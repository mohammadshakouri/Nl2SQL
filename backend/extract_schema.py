"""
Automatic Database Schema Extractor
Extracts schema information from SQL Server and generates JSON schema file
"""

import pyodbc
import app.dotenv as dotenv
import json
from typing import Dict, List, Any
from datetime import datetime
from enrich_schema import enrich_schema


class SchemaExtractor:
    def __init__(self, server: str, database: str, username: str, password: str):
        """Initialize connection to SQL Server database"""
        self.server = server
        self.database = database
        self.username = username
        self.password = password
        self.connection = None
        
    def connect(self):
        """Establish connection to SQL Server"""
        try:
            connection_string = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.server};"
                f"DATABASE={self.database};"
                f"UID={self.username};"
                f"PWD={self.password}"
            )
            self.connection = pyodbc.connect(connection_string)
            print(f"✓ Successfully connected to {self.database} on {self.server}")
            return True
        except pyodbc.Error as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    def get_tables(self) -> List[Dict[str, Any]]:
        """Extract all user tables from database"""
        cursor = self.connection.cursor()
        query = """
            SELECT 
                t.TABLE_NAME,
                ISNULL(ep.value, '') as TABLE_DESCRIPTION
            FROM INFORMATION_SCHEMA.TABLES t
            LEFT JOIN sys.tables st ON t.TABLE_NAME = st.name
            LEFT JOIN sys.extended_properties ep 
                ON st.object_id = ep.major_id 
                AND ep.minor_id = 0 
                AND ep.name = 'MS_Description'
            WHERE t.TABLE_TYPE = 'BASE TABLE'
            AND t.TABLE_SCHEMA = 'dbo'
            ORDER BY t.TABLE_NAME
        """
        cursor.execute(query)
        tables = []
        for row in cursor.fetchall():
            tables.append({
                'name': row.TABLE_NAME,
                'description': row.TABLE_DESCRIPTION or f"Table {row.TABLE_NAME}"
            })
        return tables
    
    def get_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """Extract columns for a specific table"""
        cursor = self.connection.cursor()
        query = """
            SELECT 
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.COLUMN_DEFAULT,
                ISNULL(ep.value, '') as COLUMN_DESCRIPTION,
                CASE 
                    WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 
                    ELSE 0 
                END as IS_PRIMARY_KEY
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.TABLE_NAME, ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                    ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ) pk ON c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
            LEFT JOIN sys.columns sc ON sc.name = c.COLUMN_NAME 
                AND sc.object_id = OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME)
            LEFT JOIN sys.extended_properties ep 
                ON sc.object_id = ep.major_id 
                AND sc.column_id = ep.minor_id 
                AND ep.name = 'MS_Description'
            WHERE c.TABLE_NAME = ?
            ORDER BY c.ORDINAL_POSITION
        """
        cursor.execute(query, table_name)
        columns = []
        for row in cursor.fetchall():
            columns.append({
                'column_name': row.COLUMN_NAME,
                'data_type': row.DATA_TYPE,
                'is_nullable': row.IS_NULLABLE == 'YES',
                'is_primary_key': row.IS_PRIMARY_KEY == 1,
                'description': row.COLUMN_DESCRIPTION or f"Column {row.COLUMN_NAME}"
            })
        return columns
    
    def get_foreign_keys(self) -> List[Dict[str, Any]]:
        """Extract foreign key relationships"""
        cursor = self.connection.cursor()
        query = """
            SELECT 
                fk.name as FK_NAME,
                tp.name as PARENT_TABLE,
                cp.name as PARENT_COLUMN,
                tr.name as REFERENCED_TABLE,
                cr.name as REFERENCED_COLUMN
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            INNER JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
            INNER JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
            INNER JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
            INNER JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
            ORDER BY tp.name, fk.name
        """
        cursor.execute(query)
        foreign_keys = []
        for row in cursor.fetchall():
            foreign_keys.append({
                'source_table': row.PARENT_TABLE,
                'source_column': row.PARENT_COLUMN,
                'target_table': row.REFERENCED_TABLE,
                'target_column': row.REFERENCED_COLUMN,
                'relationship_type': 'many-to-one',
                'join_purpose': f"connecting {row.PARENT_TABLE} to {row.REFERENCED_TABLE}"
            })
        return foreign_keys
    
    def map_sql_type_to_generic(self, sql_type: str) -> str:
        """Map SQL Server data types to generic types"""
        type_mapping = {
            'int': 'integer',
            'bigint': 'integer',
            'smallint': 'integer',
            'tinyint': 'integer',
            'decimal': 'decimal',
            'numeric': 'decimal',
            'float': 'decimal',
            'real': 'decimal',
            'money': 'decimal',
            'smallmoney': 'decimal',
            'varchar': 'varchar',
            'nvarchar': 'varchar',
            'char': 'varchar',
            'nchar': 'varchar',
            'text': 'varchar',
            'ntext': 'varchar',
            'date': 'date',
            'datetime': 'datetime',
            'datetime2': 'datetime',
            'smalldatetime': 'datetime',
            'time': 'time',
            'bit': 'boolean'
        }
        return type_mapping.get(sql_type.lower(), sql_type)
    
    def generate_schema_json(self) -> Dict[str, Any]:
        """Generate complete schema JSON"""
        schema = {
            'database_name': self.database,
            'description': f"Database schema for {self.database}",
            'tables': [],
            'columns': [],
            'relations': []
        }
        
        # Get all tables
        tables = self.get_tables()
        print(f"\n📊 Found {len(tables)} tables")
        
        for table in tables:
            table_name = table['name']
            print(f"  Processing: {table_name}")
            
            # Get columns for this table
            columns = self.get_columns(table_name)
            key_columns = [col['column_name'] for col in columns if col['is_primary_key']]
            
            # Add table info
            schema['tables'].append({
                'name': table_name,
                'description': table['description'],
                'key_columns': key_columns if key_columns else [col['column_name'] for col in columns[:3]]
            })
            
            # Add column info
            for col in columns:
                schema['columns'].append({
                    'table_name': table_name,
                    'column_name': col['column_name'],
                    'meaning': col['description'],
                    'data_type': self.map_sql_type_to_generic(col['data_type'])
                })
        
        # Get foreign key relationships
        foreign_keys = self.get_foreign_keys()
        print(f"\n🔗 Found {len(foreign_keys)} foreign key relationships")
        schema['relations'] = foreign_keys
        
        return schema
    
    def save_schema(self, output_file: str):
        """Extract and save schema to JSON file"""
        if not self.connect():
            return False
        
        try:
            print(f"\n🔍 Extracting schema from {self.database}...")
            schema = self.generate_schema_json()
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(schema, f, indent=2, ensure_ascii=False)
            
            print(f"\n✅ Schema successfully saved to: {output_file}")
            print(f"   Tables: {len(schema['tables'])}")
            print(f"   Columns: {len(schema['columns'])}")
            print(f"   Relations: {len(schema['relations'])}")

            # Enrich schema with rich Persian descriptions via Ollama
            print(f"\n🤖 Enriching schema with Persian LLM descriptions...")
            enrich_schema(schema)

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(schema, f, indent=2, ensure_ascii=False)

            print(f"\n✅ Enriched schema saved to: {output_file}")
            
            return True
        except Exception as e:
            print(f"✗ Error during extraction: {e}")
            return False
        finally:
            if self.connection:
                self.connection.close()


def main():
    """Main execution function"""
    # SQL Server connection details
    config = {
        'server': '.\Local2022',
        'database': 'Team10BookShop',
        'username': 'sa',
        'password': "1212"
    }

    # config = {
    #     'server': '192.168.100.16',
    #     'database': 'SimacNashr',
    #     'username': 'sa',
    #     'password': "Aa12345678"
    # }
    
    # Output file path
    output_file = 'data_schema/simacnashr_schema.json'
    
    print("=" * 60)
    print("   SQL Server Schema Extractor")
    print("=" * 60)
    print(f"\nServer: {config['server']}")
    print(f"Database: {config['database']}")
    print(f"Output: {output_file}\n")
    
    # Extract schema
    extractor = SchemaExtractor(
        server=config['server'],
        database=config['database'],
        username=config['username'],
        password=config['password']
    )
    
    success = extractor.save_schema(output_file)
    
    if success:
        print("\n" + "=" * 60)
        print("Schema extraction completed successfully!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("Schema extraction failed!")
        print("=" * 60)


if __name__ == "__main__":
    main()
