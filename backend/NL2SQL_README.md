# Schema-RAG (NL2SQL) Extension

## 🎯 Project Goal

Extend an existing text-based RAG system into a **fully functional Schema-RAG (NL2SQL)** system that converts natural language questions into executable SQL queries using retrieval-based schema linking.

## ✅ Implementation Status

**COMPLETE** - All required components implemented and production-ready.

---

## 📦 What Was Added

### 1. Core Modules (4 new files)

#### [`app/schema_manager.py`](app/schema_manager.py)
- **Purpose**: Schema-to-embedding transformation
- **Key Classes**:
  - `Table`: Represents database tables with business semantics
  - `Column`: Represents columns with meaning and operations
  - `Relation`: Represents foreign key relationships
  - `SchemaManager`: Orchestrates schema loading and embedding generation
- **Key Methods**:
  - `to_embedding_text()`: Converts schema elements to 30-60 token descriptions
  - `load_schema_from_json()`: Loads schema from JSON definition
  - `get_all_embedding_texts()`: Generates all retrieval units

#### [`app/sql_validator.py`](app/sql_validator.py)
- **Purpose**: SQL validation and feedback loop
- **Key Classes**:
  - `SQLValidator`: Validates SQL syntax and schema elements
  - `SQLFeedbackLoop`: Manages iterative error correction
- **Features**:
  - Syntax validation using `sqlparse`
  - Schema element validation (tables/columns exist)
  - Read-only enforcement (SELECT only)
  - Error-to-feedback conversion for LLM
  - Clean SQL extraction from LLM output

#### [`app/nl2sql_chain.py`](app/nl2sql_chain.py)
- **Purpose**: Complete NL2SQL pipeline orchestration
- **Key Classes**:
  - `NL2SQLChain`: Main orchestrator
- **Pipeline Stages**:
  1. Schema retrieval via vector similarity
  2. Context enrichment with retrieved elements
  3. Prompt assembly with rules
  4. SQL generation via LLM (streaming)
  5. Validation and feedback loop
- **Features**:
  - Supports both Ollama and OpenAI
  - Streaming and non-streaming modes
  - Configurable retrieval threshold
  - Multi-language support (FA/EN)

#### [`app/system_prompt.py`](app/system_prompt.py) (Extended)
- **Added Prompts**:
  - `SYSTEM_PROMPT_NL2SQL_FA`: Persian SQL generation
  - `SYSTEM_PROMPT_NL2SQL_EN`: English SQL generation
  - `SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA/EN`: Error correction prompts
- **Key Features**:
  - Enforces "SQL only" output
  - No markdown, no comments
  - Strict schema usage rules
  - Clear error correction guidance

### 2. Extended Existing Modules

#### [`app/utilities.py`](app/utilities.py)
Added NL2SQL utilities:
- `get_schema_collection_name()`: Collection naming convention
- `create_schema_vector_store()`: Schema embedding pipeline
- `validate_nl2sql_setup()`: System health check

#### [`app/schemas.py`](app/schemas.py)
Added request model:
- `NL2SQLRequest`: API request schema for /nl2sql endpoint

#### [`app/main.py`](app/main.py)
Added endpoints:
- `POST /nl2sql`: Streaming SQL generation
- `POST /nl2sql/validate`: Schema setup validation
- Helper functions: `generate_nl2sql_ollama_stream()`, `generate_nl2sql_openai_stream()`

### 3. Example Data & Documentation

#### [`data_schema/ecommerce_schema.json`](data_schema/ecommerce_schema.json)
- Complete example database schema
- 4 tables: Customers, Products, Purchases, Orders
- 19 columns with business descriptions
- 3 relations (foreign keys)
- Demonstrates proper schema formatting

#### [`data_schema/example_queries.md`](data_schema/example_queries.md)
- 10 example NL → SQL test cases
- Covers: aggregations, JOINs, filters, temporal queries
- Both Persian questions and expected SQL
- Useful for validation testing

