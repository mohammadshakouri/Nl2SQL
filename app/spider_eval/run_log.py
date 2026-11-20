"""
Run log for the Spider evaluation.

Every evaluation run writes a directory::

    runs/<timestamp>_<mode>_<model>_k<K>[_<tag>]/
        manifest.json      what was run (config, model, prompts, code version,
                           dataset hash, environment) and, at the end, the results
        samples.jsonl      ONE LINE PER SAMPLE with everything observed for it
        schema_units.json  the retrieval units indexed for each database
        console.txt        a copy of everything printed to the terminal

``samples.jsonl`` is the source of truth. It is append-only, and each record is
flushed and fsync'ed as soon as its sample is finished, so a crash or Ctrl-C
loses at most the sample in flight. ``--resume`` continues a run from it (the
last record for a sample index wins; earlier ones are kept, never rewritten).
The metrics in the manifest are recomputed from the records, so the log can
always be re-aggregated, and re-scored offline from the stored SQL.

The record format is documented in docs/run-log-format.md.

Integrity check::

    python -m app.spider_eval.run_log check runs/<run_dir>
"""

import hashlib
import io
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from app.spider_eval.spider_evaluator import compute_metrics
from app.spider_eval.spider_sqlite_executor import QueryRun

SCHEMA_VERSION = 1

MAX_RESULT_ROWS = 50
MAX_CELL_CHARS = 200
MAX_RAW_OUTPUT_CHARS = 50_000

# Failure kinds caused by infrastructure (network, provider, bugs) rather than
# by the model. ``--resume`` re-runs these samples; model failures such as an
# empty response are kept as the model's answer.
RETRYABLE_FAILURE_KINDS = frozenset(
    {"llm_error", "retrieval_error", "internal_error", "schema_build_failed"}
)

SCORED_STATUSES = ("scored", "no_sql", "internal_error")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _cell(value):
    """A SQLite value as a JSON-safe, size-bounded cell."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS] + "…"


def _row_key(row: tuple) -> str:
    return "\x1f".join(repr(v) for v in row)


def result_snapshot(run: Optional[QueryRun]) -> Optional[dict]:
    """
    A bounded, JSON-safe record of one query execution.

    Keeps the first rows and the row count, plus hashes of the complete result
    (as returned, and with rows sorted) so two results can be compared without
    storing them in full.
    """
    if run is None:
        return None
    snap = {"ok": run.ok, "error": run.error, "ms": round(run.ms, 2)}
    if run.ok and run.rows is not None:
        rows = run.rows
        keys = [_row_key(r) for r in rows]
        snap.update(
            n_rows=len(rows),
            n_cols=len(rows[0]) if rows else None,
            rows_head=[[_cell(v) for v in row] for row in rows[:MAX_RESULT_ROWS]],
            rows_truncated=len(rows) > MAX_RESULT_ROWS,
            rows_sha256=hashlib.sha256("\x1e".join(keys).encode("utf-8", "replace")).hexdigest(),
            rows_sha256_sorted=hashlib.sha256(
                "\x1e".join(sorted(keys)).encode("utf-8", "replace")
            ).hexdigest(),
        )
    return snap


def _clean(obj):
    """Make ``obj`` strictly JSON-serialisable (no NaN/inf, no bytes)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return repr(obj)
    if isinstance(obj, (bytes, bytearray)):
        return repr(bytes(obj))
    return obj


def _dumps(obj) -> str:
    return json.dumps(_clean(obj), ensure_ascii=False, allow_nan=False, default=str)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="backslashreplace", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------

def git_info(repo_dir: str) -> dict:
    def run(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo_dir, capture_output=True, text=True, timeout=10
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": None if status is None else bool(status),
    }


def environment_info() -> dict:
    from importlib import metadata

    packages = {}
    for name in ("openai", "ollama", "chromadb", "sentence-transformers", "sqlparse", "numpy"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "sqlite": __import__("sqlite3").sqlite_version,
        "packages": packages,
    }


# ---------------------------------------------------------------------------
# Terminal transcript
# ---------------------------------------------------------------------------

