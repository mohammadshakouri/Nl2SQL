# Schema-RAG (NL2SQL) System - Setup Guide

## 📋 Overview

This system extends the existing text-based RAG to support **Natural Language to SQL (NL2SQL)** using a **Schema-RAG architecture**.

### Key Features
- ✅ Schema-aware SQL generation
- ✅ Vector-based schema retrieval
- ✅ No SQL hallucination (uses only retrieved schema)
- ✅ Automatic JOIN inference from relations
- ✅ SQL validation and feedback loop
- ✅ Streaming SQL generation
- ✅ Multi-language support (Persian/English)

---

## 🏗️ Architecture

```
User Question (NL)
    ↓
Schema Retrieval (Vector Search)
    ↓
Context Assembly (Tables + Columns + Relations)
    ↓
SQL Generation (LLM)
    ↓
Validation & Feedback Loop
    ↓
Final SQL Query
```

---

## 📁 Project Structure

```
backend/
├── app/
│   ├── schema_manager.py        # Schema-to-embedding conversion
│   ├── sql_validator.py         # SQL validation & feedback loop
│   ├── nl2sql_chain.py          # NL2SQL pipeline orchestrator
│   ├── system_prompt.py         # SQL generation prompts (extended)
│   ├── utilities.py             # Schema utilities (extended)
│   ├── schemas.py               # NL2SQLRequest model (extended)
│   └── main.py                  # /nl2sql endpoint (extended)
│
├── data_schema/
│   ├── ecommerce_schema.json    # Example schema definition
│   └── example_queries.md       # Example NL→SQL pairs
│
└── chroma_db/
    └── Schema_ecommerce/        # Vector store for schema (auto-generated)
```

---

## 🚀 Quick Start

### Step 1: Install Dependencies

```bash
pip install sqlparse chromadb
```

All other dependencies are already installed from the existing RAG system.

### Step 2: Prepare Your Database Schema

Create a JSON file in `data_schema/` directory:

```json
{
  "database_name": "your_db",
  "tables": [
    {
      "name": "TableName",
      "description": "Business description",
      "key_columns": ["col1", "col2"],
      "business_role": "Purpose of this table"
    }
  ],
  "columns": [
    {
      "table_name": "TableName",
      "column_name": "col1",
      "meaning": "What this column represents",
      "data_type": "integer",
      "operations": "How it's used in queries"
    }
  ],
  "relations": [
    {
      "source_table": "TableA",
      "source_column": "FK_ID",
      "target_table": "TableB",
      "target_column": "PK_ID",
      "relationship_type": "many-to-one",
      "join_purpose": "Why these tables are joined"
    }
  ]
}
```

### Step 3: Create Schema Vector Store

Run this Python script to generate embeddings:

```python
from app.schema_manager import SchemaManager
from app.utilities import create_schema_vector_store

# Create vector store for your schema
stats = create_schema_vector_store(
    schema_json_path="./data_schema/ecommerce_schema.json",
    schema_name="ecommerce"
)

print(f"Schema embedded: {stats}")
```

Or use the initialization in `main.py` by adding to the startup:

```python
# In initialize() function in main.py
if not os.path.exists("./chroma_db/Schema_ecommerce"):
    utils.create_schema_vector_store(
        "./data_schema/ecommerce_schema.json",
        "ecommerce"
    )
```

### Step 4: Test the System

#### Option A: Via API

```bash
curl -X POST "http://localhost:80/nl2sql" \
  -H "api_key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "",
    "question": "کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟",
    "schema_name": "ecommerce",
    "culture": "fa",
    "validate_execution": false
  }'
```

#### Option B: Via Python

```python
from app.nl2sql_chain import NL2SQLChain
from app.schema_manager import SchemaManager

# Load schema
manager = SchemaManager()
manager.load_schema_from_json("./data_schema/ecommerce_schema.json")

# Initialize chain
chain = NL2SQLChain(
    schema_manager=manager,
    collection_name="Schema_ecommerce",
    culture="fa"
)

# Generate SQL
result = await chain.execute_pipeline(
    question="کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟",
    validate_execution=False
)

print(f"Generated SQL:\n{result['sql']}")
print(f"Success: {result['success']}")
print(f"Iterations: {result['iterations']}")
```

---

## 🔧 Configuration

### Environment Variables (in `.env` or `app/dotenv.py`)

No new environment variables are required. The system uses existing:
- `USE_LOCAL_LLM`: Use Ollama vs OpenAI
- `USE_LOCAL_EMBEDDING`: Use local embeddings vs OpenAI
- `OPENAI_API_KEY`: If using OpenAI

### Embedding Models