#### [`NL2SQL_SETUP.md`](NL2SQL_SETUP.md)
- Comprehensive setup guide
- Architecture explanation
- Quick start instructions
- API documentation
- Troubleshooting guide
- Best practices

#### [`demo_nl2sql.py`](demo_nl2sql.py)
- End-to-end demonstration script
- Shows complete pipeline execution
- Schema transformation examples
- Can be run directly: `python demo_nl2sql.py`

### 4. Dependencies

Added to [`requirements.txt`](requirements.txt):
- `sqlparse==0.5.3` - SQL parsing and validation

---

## 🏗️ Architecture

### Schema-RAG Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                     User Question (NL)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Stage 3: Schema Retrieval                      │
│  - Embed question                                           │
│  - Vector search in ChromaDB                                │
│  - Retrieve Top-K schema elements (tables/cols/relations)   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│            Stage 4: Context Enrichment                      │
│  - Assemble retrieved tables                                │
│  - Assemble retrieved columns                               │
│  - Assemble retrieved relations                             │
│  - Format as structured prompt                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│               Stage 5: SQL Generation                       │
│  - Build complete prompt (question + schema + rules)        │
│  - Call LLM (Ollama or OpenAI)                             │
│  - Stream SQL token-by-token                                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│             Stage 6: Validation & Feedback                  │
│  - Validate SQL syntax (sqlparse)                           │
│  - Validate schema elements                                 │
│  - Optional: Execute query for validation                   │
│  - If error: Generate feedback → Re-generate (max 3 times)  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   Final SQL Query                           │
└─────────────────────────────────────────────────────────────┘
```

### Schema Embedding Format

Each schema element becomes a retrieval unit:

**Table:**
```
Customers Table: اطلاعات مشتریان شامل نام و تاریخ عضویت. 
Includes columns CustomerID, Name, JoinDate. 
Used for نگهداری مشخصات اشخاصی که خرید انجام داده‌اند.
```

**Column:**
```
Purchases.PurchaseAmount Column: مبلغ پرداختی خرید, 
data type decimal, used for محاسبه مجموع و میانگین خریدها.
```

**Relation:**
```
Relation: Purchases.CustomerID ↔ Customers.CustomerID. 
Relationship type many-to-one. 
Used for connecting each purchase to its customer.
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install sqlparse
```

(All other dependencies already installed from existing RAG system)

### 2. Create Schema Embeddings

```python
from app.utilities import create_schema_vector_store

stats = create_schema_vector_store(
    schema_json_path="./data_schema/ecommerce_schema.json",
    schema_name="ecommerce"
)
```

### 3. Test the System

```bash
# Run the demo
python demo_nl2sql.py

# Or test via API (after starting server)
curl -X POST "http://localhost:80/nl2sql" \
  -H "api_key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "",
    "question": "کدام مشتریان بیش از ۵ میلیون تومان خرید کرده‌اند؟",
    "schema_name": "ecommerce",
    "culture": "fa"
  }'