class _Tee:
    """Writes to the real stream and to the transcript file."""

    def __init__(self, stream, transcript):
        self._stream = stream
        self._transcript = transcript

    def write(self, text):
        self._stream.write(text)
        try:
            self._transcript.write(text)
            self._transcript.flush()
        except ValueError:  # transcript already closed
            pass
        return len(text)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class StdoutCapture:
    """
    Remembers what is printed until ``stop()``, so output produced before a run
    directory exists (settings, dataset load, preflight) can still be written to
    that run's console.txt.
    """

    def __init__(self):
        self._buffer = io.StringIO()
        self._stdout = sys.stdout
        sys.stdout = _Tee(self._stdout, self._buffer)

    def stop(self) -> str:
        """Stop capturing (idempotent) and return everything captured."""
        if sys.stdout is not self._stdout and isinstance(sys.stdout, _Tee):
            sys.stdout = self._stdout
        return self._buffer.getvalue()


# ---------------------------------------------------------------------------
# Reading an existing log
# ---------------------------------------------------------------------------

def read_records(path: str, repair: bool = False) -> Tuple[List[dict], int]:
    """
    All records in file order, and the number of unreadable lines.

    A final line with no newline is a write that was cut off (crash): it is
    ignored, and with ``repair=True`` removed so appending can continue.
    """
    if not os.path.exists(path):
        return [], 0
    with open(path, "rb") as f:
        data = f.read()
    records: List[dict] = []
    bad = 0
    end = data.rfind(b"\n") + 1
    for line in data[:end].split(b"\n"):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            bad += 1
    if end < len(data):
        bad += 1  # the cut-off tail
        if repair:
            with open(path, "r+b") as f:
                f.truncate(end)
    return records, bad


def latest_by_index(records: Iterable[dict]) -> Dict[int, dict]:
    """The last record written for each sample index."""
    latest: Dict[int, dict] = {}
    for record in records:
        latest[record["sample_index"]] = record
    return latest


# ---------------------------------------------------------------------------
# Aggregation (the metrics are a pure function of the records)
# ---------------------------------------------------------------------------

def summarize_records(
    latest: Dict[int, dict],
    *,
    mode: str,
    k: int,
    max_attempts: Optional[int] = None,
    execution_feedback: Optional[bool] = None,
) -> dict:
    processed = [r for r in latest.values() if r["status"] in SCORED_STATUSES]
    scored = [r for r in processed if r.get("scoring")]
    total = len(processed)

    metrics = compute_metrics(
        total,
        sum(1 for r in scored if r["scoring"]["em"]),
        sum(1 for r in scored if r["scoring"]["ex"]),
    )
    failure_reasons = Counter(
        r["failure_kind"] for r in processed if r["status"] in ("no_sql", "internal_error")
    )
    metrics["mode"] = mode
    metrics["k"] = k
    metrics["skipped"] = sum(1 for r in latest.values() if r["status"] == "skipped")
    metrics["inference_failures"] = sum(failure_reasons.values())
    metrics["failure_reasons"] = dict(failure_reasons)
    metrics["llm_calls"] = sum(r["n_attempts"] for r in processed)

    if mode == "feedback":
        retried = sum(1 for r in processed if r["n_attempts"] > 1)
        recovered = sum(1 for r in processed if r.get("recovered"))
        first = compute_metrics(
            total,
            sum(1 for r in scored if r["scoring"]["first_attempt_em"]),
            sum(1 for r in scored if r["scoring"]["first_attempt_ex"]),
        )
        metrics["max_attempts"] = max_attempts
        metrics["execution_feedback"] = execution_feedback
        metrics["feedback"] = {
            "retried": retried,
            "recovered": recovered,
            "exhausted": retried - recovered,
            "first_attempt_exact_match": first["exact_match"],
            "first_attempt_execution_accuracy": first["execution_accuracy"],
        }
    return metrics


def token_totals(latest: Dict[int, dict]) -> dict:
    """Token usage summed over the run, and how many samples lack it.

    A sample counts as lacking usage only when an LLM call succeeded without
    the provider reporting any (a call that failed has no usage to report).
    """
    totals: Counter = Counter()
    missing = 0
    for record in latest.values():
        usage = record.get("usage")
        if usage:
            totals.update(usage)
        if any(a["llm"]["error"] is None and not a["llm"]["usage"] for a in record.get("attempts", [])):
            missing += 1
    return {**dict(totals), "samples_without_usage": missing}


# ---------------------------------------------------------------------------
# The run directory
# ---------------------------------------------------------------------------

