"""
SQLite Schema Extractor

Inspects a SQLite database and produces a schema JSON dict in the same
format consumed by SchemaManager, ensuring full compatibility with the
existing NL2SQL pipeline without any modifications to that pipeline.

Output format:
{
    "database_name": str,
    "description": str,
    "tables": [
        {"name": str, "description": str, "key_columns": [str]}
    ],
    "columns": [
        {
            "table_name": str,
            "column_name": str,
            "meaning": str,
            "data_type": str
        }
    ],
    "relations": [
        {
            "source_table": str,
            "source_column": str,
            "target_table": str,
            "target_column": str,
            "relationship_type": str,
            "join_purpose": str
        }
    ]
}
"""

import sqlite3
import os
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: Dict[str, str] = {
    "integer": "integer",
    "int": "integer",
    "tinyint": "integer",
    "smallint": "integer",
    "mediumint": "integer",
    "bigint": "integer",
    "unsigned big int": "integer",
    "int2": "integer",
    "int8": "integer",
    "real": "decimal",
    "double": "decimal",
    "double precision": "decimal",
    "float": "decimal",
    "numeric": "decimal",
    "decimal": "decimal",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
    "text": "varchar",
    "character": "varchar",
    "varchar": "varchar",
    "varying character": "varchar",
    "nchar": "varchar",
    "native character": "varchar",
    "nvarchar": "varchar",
    "clob": "varchar",
    "blob": "blob",
}


def _map_type(sqlite_type: Optional[str]) -> str:
    if not sqlite_type:
        return "varchar"
    cleaned = sqlite_type.lower().strip()
    # Check exact match first
    if cleaned in _TYPE_MAP:
        return _TYPE_MAP[cleaned]
    # Check prefix match (e.g. "varchar(255)" -> "varchar")
    for key, mapped in _TYPE_MAP.items():
        if cleaned.startswith(key):
            return mapped
    return cleaned


# ---------------------------------------------------------------------------
# SQLiteSchemaExtractor
# ---------------------------------------------------------------------------

class SQLiteSchemaExtractor:
    """
    Inspects a SQLite database and extracts schema information compatible
    with the SchemaManager JSON format.
    """

    def __init__(self, sqlite_path: str):
        """
        Args:
            sqlite_path: Full filesystem path to the .sqlite file.

        Raises:
            FileNotFoundError: If the database file does not exist.
        """
        if not os.path.exists(sqlite_path):
            raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
        self.sqlite_path = sqlite_path
        self._db_name = os.path.splitext(os.path.basename(sqlite_path))[0]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_table_names(self, conn: sqlite3.Connection) -> List[str]:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        return [row["name"] for row in cursor.fetchall()]

    def _get_columns(
        self, conn: sqlite3.Connection, table_name: str
    ) -> List[Dict[str, Any]]:
        """
        Returns list of column dicts with keys:
            cid, name, type, notnull, dflt_value, pk
        """
        cursor = conn.execute(f"PRAGMA table_info({_quote(table_name)});")
        return [dict(row) for row in cursor.fetchall()]

    def _get_foreign_keys(
        self, conn: sqlite3.Connection, table_name: str
    ) -> List[Dict[str, Any]]:
        """
        Returns list of FK dicts from PRAGMA foreign_key_list.
        Keys: id, seq, table, from, to, on_update, on_delete, match
        """
        cursor = conn.execute(f"PRAGMA foreign_key_list({_quote(table_name)});")
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> Dict[str, Any]:
        """
        Inspect the database and return the schema dict.

        Returns:
            Schema dict compatible with SchemaManager.load_schema_from_json().
        """
        schema: Dict[str, Any] = {
            "database_name": self._db_name,
            "description": f"SQLite database schema for {self._db_name}",
            "tables": [],
            "columns": [],
            "relations": [],
        }

        with self._connect() as conn:
            table_names = self._get_table_names(conn)

            for table_name in table_names:
                raw_cols = self._get_columns(conn, table_name)

                # Determine primary key columns
                pk_columns = [
                    col["name"] for col in raw_cols if col["pk"] > 0
                ]
                # Fall back to first three columns if no PK defined
                key_columns = pk_columns if pk_columns else [
                    col["name"] for col in raw_cols[:3]
                ]

                schema["tables"].append(
                    {
                        "name": table_name,
                        "description": f"Table {table_name}",
                        "key_columns": key_columns,
                    }
                )

                for col in raw_cols:
                    schema["columns"].append(
                        {
                            "table_name": table_name,
                            "column_name": col["name"],
                            "meaning": f"Column {col['name']} of table {table_name}",
                            "data_type": _map_type(col["type"]),
                        }
                    )

                # Foreign keys
                for fk in self._get_foreign_keys(conn, table_name):
                    schema["relations"].append(
                        {
                            "source_table": table_name,
                            "source_column": fk["from"],
                            "target_table": fk["table"],
                            "target_column": fk["to"],
                            "relationship_type": "many-to-one",
                            "join_purpose": (
                                f"connecting {table_name} to {fk['table']}"
                            ),
                        }
                    )

        return schema


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _quote(identifier: str) -> str:
    """Wrap an identifier in double-quotes to handle reserved words/spaces."""
    return f'"{identifier}"'
