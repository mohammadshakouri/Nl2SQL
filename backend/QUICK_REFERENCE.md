# Schema-RAG (NL2SQL) - Quick Reference

## 🚀 Quick Start (3 Steps)

### 1. Install Dependencies
```bash
pip install sqlparse
```

### 2. Initialize System
```bash
python initialize_nl2sql.py
```

### 3. Test
```bash
python demo_nl2sql.py
```

---

## 📡 API Reference

### Generate SQL
```bash
POST /nl2sql
```

**Request:**
```json
{
  "threadId": "",
  "question": "کدام مشتریان بیش از ۵ میلیون تومان خرید کرده‌اند؟",
  "schema_name": "ecommerce",
  "culture": "fa"
}
```

**Response:** SSE Stream
```
data: {"event": "on_start", "run_id": "...", "thread_id": "..."}
data: {"event": "on_stream", "data": "SELECT"}
data: {"event": "on_end", "sql": "SELECT c.Name..."}
```

### Validate Setup
```bash
POST /nl2sql/validate?schema_name=ecommerce
```

**Response:**
```json
{
  "is_valid": true,
  "schema_json_exists": true,
  "collection_exists": true
}
```

---

## 🗂️ File Structure

```
app/
├── schema_manager.py       # Schema → Embeddings
├── sql_validator.py        # SQL Validation
├── nl2sql_chain.py         # Pipeline Orchestrator
└── system_prompt.py        # SQL Prompts

data_schema/
└── ecommerce_schema.json   # Example Schema
```

---

## 📝 Schema JSON Format

```json
{
  "tables": [
    {
      "name": "TableName",
      "description": "Business description",
      "key_columns": ["col1", "col2"],
      "business_role": "Purpose"
    }
  ],
  "columns": [
    {
      "table_name": "TableName",
      "column_name": "col1",
      "meaning": "What it represents",
      "data_type": "type",
      "operations": "How it's used"
    }
  ],
  "relations": [
    {
      "source_table": "TableA",
      "source_column": "FK",
      "target_table": "TableB",
      "target_column": "PK",
      "relationship_type": "many-to-one",
      "join_purpose": "Why joined"
    }
  ]
}
```

---

## 🐍 Python Usage

### Create Schema Vector Store
```python
from app.utilities import create_schema_vector_store

stats = create_schema_vector_store(
    "./data_schema/mydb_schema.json",
    "mydb"
)
```

### Generate SQL (Non-Streaming)
```python
from app.nl2sql_chain import NL2SQLChain
from app.schema_manager import SchemaManager

manager = SchemaManager()
manager.load_schema_from_json("./data_schema/ecommerce_schema.json")

chain = NL2SQLChain(manager, "Schema_ecommerce", "fa")

result = await chain.execute_pipeline("سوال شما")
print(result['sql'])
```

### Validate SQL
```python
from app.sql_validator import SQLValidator

validator = SQLValidator(schema_manager)
is_valid, error = validator.validate_query(sql)
```

---

## 🔧 Configuration

### Environment Variables
- `USE_LOCAL_LLM`: `true` for Ollama, `false` for OpenAI
- `USE_LOCAL_EMBEDDING`: `true` for local, `false` for OpenAI
- `OPENAI_API_KEY`: Your OpenAI key

### Default Models
- **LLM (Local):** `gemma3:4b`
- **LLM (Cloud):** `gpt-4o-mini`
- **Embedding (Local):** `google/embeddinggemma-300m`
- **Embedding (Cloud):** `text-embedding-3-small`

### Tuning Parameters
- **Temperature:** `0.1` (SQL generation)
- **Retrieval Threshold:** `0.7` (similarity)
- **Top-K:** `10` (schema elements)
- **Max Iterations:** `3` (feedback loop)

---

## ✅ Validation Layers

1. **Syntax:** `sqlparse` checks
2. **Schema:** Table/column existence
3. **Security:** SELECT-only enforcement
4. **Execution:** Optional DB validation

---

## 🐛 Troubleshooting

### "No relevant schema elements found"
→ Run: `python initialize_nl2sql.py`

### "Import sqlparse error"
→ Run: `pip install sqlparse`

### SQL syntax errors
→ Check dialect compatibility
→ Review feedback loop history

### Slow embedding
→ Switch to OpenAI embeddings
→ Reduce schema granularity

---

## 📚 Documentation Files

| File | Purpose |
|------|---------|
| `NL2SQL_README.md` | Complete overview |
| `NL2SQL_SETUP.md` | Detailed setup |
| `IMPLEMENTATION_REPORT.md` | Technical report |
| `example_queries.md` | Test cases |

---

## 🧪 Example Questions

**Persian:**
- "کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟"
- "محبوب‌ترین محصولات از نظر تعداد فروش کدامند؟"
- "میانگین مبلغ خرید در سه ماه گذشته چقدر بوده است؟"

**English:**
- "Which customers purchased more than 5 million last month?"
- "What are the most popular products by sales count?"
- "What is the average purchase amount in the last 3 months?"

---

## 🎯 Key Features

✓ Schema-aware SQL generation
✓ No SQL hallucination
✓ Automatic JOIN inference
✓ Multi-language support (FA/EN)
✓ Streaming responses
✓ Feedback loop correction
✓ Read-only enforcement

---

## 📞 Quick Commands

```bash
# Initialize
python initialize_nl2sql.py

# Demo
python demo_nl2sql.py

# Start server
python main.py

# Validate
curl -X POST "http://localhost:80/nl2sql/validate?schema_name=ecommerce" \
  -H "api_key: YOUR_KEY"
```

---

**Status:** ✅ Production Ready
**Version:** 1.0
**Date:** December 2025
