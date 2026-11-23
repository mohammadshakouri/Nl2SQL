"""
Spider Evaluator

Computes the Execution Accuracy (EX) metric for Spider benchmark evaluation.
"""

from app.spider_eval.spider_sqlite_executor import SpiderSQLiteExecutor


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
    exec_correct: int,
) -> dict:
    """
    Compute final benchmark metrics as percentages rounded to 2 decimals.

    Args:
        total: Total number of evaluated samples.
        exec_correct: Number of execution-accuracy successes.

    Returns:
        Dict with keys: total, execution_accuracy.
    """
    if total == 0:
        return {"total": 0, "execution_accuracy": 0.0}

    return {
        "total": total,
        "execution_accuracy": round(exec_correct / total * 100, 2),
    }
