"""
Hybrid schema retrieval.

    dense Top-K  +  BM25 Top-K  ->  merge (RRF), at most ceil(POOL_FACTOR * K) units
                                 ->  [optional: reranker  ->  Top-K]
                                 ->  completion (keys, joins, name column)

Without the reranker the merged list is the result: between K and ceil(POOL_FACTOR * K)
units (when the merge is longer than the cap, RRF's own order decides which are kept).
With the reranker the merged list goes to the cross-encoder and its best K are kept.
Completion then appends the units that a query over the retrieved tables almost always needs.

* dense: the Chroma query of ``NL2SQLChain`` (embedding similarity);
* BM25: Okapi BM25 over the text of the same retrieval units (identifier words
  are split at ``_`` and camelCase, plurals are stripped, so ``player_api_id``
  matches "player");
* RRF: reciprocal rank fusion of the two rankings;
* reranker (``--rerank`` only): a cross-encoder (default ``BAAI/bge-reranker-v2-m3``,
  loaded from the local HuggingFace cache, never downloaded) scores (query, unit text) pairs;
* completion: see ``complete``.

Everything here is pure ranking code except ``get_reranker``; the orchestration
(which collection, which texts) is ``NL2SQLChain.retrieve``.
"""

import math
import os
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

import app.dotenv as env

RRF_C = 60
"""Reciprocal rank fusion constant: score = sum over rankings of 1 / (RRF_C + rank)."""
POOL_FACTOR = 1.5
"""The merged list is cut to ceil(POOL_FACTOR * K) units, in RRF order, if it is longer."""
BM25_K1 = 1.5
BM25_B = 0.75
RERANKER_DEFAULT = "BAAI/bge-reranker-v2-m3"
RERANKER_MAX_LENGTH = 512
"""Tokens per (query, unit) pair; longer pairs are truncated."""


def pool_size(k: int) -> int:
    """The most units the merged dense + BM25 list keeps (they go to the reranker, if there is one)."""
    return max(k, math.ceil(POOL_FACTOR * k))


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[^\W_]+")      # letters/digits of any script; "_" separates words


def _stem(word: str) -> str:
    """Strip a plural ending (students -> student, countries -> country)."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 2 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    """Lower-cased words of ``text``; identifiers are split at ``_`` and camelCase."""
    return [_stem(word.lower()) for word in _WORD.findall(_CAMEL.sub(" ", text))]


class BM25Index:
    """Okapi BM25 (Lucene idf) over a fixed list of texts."""

    def __init__(self, ids: Sequence[str], texts: Sequence[str]):
        self.ids = list(ids)
        docs = [tokenize(text) for text in texts]
        self._tf = [Counter(doc) for doc in docs]
        self._len = [len(doc) for doc in docs]
        self._avg_len = (sum(self._len) / len(docs)) if docs else 0.0
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(docs)
        self._idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}

    def top(self, query: str, k: int) -> List[Tuple[str, float]]:
        """The ``k`` best (id, score) pairs, best first; texts sharing no word with the query are left out."""
        terms = [t for t in tokenize(query) if t in self._idf]
        scored = []
        for i, tf in enumerate(self._tf):
            norm = BM25_K1 * (1 - BM25_B + BM25_B * self._len[i] / self._avg_len)
            score = sum(
                self._idf[t] * tf[t] * (BM25_K1 + 1) / (tf[t] + norm) for t in terms if t in tf
            )
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [(self.ids[i], score) for score, i in scored[:k]]


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def rrf_fuse(rankings: Sequence[Sequence[str]], c: int = RRF_C) -> List[str]:
    """
    Reciprocal rank fusion: ids ordered by sum of 1 / (c + rank) over the rankings
    they appear in. Ties keep the order of first appearance (the first ranking wins).
    """
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for rank, unit_id in enumerate(ranking, start=1):
            scores[unit_id] = scores.get(unit_id, 0.0) + 1.0 / (c + rank)
    return sorted(scores, key=lambda unit_id: -scores[unit_id])


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------

_reranker = None


def reranker_source() -> str:
    """``RERANKER_MODEL_DIR`` if set, else the default model's name (resolved in the local HF cache)."""
    return env.reranker_model_dir or RERANKER_DEFAULT


def model_label(source: str) -> str:
    """A readable model name for the manifest: ``ORG/NAME`` for a HF cache snapshot path."""
    match = re.search(r"models--([^\\/]+)--([^\\/]+)", source)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    if os.path.isdir(source):
        return os.path.basename(source.rstrip("/\\")) or source
    return source        # a hub id such as BAAI/bge-reranker-v2-m3


def get_reranker():
    """The cross-encoder, loaded once per process (offline: a missing model is an error, not a download)."""
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        source = reranker_source()
        try:
            _reranker = CrossEncoder(
                source, max_length=RERANKER_MAX_LENGTH, device="cpu", local_files_only=True
            )
        except Exception as exc:
            raise RuntimeError(
                f"cannot load the reranker {source!r} from the local cache ({type(exc).__name__}: {exc}). "
                f"Set RERANKER_MODEL_DIR in .env to a downloaded cross-encoder "
                f"(default: {RERANKER_DEFAULT})."
            ) from exc
    return _reranker