class RunLog:
    """Owns a run directory: manifest, per-sample records and the transcript."""

    def __init__(self, run_dir: str, prelude: str = "", resumed: bool = False):
        self.run_dir = run_dir
        os.makedirs(run_dir, exist_ok=True)
        self.manifest_path = os.path.join(run_dir, "manifest.json")
        self.samples_path = os.path.join(run_dir, "samples.jsonl")
        self.schema_path = os.path.join(run_dir, "schema_units.json")
        self.console_path = os.path.join(run_dir, "console.txt")

        self.manifest: dict = {}
        self.session: int = 0
        self._samples = None
        self._started: Optional[float] = None
        self._stdout = None

        self._console = open(
            self.console_path, "a", encoding="utf-8", errors="backslashreplace", newline="\n"
        )
        if resumed:
            self._console.write(f"\n===== resumed {utc_now()} =====\n")
        self._console.write(prelude)
        self._console.flush()
        self._stdout = sys.stdout
        sys.stdout = _Tee(self._stdout, self._console)

    # -- creation ---------------------------------------------------------

    @classmethod
    def create(cls, out_dir: str, mode: str, model: str, k: int, tag: Optional[str] = None,
               prelude: str = "") -> "RunLog":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = "".join(c if c.isalnum() or c in "-." else "-" for c in model).strip("-")
        name = f"{stamp}_{mode}_{slug}_k{k}" + (f"_{tag}" if tag else "")
        path, n = os.path.join(out_dir, name), 1
        while os.path.exists(path):   # two runs started within the same second
            n += 1
            path = os.path.join(out_dir, f"{name}-{n}")
        return cls(path, prelude=prelude)

    @classmethod
    def resume(cls, run_dir: str, prelude: str = "") -> "RunLog":
        if not os.path.isfile(os.path.join(run_dir, "manifest.json")):
            raise FileNotFoundError(f"not a run directory (no manifest.json): {run_dir}")
        return cls(run_dir, prelude=prelude, resumed=True)

    # -- lifecycle --------------------------------------------------------

    def start(
        self, run_meta: dict, session_meta: dict, resuming: bool
    ) -> Dict[int, dict]:
        """
        Write the manifest and open ``samples.jsonl`` for appending.

        ``run_meta`` describes the run and must carry a ``fingerprint``;
        ``session_meta`` describes this process (argv, code version, environment,
        sample limit). When resuming, the fingerprint must match the stored one
        (mixing models, K or prompts in one run would make its metrics
        meaningless) and the stored run description is kept as it is.

        Returns the latest existing record per sample index (empty for a new run).
        """
        existing: Dict[int, dict] = {}
        if resuming:
            with open(self.manifest_path, encoding="utf-8") as f:
                self.manifest = json.load(f)
            diffs = _fingerprint_diffs(self.manifest.get("fingerprint", {}), run_meta["fingerprint"])
            if diffs:
                raise ValueError(
                    "cannot resume: this run differs from the one in the log:\n  "
                    + "\n  ".join(diffs)
                )
            records, _bad = read_records(self.samples_path, repair=True)
            existing = latest_by_index(records)
        else:
            if os.path.exists(self.samples_path) and os.path.getsize(self.samples_path) > 0:
                raise FileExistsError(f"refusing to overwrite an existing log: {self.samples_path}")
            self.manifest = {
                "schema_version": SCHEMA_VERSION,
                "run_id": os.path.basename(self.run_dir),
                "created_at": utc_now(),
                "sessions": [],
                **run_meta,
            }
        self.session = len(self.manifest["sessions"]) + 1
        self.manifest["sessions"].append(
            {"session": self.session, "started_at": utc_now(), "ended_at": None,
             "status": "running", "resumed": resuming, **session_meta}
        )
        self.manifest["status"] = "running"
        self._samples = open(
            self.samples_path, "a", encoding="utf-8", errors="backslashreplace", newline="\n"
        )
        self._started = time.monotonic()
        self.save_manifest()
        return existing

    def append(self, record: dict) -> None:
        """Write one sample record durably (flush + fsync)."""
        record["session"] = self.session
        self._samples.write(_dumps(record) + "\n")
        self._samples.flush()
        os.fsync(self._samples.fileno())

    def save_manifest(self, **updates) -> None:
        self.manifest.update(updates)
        _atomic_write_json(self.manifest_path, self.manifest)

    def save_schema_units(self, units_by_db: dict) -> None:
        _atomic_write_json(self.schema_path, units_by_db)

    def load_schema_units(self) -> dict:
        if not os.path.exists(self.schema_path):
            return {}
        with open(self.schema_path, encoding="utf-8") as f:
            return json.load(f)

    def finish(self, status: str, results: Optional[dict] = None) -> None:
        """Close the session with ``complete``, ``interrupted`` or ``failed``."""
        if self._samples is not None:
            self._samples.close()
            self._samples = None
        if self.manifest:
            session = self.manifest["sessions"][-1]
            session["ended_at"] = utc_now()
            session["status"] = status
            session["wall_seconds"] = round(time.monotonic() - (self._started or time.monotonic()), 1)
            updates = {"status": status}
            if results is not None:
                updates["results"] = results
            self.save_manifest(**updates)

    def close(self) -> None:
        """Stop mirroring the terminal into console.txt."""
        if self._stdout is not None:
            sys.stdout = self._stdout
            self._stdout = None
        if not self._console.closed:
            self._console.close()


