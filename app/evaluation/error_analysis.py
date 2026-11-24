"""
Error analysis of an evaluation run (Spider or BIRD).

Everything here is computed from the run log (``samples.jsonl``,
``schema_units.json``), the dataset's ``dev.json`` and the hand-written labels
in ``error_labels.tsv`` next to the log. No LLM is called. For the failing
samples the gold and the final SQL are executed again (read-only) on the dataset's
databases to describe *how* the two results differ; that needs the dataset
folder, is cached in ``result_relations.json`` next to the log and can be
skipped with ``--no-reexecute``.

Two kinds of numbers come out, and they must not be confused:

* **Mechanical** (no judgement): retry and dialect statistics, Recall@K of the
  retrieval, difficulty, per-database results, how the failing results differ
  from gold, the precision of result-based signals, tokens. They are a pure
  function of the log, the gold data and the databases.
* **Judged**: the H / G / M category of each failing sample (``error_labels.tsv``).
  H is verified against the results (column order, case/format); G and M rest
  on reading the question, the evidence, the gold and the predicted SQL, and the
  ``arguable`` flag marks the G labels where another reader could reasonably say
  the model was wrong.

Categories (see ``TAXONOMY``):

* **H** - the scorer, not the model: the prediction carries the gold's information
  but the comparison rule rejects it (column order, case, rounding) or the gold
  query cannot be run.
* **G** - the gold query, the evidence or the question: the prediction is
  semantically equivalent or a defensible reading (ties, zero-count groups, an
  ambiguous question) or the gold query itself is wrong.
* **M** - the model.

Usage::

    python -m app.evaluation.error_analysis runs/<run_dir> --data_path ./Spider
    python -m app.evaluation.error_analysis runs/<run_dir> --data_path ./BIRD
    python -m app.evaluation.error_analysis runs/<run_dir> --check-only

What differs by dataset: Spider's gold columns, tables and hardness come from
the parsed ``sql`` of ``dev.json`` and ``tables.json``; BIRD has no parsed gold, so
its gold columns and tables are the ones SQLite itself reads when it compiles the
gold query (no per-role recall), and its difficulty is the dataset's own label.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations, permutations
from typing import Dict, List, Optional, Set, Tuple

from app.evaluation.benchmarks import DIFFICULTY_ORDER, Benchmark, default_data_path
from app.evaluation.executor import SQLiteExecutor, spider_results_match
from app.evaluation.run_log import latest_by_index, read_records

# category -> subtype -> what it means
TAXONOMY: Dict[str, Dict[str, str]] = {
    "H": {
        "column_order": "same rows, columns in another order (rejected by a rule that compares columns by position: BIRD's, or Spider's before it ignored column order)",
        "case_or_format": "same rows after trimming / lower-casing text and reading NULL as empty (rejected by BIRD's exact comparison)",
        "rounding": "same numbers at another precision (e.g. ROUND, or percentages with a different number of decimals)",
        "gold_unreadable": "the gold query cannot be run by the harness (invalid UTF-8 in the database)",
        "gold_timeout": "the gold query exceeds the 30 s limit, so it can never be scored",
    },
    "G": {
        "gold_incorrect": "the gold query does not answer the question as asked",
        "gold_text_column_quirk": "gold relies on string comparison/ordering of a numeric-looking TEXT column",
        "gold_literal_case": "gold compares with a lower-case literal, so it matches nothing (or everything)",
        "gold_empty_result": "gold returns 0 rows because of a data quirk (whitespace)",
        "gold_missing_projection": "gold omits a column the question asks for",
        "gold_extra_projection": "gold returns columns the question does not ask for",
        "gold_grain_quirk": "gold groups at another grain than the question states",
        "gold_nondeterministic": "gold returns an arbitrary value (bare column in GROUP BY)",
        "ties_limit": "tie for the top value; gold LIMIT 1 and the prediction pick different rows",
        "distinct_duplicates": "gold keeps duplicate rows, the prediction uses DISTINCT",
        "zero_count_groups": "LEFT JOIN keeps groups with count 0, gold uses an inner join",
        "ambiguous_question": "the question admits more than one reading; the prediction is a defensible one",
        "ambiguous_column": "several columns fit the wording (e.g. Maker vs FullName)",
        "ambiguous_projection": "the wording does not fix which or how many columns to return",
        "projection_format": "one concatenated column versus separate columns",
        "evidence_wrong": "the evidence misdescribes the data or contradicts the gold; the prediction follows the evidence",
        "gold_ignores_evidence": "the gold query does not apply the formula or value mapping the evidence states",
        "gold_integer_division": "gold divides integers (no CAST), so its numbers are truncated; the prediction computes the real ratio",
        "gold_null_quirk": "gold's handling of NULLs (ORDER BY ... LIMIT, aggregates over NULL) differs from the natural reading",
        "gold_wrong_literal": "gold filters by a value that does not fit the question or the data",
        "gold_loose_join": "gold relates two tables only through a shared id (e.g. molecule_id), so it matches every row of the parent, not the rows that are actually connected; the prediction follows the real connection",
    },
    "M": {
        "value_mismatch": "literal differs from the stored value (case, punctuation, abbreviation, LIKE vs =)",
        "wrong_column": "a different column than the question needs",
        "wrong_join_path": "wrong tables or join keys, missing join condition",
        "fk_not_followed": "uses a foreign-key id where the referenced table's name/attribute is needed",
        "missing_condition": "a condition of the question is dropped",
        "extra_condition": "an unrequested condition is added",
        "extra_projection": "returns a column the question does not ask for",
        "missing_projection": "omits a column the question asks for",
        "set_logic": "INTERSECT / EXCEPT / NOT IN / both-and logic is wrong",
        "superlative_logic": "wrong direction or missing top-1 restriction",
        "aggregation_grain": "aggregates at the wrong grain",
        "degenerate_sql": "an always-empty query (WHERE 1 = 0, LIMIT 0)",
        "domain_knowledge": "needs domain knowledge (e.g. highest rank = smallest number)",
        "missing_distinct": "duplicates of the same entity are returned",
        "unnecessary_cast": "a CAST changes the returned values",
        "evidence_ignored": "the evidence gives the formula, column or value mapping and the prediction does not use it",
        "evidence_misapplied": "the evidence is used, but wrongly (wrong column, operator or formula)",
        "integer_division": "a ratio or percentage is computed with integer division (no CAST AS REAL)",
        "date_handling": "wrong date/time function, format or range (strftime, SUBSTR, year bounds)",
        "wrong_table": "a different table than the one the question needs (similar tables)",
        "wrong_aggregate": "wrong aggregate (COUNT vs COUNT DISTINCT, SUM vs COUNT, AVG vs ratio)",
        "wrong_formula": "a different formula than the evidence or question states (percentage vs ratio, scale)",
        "execution_error": "the final SQL does not run (the feedback loop ran out of attempts)",
        "rounding_ignored": "the question asks for a number of decimals and the prediction does not round to it (e.g. CAST AS DECIMAL does not round in SQLite)",
        "data_quirk": "a reasonable query fails on a data peculiarity the schema does not show (leading zeros in codes, numbers stored as text)",
        "other": "none of the above",
    },
}

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def load_labels(path: str) -> Dict[int, dict]:
    """``error_labels.tsv`` -> {sample_index: {category, subtype, arguable, also, note}}."""
    labels: Dict[int, dict] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            labels[int(row["sample_index"])] = {
                "category": row["category"],
                "subtype": row["subtype"],
                "arguable": row["arguable"] == "1",
                "also": row["also"],
                "note": row["note"],
            }
    return labels


def column_order_check(record: dict) -> str:
    """
    Would a column-order-tolerant comparison (the Spider scorer's ``spider_results_match``)
    accept this sample's stored results?

    ``"full"``         yes, checked on the complete stored results
    ``"partial"``      the results have more than 20 rows and the first 20 rows match
                       under a column reordering (necessary, not sufficient)
    ``"undetermined"`` more than 20 rows and the stored rows do not match: the rows
                       are only the first 20 in query order, so a different group
                       order alone can explain it
    ``"no_match"``     the complete results do not match, even with columns reordered
    """
    gold, pred = record["results"]["gold"], record["results"]["final"]
    if not (gold.get("ok") and pred.get("ok")):
        return "no_match"
    truncated = bool(gold.get("truncated") or pred.get("truncated"))
    if gold["n_rows"] != pred["n_rows"] or gold["n_cols"] != pred["n_cols"]:
        return "no_match"
    match, permuted = spider_results_match(
        [tuple(r) for r in pred["rows"]], [tuple(r) for r in gold["rows"]]
    )
    if match and permuted:
        return "partial" if truncated else "full"
    return "undetermined" if truncated else "no_match"


def validate_labels(
    latest: Dict[int, dict], labels: Dict[int, dict], relations: Optional[Dict[int, dict]] = None,
) -> List[str]:
    """
    Everything that must hold for the labels to be usable; empty list = fine.

    ``relations`` (from :func:`reexecute_relations`) makes the H checks exact: with it,
    a result that is a column permutation (or only differs in case/format) of gold must
    be labelled H, and an H label of that kind must be true. Without it the checks use
    the (at most 20) stored result rows.
    """
    problems: List[str] = []
    failing = {i for i, r in latest.items() if not r["scoring"]["ex"]}
    for i in sorted(failing - set(labels)):
        problems.append(f"sample {i} fails but has no label")
    for i in sorted(set(labels) - failing):
        problems.append(f"sample {i} is labelled but did not fail")
    for i, label in sorted(labels.items()):
        if label["subtype"] not in TAXONOMY.get(label["category"], {}):
            problems.append(f"sample {i}: unknown label {label['category']}/{label['subtype']}")
    for i, record in sorted(latest.items()):
        if i in failing and i in labels:
            label = labels[i]
            pair = (label["category"], label["subtype"])
            if relations is not None and i in relations:
                rel = relations[i]["rel"]
                if rel in ("column_order", "case_or_format") and pair != ("H", rel):
                    problems.append(f"sample {i}: the re-executed result differs from gold only by "
                                    f"'{rel}' but it is labelled {pair[0]}/{pair[1]}")
                if pair in (("H", "column_order"), ("H", "case_or_format")) and rel != pair[1]:
                    problems.append(f"sample {i}: labelled {pair[0]}/{pair[1]}, but the re-executed "
                                    f"result relation is '{rel}'")
                continue
            mechanical = column_order_check(record)
            if mechanical == "full" and pair != ("H", "column_order"):
                problems.append(f"sample {i}: result is a column permutation of gold but labelled "
                                f"{pair[0]}/{pair[1]}")
            if pair == ("H", "column_order") and mechanical == "no_match":
                problems.append(f"sample {i}: labelled H/column_order, but the first rows are not a "
                                "column permutation of gold (check by hand)")
    return problems


# ---------------------------------------------------------------------------
# Spider gold: referenced columns and difficulty
# ---------------------------------------------------------------------------


def _walk_valunit(val_unit, roles: Dict[int, Set[str]], role: str) -> None:
    for col_unit in (val_unit[1], val_unit[2]):
        if col_unit and col_unit[1] != 0:
            roles[col_unit[1]].add(role)


def _walk_cond(cond, roles: Dict[int, Set[str]], role: str) -> None:
    _walk_valunit(cond[2], roles, role)
    for operand in cond[3:5]:
        if isinstance(operand, dict):
            gold_columns(operand, roles)
        elif isinstance(operand, list) and len(operand) == 3 and isinstance(operand[1], int) and operand[1] != 0:
            roles[operand[1]].add(role)


def gold_columns(sql: dict, roles: Optional[Dict[int, Set[str]]] = None) -> Dict[int, Set[str]]:
    """Column ids of ``tables.json`` used by a parsed gold query, with their roles."""
    roles = defaultdict(set) if roles is None else roles
    for unit in sql["from"]["table_units"]:
        if unit[0] == "sql":
            gold_columns(unit[1], roles)
    for cond in sql["from"]["conds"]:
        if isinstance(cond, list):
            _walk_cond(cond, roles, "join")
    for _, val_unit in sql["select"][1]:
        _walk_valunit(val_unit, roles, "select")
    for cond in sql["where"] + sql["having"]:
        if isinstance(cond, list):
            _walk_cond(cond, roles, "filter")
    for col_unit in sql["groupBy"]:
        if col_unit[1] != 0:
            roles[col_unit[1]].add("group")
    if sql["orderBy"]:
        for val_unit in sql["orderBy"][1]:
            _walk_valunit(val_unit, roles, "order")
    for key in ("intersect", "union", "except"):
        if sql[key]:
            gold_columns(sql[key], roles)
    return roles


def gold_tables(sql: dict, out: Optional[Set[int]] = None) -> Set[int]:
    out = set() if out is None else out
    for unit in sql["from"]["table_units"]:
        if unit[0] == "table_unit":
            out.add(unit[1])
        else:
            gold_tables(unit[1], out)
    for key in ("intersect", "union", "except"):
        if sql[key]:
            gold_tables(sql[key], out)
    for cond in sql["from"]["conds"] + sql["where"] + sql["having"]:
        if isinstance(cond, list):
            for operand in cond[3:5]:
                if isinstance(operand, dict):
                    gold_tables(operand, out)
    return out


# Spider's own hardness rules (evaluation.py), ported unchanged.
_WHERE_LIKE = 9


def _count_agg(units) -> int:
    return len([u for u in units if u[0] != 0])


def _nested(sql: dict) -> list:
    nested = []
    for cond in sql["from"]["conds"][::2] + sql["where"][::2] + sql["having"][::2]:
        for operand in cond[3:5]:
            if isinstance(operand, dict):
                nested.append(operand)
    for key in ("intersect", "except", "union"):
        if sql[key] is not None:
            nested.append(sql[key])
    return nested


def _component1(sql: dict) -> int:
    n = 0
    n += 1 if sql["where"] else 0
    n += 1 if sql["groupBy"] else 0
    n += 1 if sql["orderBy"] else 0
    n += 1 if sql["limit"] is not None else 0
    if sql["from"]["table_units"]:
        n += len(sql["from"]["table_units"]) - 1
    connectors = sql["from"]["conds"][1::2] + sql["where"][1::2] + sql["having"][1::2]
    n += len([t for t in connectors if t == "or"])
    conds = sql["from"]["conds"][::2] + sql["where"][::2] + sql["having"][::2]
    n += len([c for c in conds if c[1] == _WHERE_LIKE])
    return n


def _others(sql: dict) -> int:
    n = 0
    agg = _count_agg(sql["select"][1]) + _count_agg(sql["where"][::2]) + _count_agg(sql["groupBy"])
    if sql["orderBy"]:
        agg += _count_agg([u[1] for u in sql["orderBy"][1] if u[1]] + [u[2] for u in sql["orderBy"][1] if u[2]])
    agg += _count_agg(sql["having"])
    n += 1 if agg > 1 else 0
    n += 1 if len(sql["select"][1]) > 1 else 0
    n += 1 if len(sql["where"]) > 1 else 0
    n += 1 if len(sql["groupBy"]) > 1 else 0
    return n


def hardness(sql: dict) -> str:
    c1, c2, others = _component1(sql), len(_nested(sql)), _others(sql)
    if c1 <= 1 and others == 0 and c2 == 0:
        return "easy"
    if (others <= 2 and c1 <= 1 and c2 == 0) or (c1 <= 2 and others < 2 and c2 == 0):
        return "medium"
    if (others > 2 and c1 <= 2 and c2 == 0) or (2 < c1 <= 3 and others <= 2 and c2 == 0) or (
        c1 <= 1 and others == 0 and c2 <= 1
    ):
        return "hard"
    return "extra"


# ---------------------------------------------------------------------------
# Dataset adapters: what the gold query needs, and how hard it is
# ---------------------------------------------------------------------------

# A gold query that selects ``*`` (or ``t.*``) makes SQLite read every column of the
# table, which would count columns the query does not name; such samples contribute
# only their tables to the retrieval analysis.
_STAR_PROJECTION = re.compile(r"(?i)(\bselect\s+(distinct\s+)?|,\s*)(\w+\.|`[^`]+`\.|\"[^\"]+\"\.)?\*\s*(,|\bfrom\b)")


class _SpiderGold:
    """Gold references and hardness from Spider's parsed ``sql`` and ``tables.json``."""

    difficulty_levels = ("easy", "medium", "hard", "extra")
    difficulty_title = "Spider hardness"
    role_aware = True

    def __init__(self, benchmark: Benchmark):
        with open(benchmark.dev_path, encoding="utf-8") as f:
            self.dev = json.load(f)
        with open(os.path.join(benchmark.root, "tables.json"), encoding="utf-8") as f:
            self.tables = {t["db_id"]: t for t in json.load(f)}

    def mismatch(self, index: int, record: dict) -> bool:
        return self.dev[index]["question"] != record["question"] or self.dev[index]["db_id"] != record["db_id"]

    def difficulty(self, index: int) -> str:
        return hardness(self.dev[index]["sql"])

    def references(self, index: int, db_id: str):
        """``({(table, column): roles}, {tables}, star_projection)``, names lower-cased."""
        schema = self.tables[db_id]
        names, table_names = schema["column_names_original"], schema["table_names_original"]
        sql = self.dev[index]["sql"]
        columns = {
            (table_names[names[c][0]].lower(), names[c][1].lower()): roles
            for c, roles in gold_columns(sql).items()
        }
        tables = {table_names[t].lower() for t in gold_tables(sql)}
        return columns, tables, False


class _BirdGold:
    """
    Gold references of BIRD: SQLite's own account of what the gold query reads.

    A BIRD ``dev.json`` has no parsed gold SQL, so the query is compiled
    (``EXPLAIN``) with an authorizer that sees every ``(table, column)`` the
    statement reads, with aliases and subqueries already resolved. The role of a
    column (select / filter / join ...) is not part of that, so no per-role recall.
    """

    difficulty_levels = DIFFICULTY_ORDER
    difficulty_title = "BIRD difficulty"
    role_aware = False

    def __init__(self, benchmark: Benchmark):
        self.benchmark = benchmark
        self.samples = benchmark.load_samples()

    def mismatch(self, index: int, record: dict) -> bool:
        sample = self.samples[index]
        return sample.question != record["question"] or sample.db_id != record["db_id"]

    def difficulty(self, index: int) -> str:
        return self.samples[index].difficulty or "unknown"

    def references(self, index: int, db_id: str):
        sample = self.samples[index]
        reads: Set[Tuple[str, str]] = set()

        def authorizer(action, arg1, arg2, _db, _trigger):
            if action == sqlite3.SQLITE_READ and arg1 and not arg1.startswith("sqlite_"):
                reads.add((arg1.lower(), (arg2 or "").lower()))
            return sqlite3.SQLITE_OK

        uri = "file:" + self.benchmark.sqlite_path(db_id).replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.set_authorizer(authorizer)
            conn.execute("EXPLAIN " + sample.gold_sql)
        finally:
            conn.close()
        star = bool(_STAR_PROJECTION.search(sample.gold_sql))
        tables = {table for table, _ in reads}
        columns = {} if star else {(table, column): set() for table, column in reads if column}
        return columns, tables, star


def make_gold(benchmark: Benchmark):
    return _SpiderGold(benchmark) if benchmark.name == "spider" else _BirdGold(benchmark)


# ---------------------------------------------------------------------------
# How a failing result differs from the gold result
# ---------------------------------------------------------------------------


def _norm_cell(value) -> str:
    """Text, trimmed, lower-cased, NULL as empty, whole floats as integers (a loose view of a cell)."""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return str(value).strip().lower()


def _round_cell(value, digits: int):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return _norm_cell(value)


def _column_selections(width: int, k: int):
    """The ways to pick ``k`` of ``width`` columns (ordered when there are few, else in order)."""
    ordered = 1
    for step in range(k):
        ordered *= width - step
    return permutations(range(width), k) if ordered <= 3000 else combinations(range(width), k)


RELATIONS = {
    "equal": "the same distinct rows; only the number of duplicates differs (a Spider log)",
    "pred_error": "the predicted SQL does not run",
    "gold_error": "the gold SQL does not run (error or 30 s timeout)",
    "pred_empty": "the prediction returns no rows, gold does",
    "gold_empty": "gold returns no rows, the prediction does",
    "column_order": "same rows, the columns are in another order",
    "case_or_format": "same rows after trimming / lower-casing text and reading NULL as empty",
    "rounding": "same numbers at another precision (2-4 decimals)",
    "extra_columns": "all gold columns are there, plus extra column(s); the rows match",
    "extra_columns_rows_subset": "extra column(s), and fewer rows than gold",
    "extra_columns_rows_superset": "extra column(s), and more rows than gold",
    "more_columns_other": "more columns than gold, and the gold columns are not reproduced",
    "missing_columns": "a gold column is missing; the remaining columns match",
    "missing_columns_rows_subset": "a gold column is missing, and fewer rows than gold",
    "missing_columns_rows_superset": "a gold column is missing, and more rows than gold",
    "fewer_columns_other": "fewer columns than gold, and they do not reproduce a part of gold",
    "rows_subset": "same columns, a strict subset of gold's rows",
    "rows_superset": "same columns, a strict superset of gold's rows",
    "rows_overlap": "same columns, the rows overlap partly",
    "scalar_differs": "one value against one value, and they differ",
    "rows_disjoint": "same columns, no row in common",
}


def result_relation(pred_rows: List[tuple], gold_rows: List[tuple], scoring: str = "bird") -> str:
    """
    A key of ``RELATIONS``: how a failing result differs from gold. The comparisons
    other than the first one look at the distinct rows. ``equal`` means the two row
    sets are the same (on a Spider log: only the duplicates differ).

    ``column_order`` / ``case_or_format`` follow the run's scoring rule: BIRD ignores
    duplicates, Spider counts them (so there the matcher sees every row).
    """
    pred, gold = set(pred_rows), set(gold_rows)
    if pred == gold:
        return "equal"
    if not pred_rows:
        return "pred_empty"
    if not gold_rows:
        return "gold_empty"
    if scoring == "bird":
        match, permuted = spider_results_match(list(pred), list(gold))
    else:
        match, permuted = spider_results_match(pred_rows, gold_rows)
    if match:
        return "column_order" if permuted else "case_or_format"
    width_pred, width_gold = len(pred_rows[0]), len(gold_rows[0])
    if width_pred == width_gold:
        for digits in (2, 3, 4):
            if {tuple(_round_cell(v, digits) for v in r) for r in pred_rows} == {
                tuple(_round_cell(v, digits) for v in r) for r in gold_rows
            }:
                return "rounding"
    pred_set = {tuple(_norm_cell(v) for v in r) for r in pred_rows}
    gold_set = {tuple(_norm_cell(v) for v in r) for r in gold_rows}
    if width_pred > width_gold:
        parts = [{tuple(_norm_cell(r[j]) for j in cols) for r in pred_rows}
                 for cols in _column_selections(width_pred, width_gold)]
        if any(p == gold_set for p in parts):
            return "extra_columns"
        if any(p < gold_set for p in parts):
            return "extra_columns_rows_subset"
        if any(p > gold_set for p in parts):
            return "extra_columns_rows_superset"
        return "more_columns_other"
    if width_pred < width_gold:
        parts = [{tuple(_norm_cell(r[j]) for j in cols) for r in gold_rows}
                 for cols in _column_selections(width_gold, width_pred)]
        if any(p == pred_set for p in parts):
            return "missing_columns"
        if any(pred_set < p for p in parts):
            return "missing_columns_rows_subset"
        if any(pred_set > p for p in parts):
            return "missing_columns_rows_superset"
        return "fewer_columns_other"
    if pred_set < gold_set:
        return "rows_subset"
    if pred_set > gold_set:
        return "rows_superset"
    if pred_set & gold_set:
        return "rows_overlap"
    if len(pred_rows) == 1 and len(gold_rows) == 1:
        return "scalar_differs"
    return "rows_disjoint"


def _sql_sha(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def reexecute_relations(
    run_dir: str, benchmark: Benchmark, latest: Dict[int, dict], refresh: bool = False,
    write_cache: bool = True,
) -> Dict[int, dict]:
    """
    ``{sample_index: {rel, n_pred, n_gold, w_pred, w_gold}}`` for every failing sample,
    from running its gold and its final SQL on the database (read-only, 30 s per query).

    Cached in ``result_relations.json`` next to the log, per sample and keyed by the
    hash of both queries, so a changed log or dev.json recomputes only what changed.
    """
    scoring = benchmark.scoring
    samples = benchmark.load_samples()
    cache_path = os.path.join(run_dir, "result_relations.json")
    cache: Dict[str, dict] = {}
    if os.path.exists(cache_path) and not refresh:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    relations: Dict[int, dict] = {}
    dirty = False
    for i in sorted(latest):
        record = latest[i]
        if record["scoring"]["ex"]:
            continue
        key = _sql_sha(samples[i].gold_sql) + _sql_sha(record["final_sql"])
        entry = cache.get(str(i))
        if not entry or entry.get("key") != key:
            executor = SQLiteExecutor(benchmark.sqlite_path(samples[i].db_id), scoring=scoring)
            gold_ok, gold_error, gold_rows = executor.execute(samples[i].gold_sql)
            pred_ok, pred_error, pred_rows = executor.execute(record["final_sql"])
            entry = {"key": key}
            if not pred_ok:
                entry.update(rel="pred_error", error=pred_error)
            elif not gold_ok:
                entry.update(rel="gold_error", error=gold_error)
            else:
                entry.update(
                    rel=result_relation(pred_rows, gold_rows, scoring),
                    n_pred=len(pred_rows), n_gold=len(gold_rows),
                    w_pred=len(pred_rows[0]) if pred_rows else 0,
                    w_gold=len(gold_rows[0]) if gold_rows else 0,
                )
            cache[str(i)] = entry
            dirty = True
        relations[i] = entry
    if dirty and write_cache:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=0)
    return relations


# ---------------------------------------------------------------------------
# Feedback loop: what made the first attempt fail
# ---------------------------------------------------------------------------

_DIALECT_PATTERNS = [
    ("FETCH FIRST/NEXT n ROWS (not SQLite)", re.compile(r"\bFETCH\s+(FIRST|NEXT)\b", re.I)),
    ("ALL/ANY/SOME subquery comparison (not SQLite)", re.compile(r"(=|<|>)\s*(ALL|ANY|SOME)\s*\(", re.I)),
    ("ANSI function with FROM (EXTRACT/SUBSTRING/POSITION/TRIM)",
     re.compile(r"\b(EXTRACT|SUBSTRING|POSITION|TRIM)\s*\([^()]*\bFROM\b", re.I)),
]


def classify_rejection(rejected: dict, sql: str) -> str:
    error = rejected["error"]
    if "Could not decode to UTF-8" in error:
        return "harness: UTF-8 decode error of the database"
    if rejected["stage"] == "semantic":
        return "semantic: empty result"
    if rejected["stage"] == "static":
        return "static validator: table not found"
    if "syntax error" in error:
        for label, pattern in _DIALECT_PATTERNS:
            if pattern.search(sql):
                return "dialect: " + label
        return "syntax error (other)"
    if "no such column" in error:
        return "no such column"
    return "other execution error"


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------


def check_labels(run_dir: str, labels_path: Optional[str] = None) -> List[str]:
    """
    Validate ``error_labels.tsv`` against the run log (needs no dataset files).

    Uses ``result_relations.json`` when the analysis has made one, else the (at most
    20) result rows stored in the log.
    """
    records, _ = read_records(os.path.join(run_dir, "samples.jsonl"))
    latest = latest_by_index(records)
    labels = load_labels(labels_path or os.path.join(run_dir, "error_labels.tsv"))
    relations = None
    cache_path = os.path.join(run_dir, "result_relations.json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            relations = {int(i): entry for i, entry in json.load(f).items()}
    return validate_labels(latest, labels, relations)


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def _manifest(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def retrieval_ks(k: int) -> Tuple[int, ...]:
    """The cut-offs the retrieval is reported at: 5, 10, 15, 20, 30 ... up to the run's K, and K itself."""
    return tuple(sorted({c for c in (5, 10, 15, 20, 30, 50) if c < k} | {k}))


def benchmark_of_run(run_dir: str, data_path: str) -> Benchmark:
    """The ``Benchmark`` a run was made on, rebuilt from its manifest and the dataset folder."""
    manifest = _manifest(run_dir)
    name = (manifest.get("dataset") or {}).get("name", "spider")
    options = (manifest.get("config") or {}).get("dataset_options") or {}
    return Benchmark(name, data_path, **options)


def analyse(
    run_dir: str,
    data_path: str,
    labels_path: Optional[str] = None,
    reexecute: bool = True,
    refresh: bool = False,
    write_cache: bool = True,
) -> dict:
    records, _ = read_records(os.path.join(run_dir, "samples.jsonl"))
    latest = latest_by_index(records)
    n = len(latest)
    manifest = _manifest(run_dir)
    k = int(manifest["config"]["k"])
    ks = retrieval_ks(k)
    benchmark = benchmark_of_run(run_dir, data_path)
    gold = make_gold(benchmark)
    labels = load_labels(labels_path or os.path.join(run_dir, "error_labels.tsv"))
    relations = (reexecute_relations(run_dir, benchmark, latest, refresh, write_cache)
                 if reexecute else None)
    problems = validate_labels(latest, labels, relations)

    with open(os.path.join(run_dir, "schema_units.json"), encoding="utf-8") as f:
        units = json.load(f)
    for i, record in latest.items():
        if gold.mismatch(i, record):
            problems.append(f"sample {i}: dev.json row differs from the log (wrong dev.json?)")

    out: dict = {
        "run": os.path.basename(os.path.normpath(run_dir)), "dataset": benchmark.name,
        "k": k, "n_samples": n, "label_problems": problems,
    }
    ids = sorted(latest)
    ex = {i: latest[i]["scoring"]["ex"] for i in ids}
    failing = [i for i in ids if not ex[i]]

    # ---- overview and feedback loop
    first_ex = sum(latest[i]["scoring"]["first_ex"] for i in ids)
    out["overview"] = {
        "ex": sum(ex.values()), "ex_pct": _pct(sum(ex.values()), n),
        "single_pass_ex": first_ex, "single_pass_ex_pct": _pct(first_ex, n),
        "failing": len(failing),
    }
    attempts = Counter(len(latest[i]["attempts"]) for i in ids)
    rejections: Counter = Counter()
    first_rejection: Dict[str, Counter] = defaultdict(Counter)
    for i in ids:
        record = latest[i]
        for attempt in record["attempts"]:
            if attempt["rejected"]:
                rejections[attempt["rejected"]["stage"]] += 1
        first = record["attempts"][0]
        if first["rejected"]:
            kind = classify_rejection(first["rejected"], first["sql"])
            first_rejection[kind]["samples"] += 1
            first_rejection[kind]["final_ex"] += int(ex[i])
    transitions = Counter((latest[i]["scoring"]["first_ex"], ex[i]) for i in ids)
    out["loop"] = {
        "attempts_distribution": dict(sorted(attempts.items())),
        "llm_calls": sum(len(latest[i]["attempts"]) for i in ids),
        "samples_retried": sum(1 for i in ids if len(latest[i]["attempts"]) > 1),
        "recovered": sum(1 for i in ids if latest[i]["recovered"]),
        "fallback_to_attempt_1": sum(1 for i in ids if latest[i]["fallback"]),
        "rejections_by_stage": dict(rejections),
        "first_attempt_rejection_kinds": {k: dict(v) for k, v in sorted(first_rejection.items(), key=lambda kv: -kv[1]["samples"])},
        "single_pass_wrong_final_right": transitions[(False, True)],
        "single_pass_right_final_wrong": transitions[(True, False)],
        "failing_samples_whose_sql_ran": sum(
            1 for i in failing if latest[i]["results"]["final"].get("ok")),
    }

    # ---- taxonomy
    by_sub: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for i, label in labels.items():
        by_sub[(label["category"], label["subtype"])].append(i)
    category_totals = Counter(label["category"] for label in labels.values())
    arguable = Counter(label["category"] for label in labels.values() if label["arguable"])
    out["taxonomy"] = {
        "categories": {
            c: {"count": category_totals[c], "pct_of_all": _pct(category_totals[c], n),
                "arguable": arguable[c]}
            for c in ("H", "G", "M")
        },
        "subtypes": {
            f"{c}/{s}": {
                "description": TAXONOMY.get(c, {}).get(s, "(unknown label)"), "count": len(v),
                "arguable": sum(labels[i]["arguable"] for i in v),
                "pct_of_all": _pct(len(v), n), "samples": sorted(v),
            }
            for (c, s), v in sorted(by_sub.items(), key=lambda kv: (kv[0][0], -len(kv[1])))
        },
        # with the re-executed relations the check uses the complete results, not the stored rows
        "column_order_verification": dict(Counter(
            ("full" if relations[i]["rel"] == "column_order" else "no_match")
            if relations is not None and i in relations else column_order_check(latest[i])
            for i in by_sub[("H", "column_order")])),
    }
    n_h, n_g, n_m = (category_totals[c] for c in ("H", "G", "M"))
    g_certain = n_g - arguable["G"]
    ex_n = sum(ex.values())
    out["adjusted_ex"] = {
        "reported": _pct(ex_n, n),
        "scorer_fixed (+H)": _pct(ex_n + n_h, n),
        "plus_certain_gold_issues (+H +G not arguable)": _pct(ex_n + n_h + g_certain, n),
        "plus_all_G (+H +G)": _pct(ex_n + n_h + n_g, n),
        "model_error_rate (M only)": _pct(n_m, n),
    }

    # ---- difficulty and per database
    level = {i: gold.difficulty(i) for i in ids}
    out["difficulty_title"] = gold.difficulty_title
    out["by_difficulty"] = {}
    for lv in gold.difficulty_levels:
        group = [i for i in ids if level[i] == lv]
        cats = Counter(labels[i]["category"] for i in group if i in labels)
        out["by_difficulty"][lv] = {
            "n": len(group), "ex_pct": _pct(sum(ex[i] for i in group), len(group)),
            "single_pass_ex_pct": _pct(sum(latest[i]["scoring"]["first_ex"] for i in group), len(group)),
            "H": cats["H"], "G": cats["G"], "M": cats["M"],
        }

    # ---- retrieval: Recall@K of what the gold query needs
    unit_index: Dict[str, Dict[str, dict]] = {}
    for db, entry in units.items():
        unit_index[db] = {"column": {}, "table": {}, "n": len(entry["units"])}
        for u in entry["units"]:
            if u["kind"] == "column":
                unit_index[db]["column"][(u["table"].lower(), u["column"].lower())] = u["id"]
            elif u["kind"] == "table":
                unit_index[db]["table"][u["table"].lower()] = u["id"]
    retrieval: Dict[int, dict] = {}
    role_total: Counter = Counter()
    role_hit: Counter = Counter()
    cols_total = {c: 0 for c in ks}
    cols_hit = {c: 0 for c in ks}
    tab_total = tab_hit = 0
    prompt_cols_total = prompt_cols_hit = 0
    prompt_units: List[int] = []
    unmapped = 0
    star_golds = 0
    for i in ids:
        record = latest[i]
        index = unit_index[record["db_id"]]
        gold_cols, gold_tabs, star = gold.references(i, record["db_id"])
        star_golds += star
        rank = {uid: r for r, uid in enumerate(record["retrieved"], 1)}
        wanted: List[Tuple[int, str]] = []
        for key, col_roles in gold_cols.items():
            uid = index["column"].get(key)
            if uid is None:
                unmapped += 1
                continue
            wanted.append((rank.get(uid, 10**6), key[0]))
            for role in col_roles:
                role_total[role] += 1
                role_hit[role] += uid in rank
        tabs = gold_tabs | {t for _, t in wanted}
        covered = 0
        for t in tabs:
            tid = index["table"].get(t)
            in_prompt = tid in rank or any(
                tt == t and uid in rank for (tt, _), uid in index["column"].items())
            covered += in_prompt
        tab_total += len(tabs)
        tab_hit += covered
        for c in ks:
            cols_total[c] += len(wanted)
            cols_hit[c] += sum(1 for r, _ in wanted if r <= c)
        prompt_cols_total += len(wanted)
        prompt_cols_hit += sum(1 for r, _ in wanted if r < 10**6)
        prompt_units.append(len(record["retrieved"]))
        retrieval[i] = {
            "all_columns": {c: all(r <= c for r, _ in wanted) for c in ks},
            # in the prompt, at any rank: a hybrid run keeps more than K units (pool, completion)
            "complete": all(r < 10**6 for r, _ in wanted) and covered == len(tabs),
            "n_units": index["n"],
            "n_gold_columns": len(wanted),
        }
    complete = [i for i in ids if retrieval[i]["complete"]]
    incomplete = [i for i in ids if not retrieval[i]["complete"]]

    def ex_rate(group):
        return _pct(sum(ex[i] for i in group), len(group))

    def m_rate(group):
        return _pct(sum(1 for i in group if labels.get(i, {}).get("category") == "M"), len(group))

    out["retrieval"] = {
        "k": k,
        "column_recall_pct": {str(c): _pct(cols_hit[c], cols_total[c]) for c in ks},
        # every unit that reached the prompt (K to 1.5 K from the hybrid pool, plus completion)
        "column_recall_in_prompt_pct": _pct(prompt_cols_hit, prompt_cols_total),
        "avg_units_in_prompt": round(statistics.mean(prompt_units), 1),
        "samples_with_all_gold_columns_pct": {
            str(c): _pct(sum(retrieval[i]["all_columns"][c] for i in ids), n) for c in ks},
        "table_coverage_pct": _pct(tab_hit, tab_total),
        "column_recall_by_role_pct": {r: _pct(role_hit[r], role_total[r]) for r in sorted(role_total)},
        "gold_with_star_projection": star_golds,
        "complete_samples": len(complete), "incomplete_samples": len(incomplete),
        "ex_pct_when_complete": ex_rate(complete), "ex_pct_when_incomplete": ex_rate(incomplete),
        "model_error_pct_when_complete": m_rate(complete),
        "model_error_pct_when_incomplete": m_rate(incomplete),
        "m_errors_with_incomplete_retrieval": sum(
            1 for i in incomplete if labels.get(i, {}).get("category") == "M"),
        "m_errors_with_complete_retrieval": sum(
            1 for i in complete if labels.get(i, {}).get("category") == "M"),
        "avg_units_per_database": round(statistics.mean(r["n_units"] for r in retrieval.values()), 1),
        "samples_where_k_covers_whole_schema": sum(1 for r in retrieval.values() if r["n_units"] <= k),
        "gold_columns_not_in_units": unmapped,
        "m_subtype_with_incomplete_retrieval": {
            s: [sum(1 for i in v if not retrieval[i]["complete"]), len(v)]
            for (c, s), v in sorted(by_sub.items()) if c == "M"},
    }

    # ---- per database
    out["by_database"] = {}
    for db in sorted({latest[i]["db_id"] for i in ids}):
        group = [i for i in ids if latest[i]["db_id"] == db]
        cats = Counter(labels[i]["category"] for i in group if i in labels)
        out["by_database"][db] = {
            "n": len(group), "ex_pct": ex_rate(group),
            "single_pass_ex_pct": _pct(sum(latest[i]["scoring"]["first_ex"] for i in group), len(group)),
            "H": cats["H"], "G": cats["G"], "M": cats["M"],
            "complete_retrieval_pct": _pct(sum(retrieval[i]["complete"] for i in group), len(group)),
            "units": unit_index[db]["n"],
        }

    # ---- how the failing results differ from gold (re-executed)
    if relations is not None:
        by_relation: Dict[str, dict] = {}
        for i, entry in sorted(relations.items()):
            slot = by_relation.setdefault(entry["rel"], {"count": 0, "H": 0, "G": 0, "M": 0})
            slot["count"] += 1
            if i in labels:
                slot[labels[i]["category"]] += 1
        for rel, slot in by_relation.items():
            slot["description"] = RELATIONS.get(rel, rel)
        out["result_relations"] = dict(sorted(by_relation.items(), key=lambda kv: -kv[1]["count"]))

    # ---- result-based signals: how precise are they as 'retry' triggers
    def final_result(i):
        return latest[i]["results"]["final"]

    empty = [i for i in ids if final_result(i).get("ok") and final_result(i)["n_rows"] == 0]
    empty_fail = [i for i in empty if not ex[i]]
    degenerate_pattern = re.compile(r"(WHERE\s+1\s*=\s*0|LIMIT\s+0\b|WHERE\s+FALSE)", re.I)
    degenerate = [i for i in ids if degenerate_pattern.search(latest[i]["final_sql"])]
    placeholder = [i for i in ids if re.search(r"\bNULL\s+AS\b", latest[i]["final_sql"], re.I)]
    out["signals"] = {
        "empty_result": {
            "samples": len(empty), "wrong": len(empty_fail),
            "precision_pct": _pct(len(empty_fail), len(empty)),
            "m_errors_caught": sum(1 for i in empty_fail if labels[i]["category"] == "M"),
            "gold_also_empty_and_correct": len(empty) - len(empty_fail),
        },
        "degenerate_sql (WHERE 1 = 0 / LIMIT 0)": {
            "samples": len(degenerate), "wrong": sum(1 for i in degenerate if not ex[i]), "ids": degenerate},
        "NULL AS placeholder column": {
            "samples": len(placeholder), "wrong": sum(1 for i in placeholder if not ex[i]), "ids": placeholder},
    }

    # ---- cost
    tokens: Counter = Counter()
    latencies: List[float] = []
    for i in ids:
        for a in latest[i]["attempts"]:
            for key, value in (a["tokens"] or {}).items():
                tokens[key] += value
            latencies.append(a["ms"])
    out["cost"] = {
        "tokens": dict(tokens),
        "tokens_per_sample": {k: round(v / n) for k, v in tokens.items()},
        "reasoning_share_of_completion_pct": _pct(tokens["reasoning"], tokens["completion"]),
        "mean_call_latency_ms": round(statistics.mean(latencies)),
        "p95_call_latency_ms": round(sorted(latencies)[int(0.95 * len(latencies))]),
    }
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def format_report(a: dict) -> str:
    lines: List[str] = []
    w = lines.append
    o = a["overview"]
    w(f"run {a['run']}   {a['n_samples']} samples")
    w(f"EX {o['ex_pct']}%  (single pass {o['single_pass_ex_pct']}%)   failing {o['failing']}")
    if a["label_problems"]:
        w("\nLABEL PROBLEMS:")
        lines.extend("  - " + p for p in a["label_problems"])
    lp = a["loop"]
    w(f"\nFeedback loop: {lp['llm_calls']} calls, {lp['samples_retried']} samples retried, "
      f"{lp['recovered']} recovered; attempts {lp['attempts_distribution']}")
    w(f"  single pass wrong -> final right: {lp['single_pass_wrong_final_right']}, "
      f"right -> wrong: {lp['single_pass_right_final_wrong']}; failing samples whose SQL ran: "
      f"{lp['failing_samples_whose_sql_ran']}/{o['failing']}")
    for kind, v in lp["first_attempt_rejection_kinds"].items():
        w(f"  first attempt rejected: {v['samples']:4d}  final EX {v['final_ex']:3d}  {kind}")
    t = a["taxonomy"]
    w("\nCategories:")
    for c, v in t["categories"].items():
        w(f"  {c}: {v['count']:4d}  {v['pct_of_all']:5.2f}% of all   (arguable {v['arguable']})")
    w("\nSubtypes:")
    for key, v in t["subtypes"].items():
        w(f"  {key:28s} {v['count']:4d}  arguable {v['arguable']:3d}  {v['pct_of_all']:5.2f}%")
    w(f"\nH/column_order verification: {t['column_order_verification']}")
    w("\nAdjusted EX / model error:")
    for k, v in a["adjusted_ex"].items():
        w(f"  {k:48s} {v}%")
    w(f"\nBy {a['difficulty_title']}:")
    for lv, v in a["by_difficulty"].items():
        w(f"  {lv:11s} n={v['n']:4d}  EX {v['ex_pct']:5.1f}  single {v['single_pass_ex_pct']:5.1f}  H {v['H']:3d} G {v['G']:3d} M {v['M']:3d}")
    r = a["retrieval"]
    w(f"\nRetrieval (K={r['k']}): column recall by cut-off = {r['column_recall_pct']}, "
      f"all gold columns present = {r['samples_with_all_gold_columns_pct']}, tables {r['table_coverage_pct']}%")
    w(f"  in the prompt (all {r['avg_units_in_prompt']} units on average): "
      f"column recall {r['column_recall_in_prompt_pct']}%")
    if r["column_recall_by_role_pct"]:
        w(f"  by role: {r['column_recall_by_role_pct']}")
    if r["gold_with_star_projection"]:
        w(f"  gold queries with a * projection (columns not counted, tables are): {r['gold_with_star_projection']}")
    w(f"  EX when complete {r['ex_pct_when_complete']}% ({r['complete_samples']}), "
      f"incomplete {r['ex_pct_when_incomplete']}% ({r['incomplete_samples']})")
    w(f"  model-error rate when complete {r['model_error_pct_when_complete']}%, "
      f"incomplete {r['model_error_pct_when_incomplete']}%; "
      f"M errors with incomplete retrieval {r['m_errors_with_incomplete_retrieval']}, complete "
      f"{r['m_errors_with_complete_retrieval']}")
    w("\nBy database:")
    for db, v in a["by_database"].items():
        w(f"  {db:30s} n={v['n']:4d} EX {v['ex_pct']:5.1f} single {v['single_pass_ex_pct']:5.1f} "
          f"H {v['H']:3d} G {v['G']:3d} M {v['M']:3d}  complete retrieval {v['complete_retrieval_pct']:5.1f}%")
    if "result_relations" in a:
        w("\nHow the failing results differ from gold (re-executed):")
        for rel, v in a["result_relations"].items():
            w(f"  {rel:30s} {v['count']:4d}  H {v['H']:3d} G {v['G']:3d} M {v['M']:3d}  {v['description']}")
    w("\nSignals:")
    for k, v in a["signals"].items():
        w(f"  {k}: " + ", ".join(f"{kk}={vv}" for kk, vv in v.items() if kk != "ids"))
    c = a["cost"]
    w(f"\nCost: {c['tokens']}  per sample {c['tokens_per_sample']}  "
      f"latency mean {c['mean_call_latency_ms']} ms, p95 {c['p95_call_latency_ms']} ms")
    return "\n".join(lines)


def _run_dataset(run_dir: str) -> str:
    """The dataset a run was made on (logs written before BIRD have no name: Spider)."""
    return (_manifest(run_dir).get("dataset") or {}).get("name", "spider")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Error analysis of a Spider or BIRD run log")
    parser.add_argument("run_dir")
    parser.add_argument(
        "--data_path", "--spider_path", dest="data_path",
        help="dataset folder of the run (default: ./Spider or ./BIRD; not needed with --check-only)",
    )
    parser.add_argument("--labels", help="error_labels.tsv (default: next to the log)")
    parser.add_argument("--check-only", action="store_true", help="only validate the labels (against the stored results)")
    parser.add_argument("--no-reexecute", action="store_true",
                        help="do not run the gold and final SQL again on the databases")
    parser.add_argument("--refresh", action="store_true", help="ignore result_relations.json and execute again")
    parser.add_argument("--no-write", action="store_true",
                        help="do not write error_analysis.json or result_relations.json")
    args = parser.parse_args(argv)

    dataset = _run_dataset(args.run_dir)
    if args.check_only:
        problems = check_labels(args.run_dir, args.labels)
        for p in problems:
            print("PROBLEM:", p)
        print("labels OK" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    data_path = args.data_path or default_data_path(dataset)
    if not os.path.isdir(data_path):
        parser.error(f"the {dataset} data path {data_path!r} is not a directory; pass --data_path")
    result = analyse(args.run_dir, data_path, args.labels, reexecute=not args.no_reexecute,
                     refresh=args.refresh, write_cache=not args.no_write)
    print(format_report(result))
    if not args.no_write:
        path = os.path.join(args.run_dir, "error_analysis.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(f"\nwrote {path}")
    return 1 if result["label_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
