"""
Spider 1 Dataset Loader

Loads Spider dev.json and tables.json, providing structured access
to benchmark samples for evaluation.
"""

import json
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SpiderSample:
    """A single Spider benchmark sample."""
    question: str
    gold_sql: str
    db_id: str


def load_spider_dev(path: str) -> List[SpiderSample]:
    """
    Load Spider dev set samples from the dataset directory.

    Args:
        path: Root path to the Spider dataset directory.
              Expected layout:
                <path>/dev.json
                <path>/tables.json
                <path>/database/<db_id>/<db_id>.sqlite

    Returns:
        List of SpiderSample objects ready for evaluation.

    Raises:
        FileNotFoundError: If dev.json is missing.
        ValueError: If required fields are absent in any entry.
    """
    dev_json_path = os.path.join(path, "dev.json")
    if not os.path.exists(dev_json_path):
        raise FileNotFoundError(f"dev.json not found at: {dev_json_path}")

    with open(dev_json_path, "r", encoding="utf-8") as f:
        raw_entries = json.load(f)

    samples: List[SpiderSample] = []
    for idx, entry in enumerate(raw_entries):
        question = entry.get("question")
        gold_sql = entry.get("query")
        db_id = entry.get("db_id")

        if not question or not gold_sql or not db_id:
            raise ValueError(
                f"Entry {idx} is missing one of: question, query, db_id. "
                f"Got: {entry}"
            )

        samples.append(
            SpiderSample(
                question=question.strip(),
                gold_sql=gold_sql.strip(),
                db_id=db_id.strip(),
            )
        )

    return samples


def load_spider_tables(path: str) -> dict:
    """
    Load Spider tables.json and index it by db_id.

    Args:
        path: Root path to the Spider dataset directory.

    Returns:
        Dict mapping db_id -> table entry dict from tables.json.
    """
    tables_json_path = os.path.join(path, "tables.json")
    if not os.path.exists(tables_json_path):
        raise FileNotFoundError(f"tables.json not found at: {tables_json_path}")

    with open(tables_json_path, "r", encoding="utf-8") as f:
        raw_tables = json.load(f)

    return {entry["db_id"]: entry for entry in raw_tables}


def get_sqlite_path(spider_path: str, db_id: str) -> str:
    """
    Return the path to the SQLite database file for a given db_id.

    Args:
        spider_path: Root path to the Spider dataset directory.
        db_id: Database identifier.

    Returns:
        Absolute path to the .sqlite file.
    """
    return os.path.join(spider_path, "database", db_id, f"{db_id}.sqlite")