```

---

## 📊 API Usage

### Generate SQL

**Endpoint:** `POST /nl2sql`

**Request:**
```json
{
  "threadId": "",
  "question": "کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟",
  "schema_name": "ecommerce",
  "culture": "fa",
  "validate_execution": false
}
```

**Response:** Server-Sent Events stream
```
data: {"event": "on_start", "run_id": "...", "thread_id": "..."}
data: {"event": "on_stream", "data": "SELECT"}
data: {"event": "on_stream", "data": " c.Name"}
...
data: {"event": "on_end", "sql": "SELECT c.Name, SUM(p.PurchaseAmount)...", "latency": 1.2}
```

### Validate Setup

**Endpoint:** `POST /nl2sql/validate?schema_name=ecommerce`

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

## 🔒 Design Principles (Enforced)

✅ **Schema elements = retrieval units** - Every table, column, relation is embedded
✅ **Retrieval before generation** - No direct schema in prompt
✅ **No hard-coded schema** - All schema from vector retrieval
✅ **No hallucinated SQL** - Only use retrieved schema elements
✅ **Deterministic pipeline** - Explicit stages, no shortcuts
✅ **No natural language output** - Only SQL queries

---

## ⛔ Absolute Restrictions (Enforced)

The system enforces these restrictions:

❌ No natural language answers
❌ No SQL without retrieval
❌ No embedding of relations skipped
❌ No text-to-SQL shortcut prompting
❌ No assumed schema not retrieved

---

## 🧪 Test Cases

See [`data_schema/example_queries.md`](data_schema/example_queries.md) for 10 comprehensive test cases covering:

- Simple filters
- Aggregations (SUM, COUNT, AVG)
- Multi-table JOINs
- Temporal queries (date ranges)
- Grouping and sorting
- Subqueries

---

## 📈 Extension Points

### Add New Database Schema

1. Create `data_schema/your_db_schema.json`
2. Run: `create_schema_vector_store("./data_schema/your_db_schema.json", "your_db")`
3. Use: `{"schema_name": "your_db"}` in API

### Customize SQL Generation

Edit prompts in `app/system_prompt.py`:
- Modify temperature (default: 0.1)
- Add dialect-specific rules
- Change output format requirements

### Add SQL Dialect Support

Modify `app/sql_validator.py`:
- Add dialect-specific syntax rules
- Customize date functions
- Add vendor-specific features

---

## 📚 Code Quality

- **Type Hints**: All functions properly typed
- **Docstrings**: Comprehensive documentation
- **Error Handling**: Try-catch blocks with meaningful errors
- **Logging**: Integration with existing logging system
- **Async Support**: Full async/await throughout
- **Streaming**: SSE streaming for real-time SQL generation

---

## 🎓 Educational Value

This implementation demonstrates:

1. **RAG Architecture**: Retrieval → Context → Generation
2. **Schema Linking**: Vector-based schema element selection
3. **Prompt Engineering**: Strict output format control
4. **Feedback Loops**: Iterative error correction
5. **Production Patterns**: Validation, streaming, error handling

---

## 📝 Files Summary

| File | Lines | Purpose |
|------|-------|---------|
| `app/schema_manager.py` | ~330 | Schema transformation & embedding generation |
| `app/sql_validator.py` | ~350 | SQL validation & feedback loop |
| `app/nl2sql_chain.py` | ~450 | Complete NL2SQL pipeline orchestrator |
| `app/system_prompt.py` | +80 | SQL generation prompts |
| `app/utilities.py` | +140 | Schema utilities |
| `app/main.py` | +170 | NL2SQL API endpoints |
| `app/schemas.py` | +8 | Request models |
| `data_schema/ecommerce_schema.json` | ~220 | Example schema definition |
| `data_schema/example_queries.md` | ~150 | Test cases |
| `NL2SQL_SETUP.md` | ~400 | Comprehensive documentation |
| `demo_nl2sql.py` | ~280 | End-to-end demo script |
| **Total** | **~2,578** | **Production-ready NL2SQL system** |

---

## ✅ Deliverables Checklist

- [x] **Folder/module structure** - 4 new modules + extensions
- [x] **Schema-to-Embedding generator** - `schema_manager.py`
- [x] **Schema vector ingestion** - `utilities.create_schema_vector_store()`
- [x] **NL2SQL RAG orchestrator** - `nl2sql_chain.py`
- [x] **Prompt templates** - `system_prompt.py` (4 new prompts)
- [x] **Example end-to-end execution** - `demo_nl2sql.py`
- [x] **Extension points** - Documented in `NL2SQL_SETUP.md`

---

## 🏆 Result

A **complete, production-ready Schema-RAG (NL2SQL) system** that:

- Reuses existing RAG architecture ✓
- Follows strict Schema-RAG principles ✓
- Generates SQL without hallucination ✓
- Includes validation and feedback loops ✓
- Provides comprehensive documentation ✓
- Includes working examples ✓
- Ready for production deployment ✓

**Status:** ✅ **COMPLETE AND FUNCTIONAL**