def _fingerprint_diffs(old: dict, new: dict, prefix: str = "") -> List[str]:
    diffs = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        path = f"{prefix}{key}"
        if isinstance(a, dict) and isinstance(b, dict):
            diffs += _fingerprint_diffs(a, b, path + ".")
        elif a != b:
            diffs.append(f"{path}: log has {a!r}, this run has {b!r}")
    return diffs


# ---------------------------------------------------------------------------
# Integrity check:  python -m app.spider_eval.run_log check <run_dir>
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = ("sample_index", "db_id", "question", "gold_sql", "status", "n_attempts")


def check_run(run_dir: str) -> int:
    """Validate a run directory and print a summary. Returns a process exit code."""
    problems: List[str] = []
    manifest_path = os.path.join(run_dir, "manifest.json")
    samples_path = os.path.join(run_dir, "samples.jsonl")
    if not os.path.isfile(manifest_path):
        print(f"FAIL: no manifest.json in {run_dir}")
        return 1
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    records, bad = read_records(samples_path)
    if bad:
        problems.append(f"{bad} unreadable line(s) in samples.jsonl")
    for i, record in enumerate(records):
        missing = [key for key in _REQUIRED_KEYS if key not in record]
        if missing:
            problems.append(f"record {i}: missing {missing}")
    latest = latest_by_index(r for r in records if "sample_index" in r)

    print(f"run:        {manifest.get('run_id')}  (status: {manifest.get('status')})")
    llm = manifest.get("llm", {})
    print(f"model:      {llm.get('provider')} / {llm.get('model')}  temperature={llm.get('temperature')}")
    print(f"records:    {len(records)} lines, {len(latest)} samples "
          f"({len(records) - len(latest)} superseded by a later record)")
    statuses = Counter(r["status"] for r in latest.values())
    print(f"status:     {dict(statuses)}")

    config = manifest.get("config", {})
    mode, k = config.get("mode"), config.get("k")
    if mode and k:
        metrics = summarize_records(
            latest, mode=mode, k=k,
            max_attempts=config.get("max_attempts"),
            execution_feedback=config.get("execution_feedback"),
        )
        print(f"recomputed: EM {metrics['exact_match']}%  EX {metrics['execution_accuracy']}%  "
              f"over {metrics['total']} samples, {metrics['llm_calls']} LLM calls")
        stored = (manifest.get("results") or {}).get("metrics")
        if stored and stored != metrics:
            problems.append("manifest results differ from metrics recomputed from samples.jsonl")
        tokens = token_totals(latest)
        print(f"tokens:     {tokens}")
        if tokens["samples_without_usage"]:
            problems.append(f"{tokens['samples_without_usage']} sample(s) have no token usage")
        kinds = Counter(
            (r.get("scoring") or {}).get("ex_error_kind") for r in latest.values() if r.get("scoring")
        )
        print(f"ex outcome: {dict(kinds)}   (None = match)")

    expected = manifest.get("dataset", {}).get("n_samples")
    sessions = manifest.get("sessions") or [{}]
    limit = sessions[-1].get("limit")
    want = min(expected, limit) if expected and limit else expected
    if want and len(latest) < want:
        problems.append(f"only {len(latest)} of {want} samples are in the log (run incomplete: use --resume)")
    retryable = [i for i, r in latest.items()
                 if r.get("failure_kind") in RETRYABLE_FAILURE_KINDS or r.get("skip_reason") in RETRYABLE_FAILURE_KINDS]
    if retryable:
        problems.append(f"{len(retryable)} sample(s) failed on infrastructure errors (--resume re-runs them)")

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: log is complete and consistent.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        sys.exit(check_run(sys.argv[2]))
    print("usage: python -m app.spider_eval.run_log check <run_dir>")
    sys.exit(2)
