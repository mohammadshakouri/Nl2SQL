You are extending the existing NL2SQL backend project to add **Spider 1 benchmark evaluation capability**.

The current system already supports:

* SQL Server schema extraction
* Schema embedding with Chroma
* Retrieval-based NL2SQL generation
* Validation + feedback loop
* Streaming FastAPI endpoint

You must **add Spider evaluation support without modifying or breaking the existing API pipeline**.

---

# OBJECTIVES

Implement a complete Spider 1 evaluation pipeline that:

1. Loads Spider `dev.json`
2. Runs NL2SQL inference for each question
3. Generates predicted SQL
4. Computes:

   * Exact Match (EM)
   * Execution Accuracy (EX)
5. Prints final benchmark metrics

---

# ARCHITECTURAL CONSTRAINTS

* Do NOT modify `/nl2sql` endpoint
* Do NOT modify streaming behavior
* Do NOT break Postgre logging
* Add evaluation as separate CLI module
* Must support SQLite execution (Spider databases are SQLite)

---

# CREATE NEW MODULE

Create directory:

```plaintext
backend/app/spider_eval/
```

---

# FILES TO IMPLEMENT

---

## 1️⃣ spider_loader.py

Responsibilities:

* Load:

  * dev.json
  * tables.json
* Parse:

  * question
  * query (gold SQL)
  * db_id

Create data model:

```python
class SpiderSample:
    question: str
    gold_sql: str
    db_id: str
```

Provide:

```python
def load_spider_dev(path: str) -> List[SpiderSample]
```

---

## 2️⃣ spider_sqlite_executor.py

Responsibilities:

* Load SQLite database from:

```
<spider_path>/database/<db_id>/<db_id>.sqlite
```

* Execute predicted SQL
* Execute gold SQL
* Compare result sets

Return:

```python
(success: bool, error: Optional[str])
```

Comparison must:

* Sort rows
* Compare full result sets
* Ignore row ordering differences

---

## 3️⃣ spider_evaluator.py

Implement:

### Exact Match

```python
def normalize_sql(sql: str) -> str
def exact_match(pred_sql: str, gold_sql: str) -> bool
```

Normalization:

* lowercase
* remove extra spaces
* strip trailing semicolon

---

### Execution Accuracy

```python
def execution_match(pred_sql, gold_sql, executor) -> bool
```

* Execute both
* Compare result sets
* If both fail → count as False
* If both return same results → True

---

## 4️⃣ spider_runner.py

Main evaluation loop.

For each Spider sample:

1. Load SQLite schema
2. Extract schema into JSON format compatible with SchemaManager
3. Create temporary Chroma collection:
   `Schema_spider_<db_id>`
4. Run NL2SQLChain:

   * validate_execution=False
5. Capture predicted SQL
6. Evaluate EM
7. Evaluate EX

Accumulate metrics.

Return:

```python
{
    "total": int,
    "exact_match": float,
    "execution_accuracy": float
}
```

---

## 5️⃣ cli_spider_eval.py

Add CLI entry:

```bash
python cli_spider_eval.py --spider_path ./spider
```

It must:

* Load dev.json
* Run spider_runner
* Print:

```
Spider Evaluation Results
=========================
Total Samples: 1034
Exact Match: 71.82%
Execution Accuracy: 78.45%
```

---

# 🧠 SQLITE SCHEMA SUPPORT

Add new class:

```python
SQLiteSchemaExtractor
```

It must:

* Inspect SQLite schema using:

  ```
  SELECT name FROM sqlite_master WHERE type='table';
  ```
* Extract columns
* Extract foreign keys using:

  ```
  PRAGMA foreign_key_list(table_name);
  ```
* Output schema JSON identical to current SQL Server format:

```json
{
  "database_name": "...",
  "tables": [],
  "columns": [],
  "relations": []
}
```

This ensures SchemaManager works unchanged.

---

# ⚙ INTEGRATION DETAILS

During evaluation:

* Skip feedback loop retries
* Use single-pass generation
* Disable execution validation inside NL2SQLChain
* Do NOT store Spider results in Postgre database

---

# 📊 METRICS COMPUTATION

Exact Match:

```
EM = correct_exact / total
```

Execution Accuracy:

```
EX = correct_execution / total
```

Return float percentages rounded to 2 decimals.

---

# 🔒 DO NOT

* Modify FastAPI app
* Modify schema extraction for SQL Server
* Modify feedback endpoint
* Modify existing vector store initialization logic

---

# 🧪 ACCEPTANCE TEST

After implementation:

```bash
python cli_spider_eval.py --spider_path ./spider
```

Must:

* Iterate all dev samples
* Run inference
* Print EM and EX
* Not crash
* Not modify production data

