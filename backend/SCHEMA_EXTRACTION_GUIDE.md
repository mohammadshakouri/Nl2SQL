# 🚀 Automatic Database Schema Extraction - Complete Guide

## Overview

This system automatically extracts database schema information from SQL Server and generates JSON files compatible with your NL2SQL system. No manual schema creation needed!

## 📁 Files Created

1. **`extract_schema.py`** - Core extraction engine
2. **`extract_schema_interactive.py`** - Interactive CLI for easy use
3. **`enhance_schema.py`** - Enhances auto-generated descriptions
4. **`SCHEMA_EXTRACTOR_README.md`** - Detailed documentation

## 🎯 Quick Start

### Method 1: Using Default Configuration (SimacNashr)

```bash
cd backend
python extract_schema.py
```

This will:
- Connect to: `192.168.100.16`
- Database: `SimacNashr`
- User: `sa`
- Output: `data_schema/simacnashr_schema.json`

### Method 2: Interactive Mode (Any Database)

```bash
cd backend
python extract_schema_interactive.py
```

Then enter your connection details when prompted.

### Method 3: Custom Script

```python
from extract_schema import SchemaExtractor

extractor = SchemaExtractor(
    server='your_server',
    database='your_database',
    username='your_username',
    password='your_password'
)

extractor.save_schema('data_schema/output.json')
```

## 📊 What Gets Extracted

The system automatically extracts:

✅ **Tables**
- Table names
- SQL Server extended property descriptions
- Primary key columns
- Business purpose (auto-generated)

✅ **Columns**
- Column names
- Data types (mapped to generic types)
- Nullable/Not Nullable
- Primary key indicators
- Column descriptions from extended properties

✅ **Relationships**
- Foreign key relationships
- Source and target tables
- Relationship types (many-to-one, one-to-many)
- Join purposes

## 🔧 Enhancement Process

After extraction, enhance descriptions:

```bash
python enhance_schema.py data_schema/simacnashr_schema.json
```

This creates `simacnashr_schema_enhanced.json` with:
- Better Persian descriptions for known tables (Book, Category, Orders, etc.)
- Improved column descriptions based on naming patterns
- Contextual operation descriptions

## 📝 Your SimacNashr Database

**Successfully Extracted:**
- ✅ 14 tables
- ✅ 77 columns
- ✅ 7 foreign key relationships

**Key Tables:**
- `Book` - کتاب‌های موجود در سامانه
- `Category` - دسته‌بندی کتاب‌ها
- `Orders` - سفارشات کاربران
- `OrderDetails` - جزئیات اقلام سفارش
- `AspNetUsers` - کاربران سیستم
- `Tokens` - توکن‌های احراز هویت

**Generated Files:**
- `data_schema/simacnashr_schema.json` - Original extraction
- `data_schema/simacnashr_schema_enhanced.json` - With better descriptions

## 🔄 Integration with NL2SQL

### Step 1: Choose Your Schema

Use the enhanced version for better results:
```bash
cp data_schema/simacnashr_schema_enhanced.json data_schema/simacnashr_schema.json
```

### Step 2: Initialize Vector Database

```python
from app.schema_manager import SchemaManager

schema_manager = SchemaManager('data_schema/simacnashr_schema.json')
schema_manager.initialize_vector_db()
```

### Step 3: Update Your Application

In your `main.py` or configuration:
```python
SCHEMA_FILE = "data_schema/simacnashr_schema.json"
```

### Step 4: Test Queries

