"""
Spider Evaluator

Computes Exact Match (EM) and Execution Accuracy (EX) metrics
for Spider benchmark evaluation.
"""

import re
from typing import Optional
from app.spider_eval.spider_sqlite_executor import SpiderSQLiteExecutor


# ---------------------------------------------------------------------------
# SQL normalisation helpers
# ---------------------------------------------------------------------------

def normalize_sql(sql: str) -> str:
    """
    Normalise a SQL string for exact-match comparison.

    Steps:
    1. Lowercase the entire string.
    2. Collapse multiple whitespace characters into a single space.
    3. Strip leading/trailing whitespace.
    4. Remove a trailing semicolon if present.

    Args:
        sql: Raw SQL string.

    Returns:
        Normalised SQL string.
    """
    sql = sql.lower()
    sql = re.sub(r"\s+", " ", sql)
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql


# ---------------------------------------------------------------------------
# Exact Match
# ---------------------------------------------------------------------------

def exact_match(pred_sql: str, gold_sql: str) -> bool:
    """
    Compare predicted and gold SQL after normalisation.

    Args:
        pred_sql: SQL produced by the model.
        gold_sql: Ground-truth SQL from Spider.

    Returns:
        True if normalised strings are identical.
    """
    return normalize_sql(pred_sql) == normalize_sql(gold_sql)


# ---------------------------------------------------------------------------
# Execution Accuracy
# ---------------------------------------------------------------------------

def execution_match(
    pred_sql: str,
    gold_sql: str,
    executor: SpiderSQLiteExecutor,
) -> bool:
    """
    Determine whether the predicted SQL produces the same result set as
    the gold SQL when executed against the target SQLite database.

    Rules:
    - If both queries fail → False
    - If the gold query fails → False (considered a data issue)
    - If the predicted query fails → False
    - If both succeed and result sets are identical → True

    Args:
        pred_sql: SQL produced by the model.
        gold_sql: Ground-truth SQL from Spider.
        executor: SpiderSQLiteExecutor bound to the relevant database.

    Returns:
        True if execution results match.
    """
    match, _error = executor.compare(pred_sql, gold_sql)
    return match


# ---------------------------------------------------------------------------
# Aggregated metrics
# ---------------------------------------------------------------------------

def compute_metrics(
    total: int,
    exact_correct: int,
    exec_correct: int,
) -> dict:
    """
    Compute final benchmark metrics as percentages rounded to 2 decimals.

    Args:
        total: Total number of evaluated samples.
        exact_correct: Number of exact-match successes.
        exec_correct: Number of execution-accuracy successes.

    Returns:
        Dict with keys: total, exact_match, execution_accuracy.
    """
    if total == 0:
        return {"total": 0, "exact_match": 0.0, "execution_accuracy": 0.0}

    return {
        "total": total,
        "exact_match": round(exact_correct / total * 100, 2),
        "execution_accuracy": round(exec_correct / total * 100, 2),
    }
