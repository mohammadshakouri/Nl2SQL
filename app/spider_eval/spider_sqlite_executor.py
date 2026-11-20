"""
Spider SQLite Executor

Executes SQL queries against Spider's SQLite databases and compares
result sets for execution accuracy evaluation.

Result comparison (``results_match``) ignores row order, letter case and the
order of the columns: a query that returns the right columns in another order
is correct. Spider's own execution check (test-suite ``result_eq``) works the
same way for column order.
"""

import sqlite3
import os
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple, List, Any
from urllib.parse import quote

# Queries running longer than this are interrupted (e.g. a JOIN without an
# ON clause producing a huge cartesian product).
DEFAULT_TIMEOUT_SECONDS = 30.0

# Upper bound on column orders tried when two results have several identical
# columns (practically never reached; a result needing more is scored a mismatch).
MAX_COLUMN_ORDERS = 10_000


def _execute_sql(conn: sqlite3.Connection, sql: str) -> Tuple[bool, Optional[str], Optional[List[tuple]]]:
    """
    Execute a SQL query and return results.

    Args:
        conn: Open SQLite connection.
        sql: SQL string to execute.

    Returns:
        (success, error_message, rows)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        return True, None, rows
    except sqlite3.OperationalError as e:
        if str(e) == "interrupted":
            return False, "query timed out (check for a missing JOIN condition)", None
        return False, str(e), None
    except Exception as e:
        return False, str(e), None


@dataclass
class QueryRun:
    """One executed query: outcome, raw rows and wall time."""
    ok: bool
    error: Optional[str]
    rows: Optional[List[tuple]]
    ms: float


@dataclass
class CompareResult:
    """Outcome of comparing a predicted query with the gold query."""
    match: bool
    error: Optional[str]
    kind: Optional[str]
    """None on a match, else ``gold_failed``, ``pred_failed`` or ``result_mismatch``."""
    pred: QueryRun
    gold: QueryRun
    permuted: bool = False
    """True when the results match only after reordering the columns."""


def _normalize_results(rows: List[tuple]) -> List[tuple]:
    """
    Normalize result rows for comparison.

    Converts all values to lowercase strings so that case differences
    in string results do not produce false negatives.  Rows are sorted
    to make comparison order-independent.

    Args:
        rows: Raw result rows from SQLite.

    Returns:
        Sorted list of normalized tuples.
    """
    normalized = []
    for row in rows:
        normalized_row = tuple(
            str(v).strip().lower() if v is not None else "" for v in row
        )
        normalized.append(normalized_row)
    return sorted(normalized)


def _column_orders(candidates: List[List[int]]) -> Iterator[Tuple[int, ...]]:
    """Every way to give each gold column a different predicted column from its candidates."""
    order: List[int] = []

    def extend(position: int) -> Iterator[Tuple[int, ...]]:
        if position == len(candidates):
            yield tuple(order)
            return
        for column in candidates[position]:
            if column not in order:
                order.append(column)
                yield from extend(position + 1)
                order.pop()

    yield from extend(0)


def results_match(
    pred_rows: List[tuple], gold_rows: List[tuple]
) -> Tuple[bool, bool]:
    """
    Do two query results hold the same data?

    Rows are compared as a multiset (order and duplicates count, order of the
    rows does not), values by ``_normalize_results`` (text, trimmed, lower
    case, NULL as empty). The columns may come in any order, but every column
    must be present exactly once.

    Returns:
        ``(match, permuted)``; ``permuted`` is True when the match needed the
        predicted columns reordered.
    """
    pred = _normalize_results(pred_rows)
    gold = _normalize_results(gold_rows)
    if pred == gold:
        return True, False
    if len(pred) != len(gold) or not gold:
        return False, False
    width = len(gold[0])
    if len(pred[0]) != width or width < 2:
        return False, False

    # A predicted column can stand for a gold column only if both hold the same values.
    gold_columns = [sorted(column) for column in zip(*gold)]
    pred_columns = [sorted(column) for column in zip(*pred)]
    candidates = [
        [j for j in range(width) if pred_columns[j] == gold_column]
        for gold_column in gold_columns
    ]
    if not all(candidates):
        return False, False

    for tried, order in enumerate(_column_orders(candidates)):
        if tried >= MAX_COLUMN_ORDERS:
            break
        if sorted(tuple(row[j] for j in order) for row in pred) == gold:
            return True, True
    return False, False


def _decode_text(raw: bytes) -> str:
    """
    Decode TEXT values as UTF-8, dropping invalid bytes.

    Some Spider databases (e.g. ``wta_1``) hold bytes that are not UTF-8; with
    sqlite3's strict default even the gold query fails on them. Dropping the
    bytes is what Spider's own test-suite evaluation does.
    """
    return raw.decode("utf-8", errors="ignore")


class SpiderSQLiteExecutor:
    """
    Executes and compares SQL queries against a Spider SQLite database.

    A SQLite database is a single file, so the executor is bound to one
    ``db_id`` by the path it is constructed with; queries need no db_id.
    """

    def __init__(self, sqlite_path: str, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        """
        Args:
            sqlite_path: Full path to the .sqlite database file.
            timeout: Seconds after which a running query is interrupted.

        Raises:
            FileNotFoundError: If the database file does not exist.
        """
        if not os.path.exists(sqlite_path):
            raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
        self.sqlite_path = sqlite_path
        self.timeout = timeout

    def _open_connection(self) -> sqlite3.Connection:
        # Read-only: predicted SQL must never modify the benchmark database
        # (a committed DELETE/DROP would corrupt every later sample).
        uri = f"file:{quote(os.path.abspath(self.sqlite_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.text_factory = _decode_text
        deadline = time.monotonic() + self.timeout
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
        return conn

    def execute(self, sql: str) -> Tuple[bool, Optional[str], Optional[List[tuple]]]:
        """
        Execute a single SQL query.

        Args:
            sql: SQL query to execute.

        Returns:
            (success, error_message, rows)
        """
        with closing(self._open_connection()) as conn:
            return _execute_sql(conn, sql)

    def compare(
        self, pred_sql: str, gold_sql: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Execute both predicted and gold SQL and compare result sets.

        Comparison is (see ``results_match``):
        - Order-independent for rows and for columns
        - Case-insensitive for string values
        - If *both* queries fail, returns False
        - If *gold* fails, returns False (benchmark data issue)
        - If *pred* fails, returns False
        - If both succeed and results match, returns True

        Args:
            pred_sql: SQL generated by the model.
            gold_sql: Ground-truth SQL from Spider dev.json.

        Returns:
            (match: bool, error_description: Optional[str])
        """
        result = self.compare_detailed(pred_sql, gold_sql)
        return result.match, result.error

    def compare_detailed(self, pred_sql: str, gold_sql: str) -> CompareResult:
        """
        :meth:`compare` plus the raw outcome of both executions, so the run log
        can keep the result rows instead of only a match/no-match verdict.
        """
        pred = self._timed_run(pred_sql)
        gold = self._timed_run(gold_sql)

        if not gold.ok:
            return CompareResult(False, f"Gold SQL failed: {gold.error}", "gold_failed", pred, gold)

        if not pred.ok:
            return CompareResult(False, f"Predicted SQL failed: {pred.error}", "pred_failed", pred, gold)

        match, permuted = results_match(pred.rows, gold.rows)
        if match:
            return CompareResult(True, None, None, pred, gold, permuted)
        return CompareResult(
            False,
            f"Result mismatch: predicted {len(pred.rows)} row(s), "
            f"gold {len(gold.rows)} row(s)",
            "result_mismatch",
            pred,
            gold,
        )

    def _timed_run(self, sql: str) -> QueryRun:
        started = time.perf_counter()
        with closing(self._open_connection()) as conn:
            ok, error, rows = _execute_sql(conn, sql)
        return QueryRun(ok, error, rows, (time.perf_counter() - started) * 1000)
