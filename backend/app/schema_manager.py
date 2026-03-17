"""
Schema Manager Module for NL2SQL RAG System

This module handles database schema transformation into embedding-ready textual units.
Each schema element (table, column, relation) becomes a retrieval unit for RAG.
"""

import json
from typing import List, Dict, Tuple
from dataclasses import dataclass


@dataclass
class Table:
    """Represents a database table with semantic information"""
    name: str
    description: str
    key_columns: List[str]
    business_role: str
    
    def to_embedding_text(self) -> str:
        """
        Convert table to embedding text format:
        <TableName> Table: <semantic description>. شامل ستون های <key columns>. استفاده برای <business role>.
        """
        key_cols = ", ".join(self.key_columns)
        return (
            f"{self.name} Table: {self.description}. "
            f"شامل ستون های {key_cols}. "
            f"استفاده برای {self.business_role}."
        )


@dataclass
class Column:
    """Represents a database column with semantic information"""
    table_name: str
    column_name: str
    meaning: str
    data_type: str
    operations: str
    
    def to_embedding_text(self) -> str:
        """
        Convert column to embedding text format:
        <TableName>.<ColumnName> Column: <meaning>, نوع داده {self.data_type}, استفاده برای {self.operations}.
        """
        return (
            f"{self.table_name}.{self.column_name} Column: {self.meaning}, "
            f"نوع داده {self.data_type}, استفاده برای {self.operations}."
        )


@dataclass
class Relation:
    """Represents a foreign key relationship between tables"""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: str
    join_purpose: str
    
    def to_embedding_text(self) -> str:
        """
        Convert relation to embedding text format:
        Relation: <TableA>.<Column> ↔ <TableB>.<Column>. Relationship type {self.relationship_type}. استفاده برای {self.join_purpose}.
        """
        return (
            f"Relation: {self.source_table}.{self.source_column} ↔ "
            f"{self.target_table}.{self.target_column}. "
            f"نوع رابطه {self.relationship_type}. "
            f"استفاده برای {self.join_purpose}."
        )


class SchemaManager:
    """Manages database schema elements and converts them to embedding-ready text"""
    
    def __init__(self):
        self.tables: List[Table] = []
        self.columns: List[Column] = []
        self.relations: List[Relation] = []
    
    def load_schema_from_json(self, schema_file_path: str) -> None:
        """
        Load database schema from JSON file.
        
        Expected JSON structure:
        {
            "tables": [
                {
                    "name": "Customers",
                    "description": "اطلاعات مشتریان",
                    "key_columns": ["CustomerID", "Name", "JoinDate"],
                    "business_role": "نگهداری مشخصات اشخاصی که خرید انجام داده‌اند"
                }
            ],
            "columns": [
                {
                    "table_name": "Customers",
                    "column_name": "CustomerID",
                    "meaning": "شناسه یکتای مشتری",
                    "data_type": "integer",
                    "operations": "شناسایی و ارتباط با جداول دیگر"
                }
            ],
            "relations": [
                {
                    "source_table": "Purchases",
                    "source_column": "CustomerID",
                    "target_table": "Customers",
                    "target_column": "CustomerID",
                    "relationship_type": "many-to-one",
                    "join_purpose": "connecting each purchase to its customer"
                }
            ]
        }
        """
        with open(schema_file_path, "r", encoding="utf-8") as f:
            schema_data = json.load(f)
        
        # Load tables
        for table_data in schema_data.get("tables", []):
            table = Table(
                name=table_data["name"],
                description=table_data["description"],
                key_columns=table_data["key_columns"],
                business_role=table_data["business_role"]
            )
            self.tables.append(table)
        
        # Load columns
        for column_data in schema_data.get("columns", []):
            column = Column(
                table_name=column_data["table_name"],
                column_name=column_data["column_name"],
                meaning=column_data["meaning"],
                data_type=column_data["data_type"],
                operations=column_data["operations"]
            )
            self.columns.append(column)
        
        # Load relations
        for relation_data in schema_data.get("relations", []):
            relation = Relation(
                source_table=relation_data["source_table"],
                source_column=relation_data["source_column"],
                target_table=relation_data["target_table"],
                target_column=relation_data["target_column"],
                relationship_type=relation_data["relationship_type"],
                join_purpose=relation_data["join_purpose"]
            )
            self.relations.append(relation)
    
    def get_all_embedding_texts(self) -> Tuple[List[str], List[str]]:
        """
        Generate all embedding texts and corresponding IDs.
        
        Returns:
            Tuple of (ids, documents) ready for vector store ingestion
        """
        ids: List[str] = []
        documents: List[str] = []
        
        # Add tables
        for idx, table in enumerate(self.tables):
            ids.append(f"table_{idx}")
            documents.append(table.to_embedding_text())
        
        # Add columns
        for idx, column in enumerate(self.columns):
            ids.append(f"column_{idx}")
            documents.append(column.to_embedding_text())
        
        # Add relations
        for idx, relation in enumerate(self.relations):
            ids.append(f"relation_{idx}")
            documents.append(relation.to_embedding_text())
        
        return ids, documents
    
    def generate_schema_text_file(self, output_path: str) -> None:
        """
        Generate a pipe-separated text file for vector store ingestion.
        Compatible with existing create_vector_store function.
        """
        ids, documents = self.get_all_embedding_texts()
        
        # Join documents with pipe separator
        text_content = "\n | \n".join(documents)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text_content)
    
    def get_schema_summary(self) -> Dict[str, int]:
        """Get summary statistics of loaded schema"""
        return {
            "tables": len(self.tables),
            "columns": len(self.columns),
            "relations": len(self.relations),
            "total_units": len(self.tables) + len(self.columns) + len(self.relations)
        }