def rerank(query: str, texts: Sequence[str]) -> List[float]:
    """Relevance score of each text for the query (higher is better)."""
    if not texts:
        return []
    scores = get_reranker().predict(
        [(query, text) for text in texts], batch_size=32, show_progress_bar=False
    )
    return [float(s) for s in scores]


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

_NAME_COLUMN = re.compile(r"(^|_)(name|title)$|^(name|title)(_|$)|name$", re.I)


class SchemaCatalog:
    """Which unit stands for which table, column or relation of one database (names lower-cased)."""

    def __init__(self, ids: Sequence[str], tables, columns, relations):
        """``ids``: the unit ids in ``SchemaManager.get_all_embedding_texts`` order: tables, columns, relations."""
        self.order = {unit_id: pos for pos, unit_id in enumerate(ids)}
        n_tables, n_columns = len(tables), len(columns)
        self.units_of: Dict[str, List[str]] = {}                 # table -> its table unit and column units
        self.table_of: Dict[str, str] = {}                       # table / column unit id -> table
        self.column_id: Dict[Tuple[str, str], str] = {}          # (table, column) -> unit id
        self.key_columns: Dict[str, List[str]] = {}              # table -> key column names
        self.name_column: Dict[str, str] = {}                    # table -> its name/title column unit id
        self.relations: List[Tuple[str, str, str, str, str]] = []
        for unit_id, table in zip(ids[:n_tables], tables):
            name = table.name.lower()
            self.table_of[unit_id] = name
            self.units_of[name] = [unit_id]
            self.key_columns[name] = [c.lower() for c in table.key_columns]
        named: Dict[str, List[Tuple[str, str]]] = {}
        for unit_id, column in zip(ids[n_tables : n_tables + n_columns], columns):
            table, name = column.table_name.lower(), column.column_name.lower()
            self.table_of[unit_id] = table
            self.units_of.setdefault(table, []).append(unit_id)
            self.column_id[(table, name)] = unit_id
            if _NAME_COLUMN.search(name):
                named.setdefault(table, []).append((name, unit_id))
        for table, candidates in named.items():
            exact = [c for c in candidates if c[0] in ("name", "title")]
            self.name_column[table] = (exact or candidates)[0][1]
        for unit_id, rel in zip(ids[n_tables + n_columns :], relations):
            self.relations.append((unit_id, rel.source_table.lower(), rel.source_column.lower(),
                                   rel.target_table.lower(), rel.target_column.lower()))

    @classmethod
    def from_manager(cls, manager) -> "SchemaCatalog":
        ids, _ = manager.get_all_embedding_texts()
        return cls(ids, manager.tables, manager.columns, manager.relations)


def complete(selected: Sequence[str], catalog: SchemaCatalog) -> List[str]:
    """
    Units that are not in ``selected`` but that a query over its tables almost always needs.

    A table is in play when ``selected`` holds its table unit or one of its column units. For
    each table in play: its key columns (the primary key), and one name column (``name``,
    ``title``, ``*_name``). For each relation between two tables in play: its relation unit
    and the two foreign-key columns. Returned in schema order.
    """
    have = set(selected)
    tables = {catalog.table_of[unit_id] for unit_id in have if unit_id in catalog.table_of}
    extra = set()
    for table in tables:
        for column in catalog.key_columns.get(table, []):
            extra.add(catalog.column_id.get((table, column)))
        extra.add(catalog.name_column.get(table))
    for unit_id, source, source_column, target, target_column in catalog.relations:
        if source in tables and target in tables:
            extra.update([unit_id, catalog.column_id.get((source, source_column)),
                          catalog.column_id.get((target, target_column))])
    extra.discard(None)
    return sorted(extra - have, key=catalog.order.__getitem__)


def expand(selected: Sequence[str], tables: Sequence[str], catalog: SchemaCatalog) -> List[str]:
    """
    Units to add to ``selected`` once a query over ``tables`` was rejected for a reason the schema
    context can cause (a missing column, an empty result): every table and column unit of those
    tables, then what ``complete`` adds for the enlarged set. Returned in schema order.
    """
    have = set(selected)
    extra = {unit_id for table in tables for unit_id in catalog.units_of.get(table.lower(), [])} - have
    extra.update(complete(list(have | extra), catalog))
    return sorted(extra, key=catalog.order.__getitem__)


def describe(rerank: bool) -> dict:
    """The settings that define the retrieval pipeline, for the run manifest."""
    info = {
        "dense": "Top-K",
        "bm25": {"k1": BM25_K1, "b": BM25_B, "candidates": "K"},
        "rrf_c": RRF_C,
        "pool_max": f"ceil({POOL_FACTOR} * K)",
        "rerank": rerank,
        "completion": "key columns, name column, foreign keys between retrieved tables",
        "expand_on_retry": "every column of the tables a rejected query names",
    }
    if rerank:
        info["reranker"] = model_label(reranker_source())
        info["reranker_max_length"] = RERANKER_MAX_LENGTH
    return info