Default models (same as text RAG):
- **Local**: `google/embeddinggemma-300m`
- **OpenAI**: `text-embedding-3-small`

### LLM Models

Default models (same as text RAG):
- **Local**: `gemma3:4b` (Ollama)
- **OpenAI**: `gpt-4o-mini`

**Note:** For SQL generation, temperature is set to **0.1** (lower than text RAG) for more deterministic output.

---

## 📊 API Endpoints

### 1. `/nl2sql` - Generate SQL from Natural Language

**Method:** POST

**Request Body:**
```json
{
  "threadId": "",
  "question": "Natural language question",
  "schema_name": "ecommerce",
  "culture": "fa",
  "validate_execution": false
}
```

**Response:** Server-Sent Events (SSE) stream

```
data: {"event": "on_start", "run_id": "...", "thread_id": "...", "type": "nl2sql"}
data: {"event": "on_stream", "data": "SELECT"}
data: {"event": "on_stream", "data": " c.Name"}
...
data: {"event": "on_end", "sql": "SELECT...", "latency": 1.23}
```

### 2. `/nl2sql/validate` - Validate Schema Setup

**Method:** POST

**Parameters:** `schema_name` (string)

**Response:**
```json
{
  "schema_name": "ecommerce",
  "schema_json_exists": true,
  "collection_exists": true,
  "collection_count": 45,
  "is_valid": true,
  "errors": []
}
```

---

## 🧪 Testing Examples

See [data_schema/example_queries.md](data_schema/example_queries.md) for comprehensive test cases.

Quick test questions:

**Persian:**
- "کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟"
- "محبوب‌ترین محصولات از نظر تعداد فروش کدامند؟"
- "میانگین مبلغ خرید در سه ماه گذشته چقدر بوده است؟"

**English:**
- "Which customers purchased more than 5 million tomans last month?"
- "What are the most popular products by sales count?"
- "What is the average purchase amount in the last 3 months?"

---

## 🛡️ Security & Validation

### Validation Layers

1. **Syntax Validation**: Uses `sqlparse` to validate SQL syntax
2. **Schema Validation**: Ensures tables/columns exist in schema
3. **Read-Only Enforcement**: Only SELECT statements allowed
4. **Execution Validation** (optional): Test query against database

### Feedback Loop

If SQL generation fails:
1. Error is captured
2. Feedback prompt is generated
3. LLM regenerates corrected SQL
4. Maximum 3 iterations

---

## 📈 Extending the System

### Adding a New Database Schema

1. Create `data_schema/your_db_schema.json`
2. Run embedding generation:
   ```python
   utils.create_schema_vector_store(
       "./data_schema/your_db_schema.json",
       "your_db"
   )
   ```
3. Use in API: `schema_name: "your_db"`

### Customizing SQL Generation

Edit prompts in `app/system_prompt.py`:
- `SYSTEM_PROMPT_NL2SQL_FA`: Persian SQL generation
- `SYSTEM_PROMPT_NL2SQL_EN`: English SQL generation
- `SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA/EN`: Error correction

### Adding SQL Dialect Support

Modify `app/sql_validator.py` and `app/nl2sql_chain.py` to add dialect-specific:
- Date functions
- String operations
- Aggregate functions

---

## 🚨 Troubleshooting

### Issue: "No relevant schema elements found"

**Solution:** 
- Check if schema vector store was created
- Run `/nl2sql/validate` endpoint
- Ensure question relates to schema domain

### Issue: SQL syntax errors

**Solution:**
- Check SQL dialect compatibility
- Review generated SQL in feedback loop history
- Adjust prompts for your SQL dialect

### Issue: Slow embedding generation

**Solution:**
- Use OpenAI embeddings instead of local
- Reduce schema granularity (fewer columns)
- Increase batch size in `create_schema_vector_store`

---

## 📚 References

- **Schema Linking**: Retrieval-based schema element selection
- **RAG-SQL**: Retrieval-Augmented Generation for SQL
- **No Hallucination**: Only use retrieved schema, never invent tables/columns

---

## 🎯 Best Practices

1. **Schema Design**: Write business-level descriptions (not technical IDs)
2. **Embedding Length**: Keep descriptions 30-60 tokens
3. **Relations**: Always define foreign keys explicitly
4. **Testing**: Test with example queries before production
5. **Monitoring**: Log generated SQL and validation errors

---

## 📞 Support

For issues or questions, refer to:
- [example_queries.md](data_schema/example_queries.md) - Example test cases
- [ecommerce_schema.json](data_schema/ecommerce_schema.json) - Schema template

---

**Status:** ✅ Production-ready Schema-RAG (NL2SQL) system fully implemented
