"""
Run log of the benchmark evaluation (Spider and BIRD; log format 2).

Every evaluation run writes a directory::

    runs/<timestamp>_<dataset>_<mode>_<model>_k<K>[_<tag>]/
        manifest.json      what was run (config, model, prompts, code version,
                           dataset hash, environment) and, at the end, the results
        samples.jsonl      ONE LINE PER SAMPLE with the evidence for it
        schema_units.json  every retrieval unit indexed for each database
        brief.jsonl        one short line per sample, for reading failures
        console.txt        a copy of everything printed to the terminal

``samples.jsonl`` is the source of truth. It is append-only, and each record is
flushed and fsync'ed as soon as its sample is finished, so a crash or Ctrl-C
loses at most the sample in flight. ``--resume`` continues a run from it (the
last record for a sample index wins; earlier ones are kept, never rewritten).
The metrics in the manifest are recomputed from the records, so the log can
always be re-aggregated, and re-scored offline from the stored SQL.

Nothing that can be recomputed exactly is stored per sample: the text of the
retrieved units is looked up by id in ``schema_units.json``, and the prompt
sent for each attempt is rebuilt from the question, the retrieved ids and the
earlier attempts (a hash per attempt proves the rebuilt text is identical).

The record format is documented in docs/run-log-format.md.

Commands::

    python -m app.evaluation.run_log check  runs/<run_dir>
    python -m app.evaluation.run_log brief  runs/<run_dir>
    python -m app.evaluation.run_log prompt runs/<run_dir> <sample_index> [attempt]
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

from app.evaluation.benchmarks import DIFFICULTY_ORDER
from app.evaluation.executor import QueryRun

SCHEMA_VERSION = 2

# A result with at most this many rows is stored in full, so it can be
# re-scored offline (e.g. with a column-order-tolerant comparison) exactly.
MAX_RESULT_ROWS = 20
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

    Keeps the row/column counts, the first ``MAX_RESULT_ROWS`` rows and a hash of
    the complete result with its rows sorted, so two results can be compared
    without storing them in full.
    """
    if run is None:
        return None
    if not run.ok or run.rows is None:
        return {"ok": False, "error": run.error}
    rows = run.rows
    snap = {
        "ok": True,
        "n_rows": len(rows),
        "n_cols": len(rows[0]) if rows else None,
        "rows": [[_cell(v) for v in row] for row in rows[:MAX_RESULT_ROWS]],
        "sha": hashlib.sha256(
            "\x1e".join(sorted(_row_key(r) for r in rows)).encode("utf-8", "replace")
        ).hexdigest()[:16],
    }
    if len(rows) > MAX_RESULT_ROWS:
        snap["truncated"] = True
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
    return json.dumps(
        _clean(obj), ensure_ascii=False, allow_nan=False, default=str, separators=(",", ":")
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_sha(text: str) -> str:
    """Short hash stored per attempt to prove a rebuilt prompt is identical."""
    return sha256_text(text)[:12]


def _atomic_write_text(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="backslashreplace", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_json(path: str, obj) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------

def git_info(repo_dir: str, exclude_dir: Optional[str] = None) -> dict:
    """
    Commit, branch and whether the working tree has uncommitted changes.

    ``exclude_dir`` (the directory holding the run directories) is left out of
    the dirty check: a run's own output must not make the code look modified.
    """
    def run(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo_dir, capture_output=True, text=True, timeout=10
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    pathspec = ["--", "."]
    if exclude_dir:
        rel = os.path.relpath(os.path.abspath(exclude_dir), os.path.abspath(repo_dir))
        if rel not in (".", "") and not rel.startswith(".."):
            pathspec.append(":(exclude)" + rel.replace(os.sep, "/"))
    status = run("status", "--porcelain", "--untracked-files=all", *pathspec)
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


def load_units(run_dir: str) -> Dict[str, Dict[str, dict]]:
    """``{db_id: {unit_id: unit}}`` from schema_units.json."""
    path = os.path.join(run_dir, "schema_units.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {db: {u["id"]: u for u in entry["units"]} for db, entry in raw.items()}


# ---------------------------------------------------------------------------
# Aggregation (the metrics are a pure function of the records)
# ---------------------------------------------------------------------------

def compute_metrics(total: int, exec_correct: int) -> dict:
    """Execution accuracy as a percentage rounded to 2 decimals (0.0 for an empty run)."""
    return {
        "total": total,
        "execution_accuracy": round(exec_correct / total * 100, 2) if total else 0.0,
    }


def _by_difficulty(processed: List[dict]) -> dict:
    """EX per difficulty label of the dataset (empty when the samples carry none)."""
    groups: Dict[str, List[dict]] = {}
    for record in processed:
        if record.get("difficulty"):
            groups.setdefault(record["difficulty"], []).append(record)
    order = [d for d in DIFFICULTY_ORDER if d in groups] + sorted(set(groups) - set(DIFFICULTY_ORDER))
    return {
        label: compute_metrics(
            len(groups[label]),
            sum(1 for r in groups[label] if (r.get("scoring") or {}).get("ex")),
        )
        for label in order
    }


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

    metrics = compute_metrics(total, sum(1 for r in scored if r["scoring"]["ex"]))
    by_difficulty = _by_difficulty(processed)
    if by_difficulty:
        metrics["by_difficulty"] = by_difficulty
    failure_reasons = Counter(
        r["failure_kind"] for r in processed if r["status"] in ("no_sql", "internal_error")
    )
    metrics["mode"] = mode
    metrics["k"] = k
    metrics["skipped"] = sum(1 for r in latest.values() if r["status"] == "skipped")
    metrics["inference_failures"] = sum(failure_reasons.values())
    metrics["failure_reasons"] = dict(failure_reasons)
    metrics["llm_calls"] = sum(len(r["attempts"]) for r in processed)
    # EX passes that needed the columns reordered (scorer tolerance, see results_match)
    metrics["ex_column_reordered"] = sum(
        1 for r in scored if r["scoring"]["ex"] and r["scoring"].get("permuted")
    )

    if mode == "feedback":
        retried = sum(1 for r in processed if len(r["attempts"]) > 1)
        recovered = sum(1 for r in processed if r.get("recovered"))
        first = compute_metrics(total, sum(1 for r in scored if r["scoring"]["first_ex"]))
        metrics["max_attempts"] = max_attempts
        metrics["execution_feedback"] = execution_feedback
        metrics["feedback"] = {
            "retried": retried,
            "recovered": recovered,
            "exhausted": retried - recovered,
            "first_attempt_execution_accuracy": first["execution_accuracy"],
        }
    return metrics


def token_totals(latest: Dict[int, dict]) -> dict:
    """
    Token usage summed over the run, and how many samples lack it.

    A sample counts as lacking usage only when an LLM call succeeded without
    the provider reporting any (a call that failed has no usage to report).
    """
    totals: Counter = Counter()
    missing = 0
    for record in latest.values():
        lacks = False
        for attempt in record.get("attempts", []):
            tokens = attempt.get("tokens")
            if tokens:
                prompt, completion = tokens.get("prompt", 0), tokens.get("completion", 0)
                totals["prompt_tokens"] += prompt
                totals["completion_tokens"] += completion
                totals["total_tokens"] += prompt + completion
                if "reasoning" in tokens:
                    totals["reasoning_tokens"] += tokens["reasoning"]
                if "cached" in tokens:
                    totals["cached_tokens"] += tokens["cached"]
            elif not attempt.get("error"):
                lacks = True
        missing += lacks
    return {**dict(totals), "samples_without_usage": missing}


def describe_outcome(record: dict) -> Optional[str]:
    """Why a scored sample did not match the gold result (None if it matched)."""
    scoring = record.get("scoring")
    if not scoring or scoring["ex"]:
        return None
    results = record["results"]
    kind = scoring["kind"]
    if kind == "gold_failed":
        return f"Gold SQL failed: {results['gold'].get('error')}"
    if kind == "pred_failed":
        return f"Predicted SQL failed: {results['final'].get('error')}"
    if kind == "result_mismatch":
        return (f"Result mismatch: predicted {results['final']['n_rows']} row(s), "
                f"gold {results['gold']['n_rows']} row(s)")
    return f"{kind}: {(results['final'] or {}).get('error')}"


# ---------------------------------------------------------------------------
# brief.jsonl: one short line per sample, for reading failures
# ---------------------------------------------------------------------------

def brief_record(record: dict) -> dict:
    scoring = record.get("scoring") or {}
    results = record.get("results") or {}
    error = describe_outcome(record) or record.get("error")
    if not error:
        for attempt in record.get("attempts", []):
            if attempt.get("rejected"):
                error = f"attempt rejected ({attempt['rejected']['stage']}): {attempt['rejected']['error']}"
                break
    extra = {key: record[key] for key in ("evidence", "difficulty") if record.get(key)}
    return {
        "idx": record["sample_index"],
        "db": record["db_id"],
        "question": record["question"],
        **extra,
        "gold": record["gold_sql"],
        "pred": record.get("final_sql"),
        "status": record["status"] if record["status"] != "scored" else None,
        "ex": scoring.get("ex"),
        "kind": scoring.get("kind") if scoring else record.get("failure_kind") or record.get("skip_reason"),
        "attempts": len(record.get("attempts", [])),
        "first_ex": scoring.get("first_ex"),
        "rows_pred": (results.get("final") or {}).get("n_rows"),
        "rows_gold": (results.get("gold") or {}).get("n_rows"),
        "error": error,
    }


def write_brief(run_dir: str) -> int:
    """(Re)write brief.jsonl from samples.jsonl; returns the number of lines."""
    records, _bad = read_records(os.path.join(run_dir, "samples.jsonl"))
    latest = latest_by_index(r for r in records if "sample_index" in r)
    lines = [_dumps(brief_record(latest[i])) for i in sorted(latest)]
    _atomic_write_text(os.path.join(run_dir, "brief.jsonl"), "".join(line + "\n" for line in lines))
    return len(lines)


# ---------------------------------------------------------------------------
# Rebuilding the prompts that were sent
# ---------------------------------------------------------------------------

def rebuild_user_prompts(record: dict, units: Dict[str, dict]) -> List[str]:
    """
    The user prompt of every attempt of ``record``, rebuilt from the question
    (and its evidence, if it had any), the retrieved unit ids, schema_units.json
    (``units``: this db's units by id) and the earlier attempts' SQL and
    rejection messages.
    """
    from app.nl2sql_chain import NL2SQLChain
    from app.sql_validator import SQLFeedbackLoop, SQLValidator

    chain = NL2SQLChain.__new__(NL2SQLChain)   # the prompt builders do not use instance state
    context = chain.build_schema_context([units[i]["text"] for i in record["retrieved"]])
    loop = SQLFeedbackLoop(SQLValidator(), max_iterations=len(record["attempts"]) + 1)
    prompts = []
    for attempt in record["attempts"]:
        prompts.append(chain.build_user_prompt(
            record["question"], context, loop.get_feedback_prompt(), record.get("evidence")
        ))
        if attempt.get("error"):      # the call failed: nothing was checked, the loop stopped
            break
        rejected = attempt.get("rejected")
        loop.add_iteration(attempt["sql"], rejected["error"] if rejected else None, success=rejected is None)
    return prompts


def verify_prompts(run_dir: str, latest: Dict[int, dict]) -> Tuple[int, List[str]]:
    """Rebuild every prompt and compare its hash. Returns (checked, problems)."""
    units = load_units(run_dir)
    checked, problems = 0, []
    for index, record in sorted(latest.items()):
        if not record.get("attempts"):
            continue
        try:
            prompts = rebuild_user_prompts(record, units[record["db_id"]])
        except Exception as exc:
            problems.append(f"sample {index}: cannot rebuild prompts ({type(exc).__name__}: {exc})")
            continue
        for number, (attempt, prompt) in enumerate(zip(record["attempts"], prompts), start=1):
            checked += 1
            if prompt_sha(prompt) != attempt["prompt_sha"]:
                problems.append(f"sample {index} attempt {number}: rebuilt prompt differs from the one sent")
    return checked, problems


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
    def create(cls, out_dir: str, dataset: str, mode: str, model: str, k: int,
               tag: Optional[str] = None, prelude: str = "") -> "RunLog":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = "".join(c if c.isalnum() or c in "-." else "-" for c in model).strip("-")
        name = f"{stamp}_{dataset}_{mode}_{slug}_k{k}" + (f"_{tag}" if tag else "")
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
            if self.manifest.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(
                    f"cannot resume: this run uses log format {self.manifest.get('schema_version')}, "
                    f"the current code writes format {SCHEMA_VERSION}. Start a new run."
                )
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
            try:
                write_brief(self.run_dir)
            except Exception as exc:   # a convenience file must never fail a run
                print(f"note: could not write brief.jsonl: {type(exc).__name__}: {exc}")

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
# Commands
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = ("sample_index", "db_id", "question", "gold_sql", "status", "attempts")


def _metrics_differ(stored: dict, current: dict) -> bool:
    """
    True if a stored metric disagrees with the recomputed one.

    Only the metrics the current code computes are compared: a log written by
    other code may hold metrics that are no longer reported (or not yet), and
    those must not fail the check.
    """
    for key, value in stored.items():
        if key not in current:
            continue
        if isinstance(value, dict) and isinstance(current[key], dict):
            if _metrics_differ(value, current[key]):
                return True
        elif current[key] != value:
            return True
    return False


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
    if manifest.get("schema_version") != SCHEMA_VERSION:
        print(f"This run uses log format {manifest.get('schema_version')}; this checker reads "
              f"format {SCHEMA_VERSION} (see docs/run-log-format.md). Re-run to get a format "
              f"{SCHEMA_VERSION} log.")
        return 1

    records, bad = read_records(samples_path)
    if bad:
        problems.append(f"{bad} unreadable line(s) in samples.jsonl")
    for i, record in enumerate(records):
        missing = [key for key in _REQUIRED_KEYS if key not in record]
        if missing:
            problems.append(f"record {i}: missing {missing}")
    latest = latest_by_index(r for r in records if "sample_index" in r)

    code = manifest.get("code", {})
    dataset = manifest.get("dataset", {})
    options = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in (dataset.get("options") or {}).items())
    print(f"run:        {manifest.get('run_id')}  (status: {manifest.get('status')})")
    print(f"dataset:    {dataset.get('name', 'spider')}" + (f" ({options})" if options else "")
          + f"  {dataset.get('n_samples')} samples")
    llm = manifest.get("llm", {})
    print(f"model:      {llm.get('provider')} / {llm.get('model')}  temperature={llm.get('temperature')}  "
          f"reasoning_effort={llm.get('reasoning_effort')}")
    print(f"code:       {str(code.get('commit'))[:10]}  dirty={code.get('dirty')}")
    print(f"records:    {len(records)} lines, {len(latest)} samples "
          f"({len(records) - len(latest)} superseded by a later record)")
    print(f"status:     {dict(Counter(r['status'] for r in latest.values()))}")

    config = manifest.get("config", {})
    mode, k = config.get("mode"), config.get("k")
    if mode and k:
        metrics = summarize_records(
            latest, mode=mode, k=k,
            max_attempts=config.get("max_attempts"),
            execution_feedback=config.get("execution_feedback"),
        )
        print(f"recomputed: EX {metrics['execution_accuracy']}%  "
              f"over {metrics['total']} samples, {metrics['llm_calls']} LLM calls")
        stored = (manifest.get("results") or {}).get("metrics")
        if stored and _metrics_differ(stored, metrics):
            problems.append("manifest results differ from metrics recomputed from samples.jsonl")
        tokens = token_totals(latest)
        print(f"tokens:     {tokens}")
        if tokens["samples_without_usage"]:
            problems.append(f"{tokens['samples_without_usage']} sample(s) have no token usage")
        kinds = Counter((r.get("scoring") or {}).get("kind") for r in latest.values() if r.get("scoring"))
        print(f"ex outcome: {dict(kinds)}   (None = match)")

    try:
        checked, prompt_problems = verify_prompts(run_dir, latest)
        print(f"prompts:    {checked} rebuilt from ids + schema_units.json; "
              f"{len(prompt_problems)} differ from what was sent")
        problems += prompt_problems
    except ImportError as exc:
        print(f"prompts:    not verified (the project's dependencies are not importable: {exc})")

    expected = dataset.get("n_samples")
    sessions = manifest.get("sessions") or [{}]
    limit = sessions[-1].get("limit")
    want = min(expected, limit) if expected and limit else expected
    if want and len(latest) < want:
        problems.append(f"only {len(latest)} of {want} samples are in the log (run incomplete: use --resume)")
    retryable = [i for i, r in latest.items()
                 if r.get("failure_kind") in RETRYABLE_FAILURE_KINDS or r.get("skip_reason") in RETRYABLE_FAILURE_KINDS]
    if retryable:
        problems.append(f"{len(retryable)} sample(s) failed on infrastructure errors (--resume re-runs them)")

    if code.get("dirty"):
        print("\nWARNING: the run used uncommitted changes to tracked or new source files "
              "(code.dirty): commit before a run you intend to report.")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: log is complete and consistent.")
    return 0


def show_prompt(run_dir: str, index: int, attempt: int = 1) -> int:
    records, _ = read_records(os.path.join(run_dir, "samples.jsonl"))
    record = latest_by_index(records).get(index)
    if record is None or not record.get("attempts"):
        print(f"no attempts logged for sample {index}")
        return 1
    prompts = rebuild_user_prompts(record, load_units(run_dir)[record["db_id"]])
    if not 1 <= attempt <= len(prompts):
        print(f"sample {index} has {len(prompts)} attempt(s)")
        return 1
    with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    system = manifest["prompts"]["system_feedback" if attempt > 1 else "system_first"]
    sent = record["attempts"][attempt - 1]["prompt_sha"]
    print(f"=== system ===\n{system}\n=== user (identical to what was sent: "
          f"{prompt_sha(prompts[attempt - 1]) == sent}) ===\n{prompts[attempt - 1]}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "check":
        sys.exit(check_run(args[1]))
    if len(args) == 2 and args[0] == "brief":
        print(f"wrote {write_brief(args[1])} lines to {os.path.join(args[1], 'brief.jsonl')}")
        sys.exit(0)
    if len(args) in (3, 4) and args[0] == "prompt":
        sys.exit(show_prompt(args[1], int(args[2]), int(args[3]) if len(args) == 4 else 1))
    print("usage: python -m app.evaluation.run_log check|brief <run_dir>\n"
          "       python -m app.evaluation.run_log prompt <run_dir> <sample_index> [attempt]")
    sys.exit(2)