Example queries your system can now handle:
- "چند کتاب در سیستم داریم؟" (How many books in the system?)
- "لیست سفارشات امروز" (List today's orders)
- "پرفروش‌ترین کتاب‌ها" (Best-selling books)
- "کاربران فعال در هفته گذشته" (Active users last week)

## 🛠️ Customization

### Add Custom Descriptions

Edit the enhanced JSON file manually to add specific business context:

```json
{
  "table_name": "Book",
  "column_name": "ISBN",
  "meaning": "شماره شابک کتاب برای شناسایی بین‌المللی",
  "data_type": "varchar",
  "operations": "جستجو و شناسایی یکتای کتاب"
}
```

### Filter Specific Tables

Modify `extract_schema.py`, line ~50:

```python
WHERE t.TABLE_TYPE = 'BASE TABLE'
AND t.TABLE_SCHEMA = 'dbo'
AND t.TABLE_NAME IN ('Book', 'Orders', 'OrderDetails')  # Add this
```

### Add Persian Descriptions for More Tables

Edit `enhance_schema.py`, add to `PERSIAN_TEMPLATES`:

```python
'YourTableName': {
    'description': 'توضیحات فارسی',
    'business_role': 'نقش کسب‌وکاری'
}
```

## 🔍 Troubleshooting

### Connection Issues

**Error:** `[Microsoft][ODBC Driver 17 for SQL Server] Login failed`
- ✅ Check SQL Server authentication is enabled
- ✅ Verify username and password
- ✅ Ensure SQL Server allows remote connections

**Error:** `No module named 'pyodbc'`
```bash
pip install pyodbc
```

**Error:** `Data source name not found`
- ✅ Install ODBC Driver 17 for SQL Server
- ✅ Try alternative drivers in connection string

### Empty Descriptions

If descriptions are generic:
1. Run the enhancer: `python enhance_schema.py <file>`
2. Manually add descriptions to the JSON
3. Add SQL Server extended properties:

```sql
EXEC sp_addextendedproperty 
    @name = N'MS_Description',
    @value = N'توضیحات فارسی',
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'Book'
```

## 📦 Requirements

Added to `requirements.txt`:
```
pyodbc==5.2.0
```

System Requirements:
- Python 3.7+
- SQL Server ODBC Driver 17 or 18
- Network access to SQL Server
- SQL Server authentication enabled

## 🎨 Architecture

```
Database (SQL Server)
    ↓
extract_schema.py (Connects & Queries)
    ↓
Raw Schema JSON (Auto-generated)
    ↓
enhance_schema.py (Adds context)
    ↓
Enhanced Schema JSON (Better descriptions)
    ↓
NL2SQL System (Vector DB + LLM)
```

## 💡 Best Practices

1. **Extract First, Enhance Later**
   - Always run extractor first
   - Then enhance with better descriptions
   - Finally, manually review and improve

2. **Version Control**
   - Keep both original and enhanced versions
   - Document custom changes
   - Track schema updates

3. **Regular Updates**
   - Re-extract when database schema changes
   - Merge custom descriptions with new extractions
   - Test NL2SQL queries after updates

4. **Security**
   - Don't commit passwords to version control
   - Use environment variables for credentials
   - Restrict database user permissions

## 🚀 Advanced Usage

### Multiple Databases

Extract from multiple databases:
```python
databases = ['DB1', 'DB2', 'DB3']
for db in databases:
    extractor = SchemaExtractor('server', db, 'user', 'pass')
    extractor.save_schema(f'data_schema/{db.lower()}_schema.json')
```

### Scheduled Extraction

Set up automatic extraction:
```bash
# Windows Task Scheduler or cron job
python extract_schema.py && python enhance_schema.py data_schema/simacnashr_schema.json
```

### Compare Schemas

Detect schema changes:
```python
import json

with open('old_schema.json') as f:
    old = json.load(f)
with open('new_schema.json') as f:
    new = json.load(f)

# Compare table counts, column counts, etc.
```

## 📚 Additional Resources

- [SQL Server ODBC Driver Download](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- [pyodbc Documentation](https://github.com/mkleehammer/pyodbc/wiki)
- [SQL Server System Tables](https://learn.microsoft.com/en-us/sql/relational-databases/system-information-schema-views)

## ✅ Next Steps

1. ✅ Schema extracted from SimacNashr
2. ✅ Enhanced with better descriptions
3. ⏭️ Review and customize descriptions
4. ⏭️ Initialize vector database
5. ⏭️ Test with NL2SQL queries
6. ⏭️ Deploy to production

---

**Created:** December 2025  
**Database:** SimacNashr  
**Status:** ✅ Ready to use
