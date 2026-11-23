"""
Error analysis of a Spider evaluation run.

Everything here is computed from the run log (``samples.jsonl``,
``schema_units.json``), Spider's ``dev.json`` / ``tables.json`` and the
hand-written labels in ``error_labels.tsv`` next to the log. Nothing is
re-executed, so it needs no database and no LLM.

Two kinds of numbers come out, and they must not be confused:

* **Mechanical** (no judgement): retry and dialect statistics, Recall@K of the
  retrieval, hardness, per-database results, the precision of result-based
  signals, tokens. They are a pure function of the log and the gold data.
* **Judged**: the H / G / M category of each failing sample (``error_labels.tsv``).
  H is partly verified against the stored results (column order); G and M rest
  on reading the gold and predicted SQL, and the ``arguable`` flag marks the
  G labels where another reader could reasonably say the model was wrong.

Categories (see ``TAXONOMY``):

* **H** - the scorer, not the model: the prediction is right but the user's
  comparison rejects it (column order) or the gold query cannot be run.
* **G** - the gold query or the question: the prediction is semantically
  equivalent or a defensible reading (ties, zero-count groups, an ambiguous
  question) or the gold query itself is wrong.
* **M** - the model.

Usage::

    python -m app.spider_eval.error_analysis runs/<run_dir> --spider_path ./spider
    python -m app.spider_eval.error_analysis runs/<run_dir> --check-only
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple

from app.spider_eval.run_log import latest_by_index, read_records
from app.spider_eval.spider_sqlite_executor import results_match

# category -> subtype -> what it means
TAXONOMY: Dict[str, Dict[str, str]] = {
    "H": {
        "column_order": "same rows, columns in another order (rejected by the scorer used before results_match ignored column order)",
        "gold_unreadable": "the gold query cannot be run by the harness (invalid UTF-8 in the database)",
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
        "other": "none of the above",
    },
}

DIFFICULTIES = ("easy", "medium", "hard", "extra")
RETRIEVAL_KS = (5, 10, 15)

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
    Would a column-order-tolerant comparison (the scorer's ``results_match``)
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
    match, permuted = results_match(
        [tuple(r) for r in pred["rows"]], [tuple(r) for r in gold["rows"]]
    )
    if match and permuted:
        return "partial" if truncated else "full"
    return "undetermined" if truncated else "no_match"


def validate_labels(latest: Dict[int, dict], labels: Dict[int, dict]) -> List[str]:
    """Everything that must hold for the labels to be usable; empty list = fine."""
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
            mechanical = column_order_check(record)
            label = labels[i]
            if mechanical == "full" and (label["category"], label["subtype"]) != ("H", "column_order"):
                problems.append(f"sample {i}: result is a column permutation of gold but labelled "
                                f"{label['category']}/{label['subtype']}")
            if (label["category"], label["subtype"]) == ("H", "column_order") and mechanical == "no_match":
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
    """Validate ``error_labels.tsv`` against the run log (needs no Spider files)."""
    records, _ = read_records(os.path.join(run_dir, "samples.jsonl"))
    latest = latest_by_index(records)
    labels = load_labels(labels_path or os.path.join(run_dir, "error_labels.tsv"))
    return validate_labels(latest, labels)


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def analyse(run_dir: str, spider_path: str, labels_path: Optional[str] = None) -> dict:
    records, _ = read_records(os.path.join(run_dir, "samples.jsonl"))
    latest = latest_by_index(records)
    n = len(latest)
    labels = load_labels(labels_path or os.path.join(run_dir, "error_labels.tsv"))
    problems = validate_labels(latest, labels)

    with open(os.path.join(spider_path, "dev.json"), encoding="utf-8") as f:
        dev = json.load(f)
    with open(os.path.join(spider_path, "tables.json"), encoding="utf-8") as f:
        tables = {t["db_id"]: t for t in json.load(f)}
    with open(os.path.join(run_dir, "schema_units.json"), encoding="utf-8") as f:
        units = json.load(f)
    for i, record in latest.items():
        if dev[i]["question"] != record["question"] or dev[i]["db_id"] != record["db_id"]:
            problems.append(f"sample {i}: dev.json row differs from the log (wrong dev.json?)")

    out: dict = {"run": os.path.basename(os.path.normpath(run_dir)), "n_samples": n, "label_problems": problems}
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
        "column_order_verification": dict(Counter(
            column_order_check(latest[i]) for i in by_sub[("H", "column_order")])),
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

    # ---- hardness and per database
    level = {i: hardness(dev[i]["sql"]) for i in ids}
    out["by_hardness"] = {}
    for lv in DIFFICULTIES:
        group = [i for i in ids if level[i] == lv]
        cats = Counter(labels[i]["category"] for i in group if i in labels)
        out["by_hardness"][lv] = {
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
    cols_total = {k: 0 for k in RETRIEVAL_KS}
    cols_hit = {k: 0 for k in RETRIEVAL_KS}
    tab_total = tab_hit = 0
    unmapped = 0
    for i in ids:
        record = latest[i]
        schema = tables[record["db_id"]]
        index = unit_index[record["db_id"]]
        names, table_names = schema["column_names_original"], schema["table_names_original"]
        roles = gold_columns(dev[i]["sql"])
        rank = {uid: r for r, uid in enumerate(record["retrieved"], 1)}
        wanted: List[Tuple[int, str]] = []
        for col, col_roles in roles.items():
            key = (table_names[names[col][0]].lower(), names[col][1].lower())
            uid = index["column"].get(key)
            if uid is None:
                unmapped += 1
                continue
            wanted.append((rank.get(uid, 10**6), key[0]))
            for role in col_roles:
                role_total[role] += 1
                role_hit[role] += uid in rank
        tabs = {table_names[t].lower() for t in gold_tables(dev[i]["sql"])} | {t for _, t in wanted}
        covered = 0
        for t in tabs:
            tid = index["table"].get(t)
            in_prompt = tid in rank or any(
                tt == t and uid in rank for (tt, _), uid in index["column"].items())
            covered += in_prompt
        tab_total += len(tabs)
        tab_hit += covered
        for k in RETRIEVAL_KS:
            cols_total[k] += len(wanted)
            cols_hit[k] += sum(1 for r, _ in wanted if r <= k)
        retrieval[i] = {
            "all_columns": {k: all(r <= k for r, _ in wanted) for k in RETRIEVAL_KS},
            "complete": all(r <= 15 for r, _ in wanted) and covered == len(tabs),
            "n_units": index["n"],
        }
    complete = [i for i in ids if retrieval[i]["complete"]]
    incomplete = [i for i in ids if not retrieval[i]["complete"]]

    def ex_rate(group):
        return _pct(sum(ex[i] for i in group), len(group))

    def m_rate(group):
        return _pct(sum(1 for i in group if labels.get(i, {}).get("category") == "M"), len(group))

    out["retrieval"] = {
        "k": max(RETRIEVAL_KS),
        "column_recall_pct": {str(k): _pct(cols_hit[k], cols_total[k]) for k in RETRIEVAL_KS},
        "samples_with_all_gold_columns_pct": {
            str(k): _pct(sum(retrieval[i]["all_columns"][k] for i in ids), n) for k in RETRIEVAL_KS},
        "table_coverage_pct": _pct(tab_hit, tab_total),
        "column_recall_by_role_at_15_pct": {r: _pct(role_hit[r], role_total[r]) for r in sorted(role_total)},
        "complete_samples": len(complete), "incomplete_samples": len(incomplete),
        "ex_pct_when_complete": ex_rate(complete), "ex_pct_when_incomplete": ex_rate(incomplete),
        "model_error_pct_when_complete": m_rate(complete),
        "model_error_pct_when_incomplete": m_rate(incomplete),
        "m_errors_with_incomplete_retrieval": sum(
            1 for i in incomplete if labels.get(i, {}).get("category") == "M"),
        "m_errors_with_complete_retrieval": sum(
            1 for i in complete if labels.get(i, {}).get("category") == "M"),
        "avg_units_per_database": round(statistics.mean(r["n_units"] for r in retrieval.values()), 1),
        "samples_where_k_covers_whole_schema": sum(1 for r in retrieval.values() if r["n_units"] <= 15),
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
    w("\nBy hardness:")
    for lv, v in a["by_hardness"].items():
        w(f"  {lv:7s} n={v['n']:4d}  EX {v['ex_pct']:5.1f}  single {v['single_pass_ex_pct']:5.1f}  H {v['H']:3d} G {v['G']:3d} M {v['M']:3d}")
    r = a["retrieval"]
    w(f"\nRetrieval (K={r['k']}): column recall@5/10/15 = {r['column_recall_pct']}, "
      f"all gold columns present = {r['samples_with_all_gold_columns_pct']}, tables {r['table_coverage_pct']}%")
    w(f"  by role at 15: {r['column_recall_by_role_at_15_pct']}")
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
    w("\nSignals:")
    for k, v in a["signals"].items():
        w(f"  {k}: " + ", ".join(f"{kk}={vv}" for kk, vv in v.items() if kk != "ids"))
    c = a["cost"]
    w(f"\nCost: {c['tokens']}  per sample {c['tokens_per_sample']}  "
      f"latency mean {c['mean_call_latency_ms']} ms, p95 {c['p95_call_latency_ms']} ms")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Error analysis of a Spider run log")
    parser.add_argument("run_dir")
    parser.add_argument("--spider_path", help="folder with dev.json and tables.json (not needed with --check-only)")
    parser.add_argument("--labels", help="error_labels.tsv (default: next to the log)")
    parser.add_argument("--check-only", action="store_true", help="only validate the labels")
    parser.add_argument("--no-write", action="store_true", help="do not write error_analysis.json")
    args = parser.parse_args(argv)

    if args.check_only:
        problems = check_labels(args.run_dir, args.labels)
        for p in problems:
            print("PROBLEM:", p)
        print("labels OK" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if not args.spider_path:
        parser.error("--spider_path is required (except with --check-only)")
    result = analyse(args.run_dir, args.spider_path, args.labels)
    print(format_report(result))
    if not args.no_write:
        path = os.path.join(args.run_dir, "error_analysis.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(f"\nwrote {path}")
    return 1 if result["label_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
