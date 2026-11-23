"""
Benchmarks: Spider 1 and BIRD (dev sets).

Everything that differs between the two datasets lives here: where the files
are, how a dev entry is read, which comparison rule scores EX and what extra
input a sample carries. The rest of the harness (retrieval, prompting, the
feedback loop, scoring, logging) is shared and only sees a ``Benchmark`` and its
``Sample`` objects.

Expected layouts (``<root>`` is the folder given with ``--data_path``)::

    Spider   <root>/dev.json                         question, query, db_id
             <root>/tables.json
             <root>/database/<db_id>/<db_id>.sqlite

    BIRD     <root>/dev.json                         question, evidence, SQL, db_id, difficulty
             <root>/dev_databases/<db_id>/<db_id>.sqlite
             <root>/dev_databases/<db_id>/database_description/<table>.csv

BIRD-only options (all recorded in the run manifest, so a run cannot be resumed
with different ones):

* ``evidence``     the sample's external-knowledge hint is part of the input
                   (BIRD's standard setting): it is appended to the question in
                   the prompt and also used as part of the retrieval query.
* ``descriptions`` the column descriptions of ``database_description/*.csv`` become
                   the "meaning" text of the column retrieval units (enriched
                   schema) instead of the generic "Column x of table y".

``dev_tied_append.json`` (BIRD's tied-answer variants of 42 gold queries) is not
used: it comes from an older dev set (3 of its questions have since been reworded
in dev.json) and BIRD's own evaluation scores against dev.json.
"""

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Sample:
    """One benchmark question."""
    question: str
    gold_sql: str
    db_id: str
    evidence: Optional[str] = None
    """External knowledge sent with the question (BIRD with ``evidence`` on), else None."""
    difficulty: Optional[str] = None
    """The dataset's own difficulty label (BIRD: simple / moderate / challenging)."""


@dataclass(frozen=True)
class _Spec:
    title: str
    default_dir: str
    db_dir: str
    """Folder under the root that holds ``<db_id>/<db_id>.sqlite``."""
    gold_key: str
    """Key of the gold SQL in a dev.json entry."""
    scoring: str
    """Comparison rule of EX (a key of ``executor.MATCHERS``)."""
    options: Dict[str, bool]
    """Option name -> default value."""


_SPECS: Dict[str, _Spec] = {
    "spider": _Spec("Spider 1", "Spider", "database", "query", "spider", {}),
    "bird": _Spec(
        "BIRD", "BIRD", "dev_databases", "SQL", "bird",
        {"evidence": True, "descriptions": False},
    ),
}

BENCHMARKS = tuple(_SPECS)

# BIRD's own order of difficulty labels, for reports.
DIFFICULTY_ORDER = ("simple", "moderate", "challenging")

# Longest value description (e.g. "0: no, 1: yes ...") kept in a column unit.
_MAX_VALUE_DESCRIPTION_CHARS = 250


def default_data_path(name: str) -> str:
    return _SPECS[name].default_dir


def option_names(name: str) -> Tuple[str, ...]:
    return tuple(_SPECS[name].options)


def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_text(path: str) -> str:
    """A description CSV: UTF-8 (with or without BOM); a few files are Windows-1252."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _squash(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_group(root: str, paths: List[str]) -> str:
    """One hash for several files: their relative names and contents, in name order."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(os.path.relpath(path, root).replace(os.sep, "/").encode("utf-8") + b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
    return digest.hexdigest()


