"""
Tests for the Spider scorer (app/spider_eval/spider_sqlite_executor.py).

Run with ``python tests/test_scorer.py`` or ``python -m pytest tests``. They
need only the standard library: no LLM, no Spider data.
"""

import itertools
import os
import random
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.spider_eval.spider_sqlite_executor import (  # noqa: E402
    SpiderSQLiteExecutor,
    _normalize_results,
    results_match,
)


def _any_permutation_matches(pred, gold, width):
    target = _normalize_results(gold)
    return any(
        _normalize_results([tuple(row[j] for j in order) for row in pred]) == target
        for order in itertools.permutations(range(width))
    )


def test_matches_ignoring_row_order_case_and_column_order():
    assert results_match([(1, "a")], [(1, "a")]) == (True, False)
    assert results_match([("a", 1)], [(1, "a")]) == (True, True)
    assert results_match([("b", 2), ("a", 1)], [(1, "A"), (2, "b")]) == (True, True)
    assert results_match([], []) == (True, False)
    assert results_match([(None, 1)], [(1, "")]) == (True, True)  # NULL is the empty string
    assert results_match([(1, 1, "x"), (2, 2, "y")], [(1, "x", 1), (2, "y", 2)]) == (True, True)
    gold = [(i, i * 2, str(i), "k", i % 2) for i in range(8)]
    pred = [(r[3], r[4], r[0], r[2], r[1]) for r in gold]
    assert results_match(pred, gold) == (True, True)


def test_does_not_match():
    assert not results_match([(1, "a")], [(1, "b")])[0]
    assert not results_match([(1, "a"), (1, "a")], [(1, "a")])[0]  # duplicates count
    assert not results_match([(1, "a")], [(1,)])[0]  # extra column
    assert not results_match([(1,)], [(1, "a")])[0]  # missing column
    assert not results_match([(1, "a")], [("a", 1), ("b", 2)])[0]  # row count
    assert not results_match([(1, 2)], [(1, 1)])[0]  # a column cannot be used twice
    assert not results_match([(1, 1)], [(1, 2)])[0]
    assert not results_match([(1, "b"), (2, "a")], [(1, "a"), (2, "b")])[0]  # rows paired differently
    assert not results_match([(1, "a")], [])[0] and not results_match([], [(1, "a")])[0]


def test_many_identical_columns_terminate():
    width = 9
    gold = [tuple([0] * width)] * 3 + [tuple([0] * (width - 1) + [1])]
    pred = [tuple([0] * width)] * 4
    started = time.time()
    assert not results_match(pred, gold)[0]
    assert time.time() - started < 5


def test_accepts_everything_the_old_rule_did_and_nothing_but_permutations():
    random.seed(1)
    for _ in range(2000):
        width, n = random.randint(1, 4), random.randint(0, 6)

        def cell():
            return random.choice([1, 2, "a", "B", None, 3.5])

        gold = [tuple(cell() for _ in range(width)) for _ in range(n)]
        if random.random() < 0.5:
            pred = [tuple(cell() for _ in range(width)) for _ in range(n)]
        else:
            pred = [tuple(reversed(row)) for row in gold]
        old = _normalize_results(pred) == _normalize_results(gold)
        new, permuted = results_match(pred, gold)
        assert not old or (new and not permuted)
        assert new == (old or _any_permutation_matches(pred, gold, width))


def _database_with_invalid_utf8():
    path = os.path.join(tempfile.mkdtemp(), "t.sqlite")
    conn = sqlite3.connect(path)
    conn.execute("create table players(id integer, first_name text, last_name text)")
    conn.execute("insert into players values (1, 'Ann', 'Lee')")
    # 0xED is not valid UTF-8 (as in the wta_1 database)
    conn.execute("insert into players values (2, 'Treyes', cast(x'416c626172726163ed4e' as text))")
    conn.commit()
    conn.close()
    return path


def test_invalid_utf8_does_not_fail_the_query():
    path = _database_with_invalid_utf8()
    ok, error, rows = SpiderSQLiteExecutor(path).execute("SELECT first_name, last_name FROM players ORDER BY id")
    assert ok, error
    assert len(rows) == 2 and rows[1][1].startswith("Albarrac")
    # control: sqlite3's strict default really does fail on this database
    try:
        sqlite3.connect(path).execute("SELECT last_name FROM players").fetchall()
        raise AssertionError("expected a decode error")
    except sqlite3.OperationalError as exc:
        assert "decode" in str(exc).lower()


def test_compare_detailed_outcomes():
    executor = SpiderSQLiteExecutor(_database_with_invalid_utf8())
    res = executor.compare_detailed("SELECT last_name, first_name FROM players", "SELECT first_name, last_name FROM players")
    assert res.match and res.permuted and res.kind is None
    res = executor.compare_detailed("SELECT first_name FROM players", "SELECT first_name, last_name FROM players")
    assert not res.match and res.kind == "result_mismatch" and not res.permuted
    assert "Result mismatch" in res.error
    assert executor.compare_detailed("SELECT nope FROM players", "SELECT first_name FROM players").kind == "pred_failed"
    assert executor.compare_detailed("SELECT first_name FROM players", "SELECT nope FROM players").kind == "gold_failed"


def test_database_stays_read_only():
    ok, _, _ = SpiderSQLiteExecutor(_database_with_invalid_utf8()).execute("DELETE FROM players")
    assert not ok


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print("PASS ", name)
    print(f"{len(tests)} tests passed")
