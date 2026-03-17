"""
Schema Enricher
Enriches extracted schema JSON with rich Persian descriptions using a local Ollama LLM.
Enriches:
  - tables  → description, business_role
  - columns → meaning, operations
  - relations → join_purpose
"""

import json
import re
from typing import Any, Dict, List

from ollama import Client

OLLAMA_HOST: str = "http://127.0.0.1:11434"
OLLAMA_MODEL: str = "gemma3:4b"
OLLAMA_TEMPERATURE: float = 0.2


def _call_llm(client: Client, prompt: str) -> str:
    response = client.chat(
        messages=[{"role": "user", "content": prompt}],
        model=OLLAMA_MODEL,
        options={"temperature": OLLAMA_TEMPERATURE},
    )
    return response.message.content.strip()


# ---------------------------------------------------------------------------
# Table enrichment
# ---------------------------------------------------------------------------

def _build_table_prompt(
    table: Dict[str, Any],
    columns: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
) -> str:
    col_lines = "\n".join(
        f"  - {c['column_name']} ({c['data_type']})" for c in columns
    )
    rel_lines = "\n".join(
        f"  - {r['source_column']} → {r['target_table']}.{r['target_column']}"
        for r in relations
    ) or "  (no outgoing foreign keys)"

    return f"""You are a database documentation expert. Your task is to write a rich, informative description in **Persian (Farsi)** for a database table.

Table name: {table['name']}
Key columns: {', '.join(table.get('key_columns', []))}

Columns:
{col_lines}

Outgoing foreign-key relations:
{rel_lines}

Write two things, each on its own line with the exact labels shown:
DESCRIPTION: <a 1-3 sentence Persian description of what this table stores and its business purpose>
BUSINESS_ROLE: <one concise Persian sentence describing the business role of this table>

Rules:
- Write ONLY in Persian.
- Do not include any explanation or extra text outside the two labeled lines.
- Do not use markdown formatting inside the values.
"""


def enrich_table(
    client: Client,
    table: Dict[str, Any],
    columns: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
) -> None:
    prompt = _build_table_prompt(table, columns, relations)
    raw = _call_llm(client, prompt)

    description = _extract_label(raw, "DESCRIPTION")
    business_role = _extract_label(raw, "BUSINESS_ROLE")

    if description:
        table["description"] = description
    if business_role:
        table["business_role"] = business_role


# ---------------------------------------------------------------------------
# Column enrichment
# ---------------------------------------------------------------------------

def _build_column_prompt(
    column: Dict[str, Any],
    table: Dict[str, Any],
) -> str:
    return f"""You are a database documentation expert. Your task is to write rich Persian (Farsi) documentation for a single database column.

Table: {column['table_name']}
Table description: {table.get('description', '')}
Column: {column['column_name']}
Data type: {column['data_type']}
Is primary key: {'yes' if column['column_name'] in table.get('key_columns', []) else 'no'}

Write two things, each on its own line with the exact labels shown:
MEANING: <a clear Persian sentence explaining what this column stores and its semantic meaning>
OPERATIONS: <a Persian sentence describing typical query operations on this column, e.g. filtering, sorting, aggregation, joining>

Rules:
- Write ONLY in Persian.
- Do not include any explanation or extra text outside the two labeled lines.
- Do not use markdown formatting inside the values.
"""


def enrich_column(
    client: Client,
    column: Dict[str, Any],
    table: Dict[str, Any],
) -> None:
    prompt = _build_column_prompt(column, table)
    raw = _call_llm(client, prompt)

    meaning = _extract_label(raw, "MEANING")
    operations = _extract_label(raw, "OPERATIONS")

    if meaning:
        column["meaning"] = meaning
    if operations:
        column["operations"] = operations


# ---------------------------------------------------------------------------
# Relation enrichment
# ---------------------------------------------------------------------------

def _build_relation_prompt(relation: Dict[str, Any]) -> str:
    return f"""You are a database documentation expert. Your task is to write a rich Persian (Farsi) description explaining the purpose of a foreign-key relationship between two tables.

Source table: {relation['source_table']}
Source column: {relation['source_column']}
Target table: {relation['target_table']}
Target column: {relation['target_column']}
Relationship type: {relation['relationship_type']}

Write one thing on its own line with the exact label shown:
JOIN_PURPOSE: <a clear Persian sentence describing why this join exists and what business question it answers>

Rules:
- Write ONLY in Persian.
- Do not include any explanation or extra text outside the labeled line.
- Do not use markdown formatting inside the value.
"""


def enrich_relation(client: Client, relation: Dict[str, Any]) -> None:
    prompt = _build_relation_prompt(relation)
    raw = _call_llm(client, prompt)

    join_purpose = _extract_label(raw, "JOIN_PURPOSE")
    if join_purpose:
        relation["join_purpose"] = join_purpose


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_label(text: str, label: str) -> str:
    """Extract the value after 'LABEL:' on a line, stripping markdown bold markers."""
    pattern = re.compile(
        rf"^\s*\**{re.escape(label)}\**\s*:\s*(.+)$",
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return ""


def _build_table_index(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {t["name"]: t for t in schema["tables"]}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enriches a schema dict in-place with Persian LLM descriptions.
    Returns the same (mutated) dict for convenience.
    """
    client = Client(host=OLLAMA_HOST)
    table_index = _build_table_index(schema)

    total_tables = len(schema["tables"])
    total_columns = len(schema["columns"])
    total_relations = len(schema["relations"])

    # ── Enrich tables ────────────────────────────────────────────────────────
    print(f"\n🗂  Enriching {total_tables} tables...")
    for i, table in enumerate(schema["tables"], 1):
        name = table["name"]
        table_cols = [c for c in schema["columns"] if c["table_name"] == name]
        table_rels = [r for r in schema["relations"] if r["source_table"] == name]
        print(f"  [{i}/{total_tables}] {name} ...", end=" ", flush=True)
        enrich_table(client, table, table_cols, table_rels)
        print("✓")

    # ── Enrich columns ───────────────────────────────────────────────────────
    print(f"\n📋 Enriching {total_columns} columns...")
    for i, column in enumerate(schema["columns"], 1):
        tbl = table_index.get(column["table_name"], {})
        print(
            f"  [{i}/{total_columns}] {column['table_name']}.{column['column_name']} ...",
            end=" ",
            flush=True,
        )
        enrich_column(client, column, tbl)
        print("✓")

    # ── Enrich relations ─────────────────────────────────────────────────────
    print(f"\n🔗 Enriching {total_relations} relations...")
    for i, relation in enumerate(schema["relations"], 1):
        print(
            f"  [{i}/{total_relations}] {relation['source_table']}.{relation['source_column']}"
            f" → {relation['target_table']}.{relation['target_column']} ...",
            end=" ",
            flush=True,
        )
        enrich_relation(client, relation)
        print("✓")

    return schema


def enrich_schema_file(input_file: str, output_file: str | None = None) -> None:
    """Load a schema JSON file, enrich it, and save the result."""
    if output_file is None:
        output_file = input_file  # overwrite in-place

    with open(input_file, "r", encoding="utf-8") as f:
        schema = json.load(f)

    print(f"Loaded schema: {schema.get('database_name', input_file)}")
    enrich_schema(schema)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Enriched schema saved to: {output_file}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python enrich_schema.py <schema.json> [output.json]")
        print("like: python enrich_schema.py data_schema/concert_singer_schema.json")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    enrich_schema_file(input_path, output_path)
