# Database Schema Extractor

Automatically extract database schema information from SQL Server and generate JSON schema files compatible with the NL2SQL system.

## Features

- ✅ Extracts tables, columns, data types, and descriptions
- ✅ Identifies primary keys and foreign key relationships
- ✅ Supports SQL Server extended properties for descriptions
- ✅ Generates JSON in the same format as `ecommerce_schema.json`
- ✅ Works with SQL Server authentication

## Prerequisites

1. Install required package:
```bash
pip install pyodbc
```

2. Install SQL Server ODBC Driver:
   - **Windows**: Download and install [Microsoft ODBC Driver 17 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
   - **Alternative**: Use ODBC Driver 18 or SQL Server Native Client if available

## Usage

### Option 1: Direct Execution

Edit the connection details in `extract_schema.py`:

```python
config = {
    'server': '192.168.100.16',
    'database': 'SimacNashr',
    'username': 'sa',
    'password': '345678'
}
```

Then run:
```bash
cd backend
python extract_schema.py
```

### Option 2: Use as Module

```python
from extract_schema import SchemaExtractor

extractor = SchemaExtractor(
    server='192.168.100.16',
    database='SimacNashr',
    username='sa',
    password='345678'
)

extractor.save_schema('data_schema/my_schema.json')
```

## Output Format

The generated JSON file will have this structure:

```json
{
  "database_name": "SimacNashr",
  "description": "Database schema for SimacNashr",
  "tables": [
    {
      "name": "TableName",
      "description": "Table description",
      "key_columns": ["PrimaryKey"],
      "business_role": "Business purpose"
    }
  ],
  "columns": [
    {
      "table_name": "TableName",
      "column_name": "ColumnName",
      "meaning": "Column description",
      "data_type": "integer",
      "operations": "Operations on column"
    }
  ],
  "relations": [
    {
      "source_table": "ChildTable",
      "source_column": "ForeignKey",
      "target_table": "ParentTable",
      "target_column": "PrimaryKey",
      "relationship_type": "many-to-one",
      "join_purpose": "Relationship description"
    }
  ]
}
```

## Using with NL2SQL

After generating the schema file:

1. Place the generated JSON file in `backend/data_schema/`
2. Update your NL2SQL configuration to use the new schema
3. Initialize the vector database with the new schema:

```python
from app.schema_manager import SchemaManager

schema_manager = SchemaManager('data_schema/simacnashr_schema.json')
schema_manager.initialize_vector_db()
```

## Troubleshooting

### Connection Issues

If you encounter connection errors:

1. **Check ODBC Driver**: Verify ODBC Driver 17 is installed
   ```bash
   # List available drivers
   python -c "import pyodbc; print(pyodbc.drivers())"
   ```

2. **Try different drivers** in the connection string:
   - `ODBC Driver 17 for SQL Server`
   - `ODBC Driver 18 for SQL Server`
   - `SQL Server Native Client 11.0`
   - `SQL Server`

3. **Network access**: Ensure SQL Server allows remote connections and port 1433 is open

4. **Authentication**: Verify SQL Server authentication is enabled (not just Windows Authentication)

### Empty Descriptions

If descriptions are empty, SQL Server extended properties may not be set. You can:
- Add descriptions manually to the JSON file
- Add extended properties in SQL Server:
  ```sql
  EXEC sp_addextendedproperty 
      @name = N'MS_Description',
      @value = N'Your description here',
      @level0type = N'SCHEMA', @level0name = 'dbo',
      @level1type = N'TABLE',  @level1name = 'YourTable',
      @level2type = N'COLUMN', @level2name = 'YourColumn'
  ```

## Configuration Tips

### Custom Output Path
```python
output_file = 'data_schema/custom_name_schema.json'
extractor.save_schema(output_file)
```

### Filter Specific Tables
Modify the `get_tables()` method to add a WHERE clause:
```sql
WHERE t.TABLE_NAME IN ('Table1', 'Table2', 'Table3')
```

### Include System Tables
Remove the schema filter:
```sql
-- Remove this line:
AND t.TABLE_SCHEMA = 'dbo'
```

## Next Steps

After extraction:
1. Review the generated JSON file
2. Add/improve Persian descriptions if needed
3. Verify relationships are correct
4. Update business_role and operations fields
5. Test with NL2SQL queries