class Benchmark:
    """A dataset folder plus the options chosen for this run."""

    def __init__(self, name: str, root: str, **options: Optional[bool]):
        if name not in _SPECS:
            raise ValueError(f"unknown benchmark {name!r}; choose one of {BENCHMARKS}")
        self.name = name
        self._spec = _SPECS[name]
        self.root = os.path.abspath(root)
        unknown = set(options) - set(self._spec.options)
        if unknown:
            raise ValueError(f"{self._spec.title} has no option(s): {', '.join(sorted(unknown))}")
        # None means "not given": the default applies.
        self.options: Dict[str, bool] = {
            key: default if options.get(key) is None else bool(options[key])
            for key, default in self._spec.options.items()
        }

    # -- identity -----------------------------------------------------------

    @property
    def title(self) -> str:
        return self._spec.title

    @property
    def scoring(self) -> str:
        return self._spec.scoring

    @property
    def chroma_dir_name(self) -> str:
        """Subfolder of the Chroma directory for this dataset's collections."""
        return f"{self.name}_eval"

    @property
    def collection_prefix(self) -> str:
        """Collections are named ``Schema_<prefix>_<db_id>``; enriched schemas get their own."""
        return f"{self.name}_desc" if self.options.get("descriptions") else self.name

    # -- files ----------------------------------------------------------------

    @property
    def dev_path(self) -> str:
        return os.path.join(self.root, "dev.json")

    def sqlite_path(self, db_id: str) -> str:
        return os.path.join(self.root, self._spec.db_dir, db_id, f"{db_id}.sqlite")

    def _description_dir(self, db_id: str) -> str:
        return os.path.join(self.root, self._spec.db_dir, db_id, "database_description")

    def data_files(self) -> Dict[str, str]:
        """name -> sha256 of every file that defines this run's data (for the manifest)."""
        out = {"dev.json": _sha256_file(self.dev_path)}
        if self.options.get("descriptions"):
            csvs = [
                os.path.join(self._description_dir(db), name)
                for db in self.db_ids()
                if os.path.isdir(self._description_dir(db))
                for name in os.listdir(self._description_dir(db))
                if name.lower().endswith(".csv")
            ]
            out["database_description/*.csv"] = _sha256_group(self.root, csvs)
        return out

    def db_ids(self) -> List[str]:
        base = os.path.join(self.root, self._spec.db_dir)
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))

    # -- samples ----------------------------------------------------------------

    def load_samples(self) -> List[Sample]:
        """
        The dev set in file order (a sample's index is its position in dev.json).

        Raises:
            FileNotFoundError: dev.json is missing.
            ValueError: an entry lacks a question, gold SQL or db_id.
        """
        if not os.path.exists(self.dev_path):
            raise FileNotFoundError(f"dev.json not found at: {self.dev_path}")
        entries = _read_json(self.dev_path)

        samples: List[Sample] = []
        for index, entry in enumerate(entries):
            question = entry.get("question")
            gold = entry.get(self._spec.gold_key)
            db_id = entry.get("db_id")
            if not question or not gold or not db_id:
                raise ValueError(
                    f"Entry {index} is missing one of: question, {self._spec.gold_key}, db_id. "
                    f"Got: {entry}"
                )
            evidence = None
            if self.options.get("evidence"):
                evidence = _squash(entry.get("evidence")) or None
            samples.append(
                Sample(
                    question=question.strip(),
                    gold_sql=gold.strip(),
                    db_id=db_id.strip(),
                    evidence=evidence,
                    difficulty=entry.get("difficulty"),
                )
            )
        return samples

    # -- schema enrichment ----------------------------------------------------------

    def column_meanings(self, db_id: str) -> Optional[Dict[Tuple[str, str], str]]:
        """
        ``{(table, column) lower-cased: meaning}`` from BIRD's column descriptions,
        or None when this run does not use them (always None for Spider).

        A column's meaning joins its readable name, its description and (shortened)
        its value description; parts that only repeat the column's own name are left
        out, and a column with nothing left keeps the generic text.
        """
        if not self.options.get("descriptions"):
            return None
        directory = self._description_dir(db_id)
        meanings: Dict[Tuple[str, str], str] = {}
        if not os.path.isdir(directory):
            return meanings
        for filename in sorted(os.listdir(directory)):
            if not filename.lower().endswith(".csv"):
                continue
            table = filename[:-4]
            rows = csv.DictReader(io.StringIO(_read_text(os.path.join(directory, filename))))
            for row in rows:
                column = _squash(row.get("original_column_name"))
                meaning = _meaning(column, row)
                if column and meaning:
                    meanings[(table.lower(), column.lower())] = meaning
        return meanings


def _meaning(column: str, row: dict) -> Optional[str]:
    parts: List[str] = []
    for key in ("column_name", "column_description"):
        text = _squash(row.get(key))
        if text and text.lower() != column.lower() and text.lower() not in (p.lower() for p in parts):
            parts.append(text)
    values = _squash(row.get("value_description"))
    if values:
        if len(values) > _MAX_VALUE_DESCRIPTION_CHARS:
            values = values[:_MAX_VALUE_DESCRIPTION_CHARS].rstrip() + "…"
        parts.append(f"values: {values}")
    return "; ".join(parts) or None
