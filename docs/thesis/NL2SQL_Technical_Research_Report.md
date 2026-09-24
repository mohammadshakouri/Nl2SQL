# NL2SQL Schema-RAG Framework: Technical and Research Report

*Input for building the 6-month thesis progress presentation. This file is not slides.*

- **Repository:** `mohammadshakouri/Nl2SQL`
- **Code state inspected:** commit `6e55aee` ("edit config"), 2026-09-24
- **Scope:** the entire repository (backend, Spider evaluation, frontend, docs, diagrams) and the relevant git history
- **Method:** I followed the call graph from the entry points (`backend/main.py`, `backend/cli_spider_eval.py`, `backend/extract_schema.py`, `backend/enrich_schema.py`). I also executed the validator, the prompt builder and the schema extractor locally on a synthetic schema, to check behaviour instead of inferring it. **No experiment was run and no accuracy number appears in this report.**

## Status legend (used throughout)

| Label | Meaning |
|---|---|
| **IMPLEMENTED** | The code exists and runs on the active execution path. |
| **PARTIALLY IMPLEMENTED** | The code exists but is incomplete, or it runs in only one of the two pipelines (production API vs. Spider evaluation). |
| **EXPERIMENTAL** | The code is present but disabled or commented out, produces output that nothing consumes, or is a leftover from an earlier design. |
| **PLANNED** | It appears only in documentation or diagrams, with no code in the repository or its git history. |

---

## 0. Critical findings (read these first)

These findings decide what can be shown in the presentation.

1. **Retrieval is dense-only.** Query Enhancement, BM25, RRF and the Reranker appear in `docs/diagrams/OnlineInference.drawio.png` and in `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md`. None of them exists in the code, and none has ever existed in the git history. The only "bm25" hits in the history are inside a committed ChromaDB binary file. `requirements.txt` contains no BM25 or cross-encoder dependency. All four are **PLANNED**.
2. **The results tables in `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md` were not produced by this code.** Examples are "Dense Only EM 69.4 / EX 75.9" and "Hybrid + Iterative + Enriched EM 81.2 / EX 88.4". This codebase cannot have produced them, for three reasons:
   - (a) BM25 and the reranker do not exist.
   - (b) The Spider pipeline never applies metadata enrichment.
   - (c) The EM metric implemented here is a strict string comparison, not the official Spider EM, so it would give much lower values than those in the table.

   Present these tables only as *hypotheses or expected outcomes*, clearly labelled, or remove them. Showing them as results would be academically unsafe. The example numbers in `backend/prompt.md` ("71.82% / 78.45%") are also placeholders from a code-generation spec.
3. **Metadata enrichment exists only in the production (SQL Server) path.** The Spider path builds schemas with placeholder descriptions such as `"Table singer"` and `"Column Name of table singer"`, and never calls the enricher. There is therefore **no runnable "Raw vs Enriched" experiment on Spider yet**. The enrichment is also generated in **Persian**, while Spider questions are English.
4. **The Spider "feedback" mode uses validation feedback only.** It contains no execution feedback. Execution-guided feedback runs only in the production API, against the SQL Server execution database. The "Execution-Guided Feedback Loop" experiment described in the design document is therefore **not runnable on Spider yet**.
5. **The validator is weak.** I confirmed this empirically:
   - `SELEC * FRM singer` and `hello world` both pass the "syntax" check.
   - The column check is a no-op.
   - There are false positives. `SELECT EXTRACT(YEAR FROM birth_date) ...` is rejected as "Table 'birth_date' does not exist".

   As a result, the validation feedback loop rarely fires on real errors and sometimes fires on correct SQL (§9).
6. **The evaluation metrics are non-standard.**
   - **EM** is lowercase and whitespace-normalised string equality, not Spider's official component-based "exact set match".
   - **EX** compares sorted and lower-cased result rows, not the official test-suite evaluation.

   Numbers from this harness are not comparable with published Spider results unless the official scripts are added (§10).
7. **The Spider harness saves no predictions or retrieval traces.** It prints only a status label and a question prefix per sample. Error analysis, schema-linking recall and before/after examples cannot be produced without a small code addition (§14, "Minimal code additions").
8. **The retrieval depth is fixed at K = 15** in both pipelines. The `retrieve_schema_elements` method has a default of 10, but neither pipeline uses it. K is not exposed as a CLI flag. There is no relevance threshold (it is commented out).
9. **`backend/ARCHITECTURE.md` is stale.** It describes a `/chat` endpoint, `/nl2sql/validate`, `dt_chain.py`, "Threshold = 0.7", "Top-K = 10", "max 3 times" and an "Available tables" hint in feedback. None of these matches the current code. Do not use it as a source for slides.
10. **The repository has no automated tests** (no `test_*.py`, no pytest configuration).

---

## 1. Overall Architecture

### 1.1 Two execution paths share one core

The core components are shared: `SchemaManager`, `NL2SQLChain`, `SQLValidator` and `SQLFeedbackLoop`. They are driven by two different orchestrators:

- **Production / interactive path.** `POST /nl2sql` (`backend/main.py:64`) calls `LoadNL2SQLChain` (`backend/app/nl2sql_chain.py:326`), which is an async generator that streams Server-Sent Events. It targets a Microsoft SQL Server database, logs every run to PostgreSQL, and supports human feedback and regeneration.
- **Evaluation path.** `backend/cli_spider_eval.py` calls `run_spider_evaluation` (`backend/app/spider_eval/spider_runner.py:254`). It targets Spider SQLite databases, logs nothing to a database, and computes EM and EX.

### 1.2 Actual data flow (as implemented)

```
OFFLINE (production)                               OFFLINE (Spider, on the fly per db_id)
SQL Server DB                                       Spider SQLite DB
  └─ SchemaExtractor (extract_schema.py)              └─ SQLiteSchemaExtractor (spider_eval/sqlite_schema_extractor.py)
       INFORMATION_SCHEMA + sys.* + MS_Description         sqlite_master + PRAGMA table_info / foreign_key_list
  └─ Schema JSON {tables, columns, relations}         └─ Schema dict (same format, placeholder descriptions)
  └─ enrich_schema(): LLM Persian keywords  ◄─ only here        (NO enrichment)
  └─ data_schema/<name>_schema.json
  └─ SchemaManager → one text per table/column/relation (retrieval units)
  └─ Embedding fn (local SentenceTransformer | OpenAI) → ChromaDB collection "Schema_<name>" / "Schema_spider_<db_id>"

ONLINE (both paths)
NL question ──(no query enhancement)──► embed question (same embedding fn)
  └─ Chroma dense Top-K (K=15, no threshold, no filter) → list of unit texts (distances discarded)
  └─ build_schema_context(): group units into Tables / Columns / Relations sections
  └─ build_user_prompt() + language-specific system prompt → LLM (Ollama local | OpenAI gpt-4o-mini), streaming
  └─ clean_sql_output(): strip ``` fences and comments, flatten, add ';'
  └─ validate_query(): SELECT-first check + FROM/JOIN table-name check
  └─ [production only, optional] execute on SQL Server (ExecutionDB), catch DB error
  └─ on failure: feedback prompt (last failed SQL + error + hint) → regenerate (same retrieved context)
       up to max_iterations total attempts (prod: 4; Spider CLI: --max-iter, default 4)
  └─ production: persist to PostgreSQL, stream on_end   |   Spider: EM + EX against gold
  └─ [production only] user 👎 + corrected SQL + comment → /regenerate re-runs the pipeline with the comment injected
```

### 1.3 Stage-by-stage table

| # | Stage | Input | What happens | Output | Why it exists | Where | Status |
|---|---|---|---|---|---|---|---|
| 1 | Schema extraction (SQL Server) | DB connection | Queries `INFORMATION_SCHEMA.TABLES/COLUMNS`, `sys.foreign_keys`, `sys.extended_properties` (`MS_Description`). Only the `dbo` schema and base tables. PKs come from `TABLE_CONSTRAINTS`. SQL types are mapped to generic types. | Schema JSON | Turns a live DB into a model-independent description | `backend/extract_schema.py:38-209` | IMPLEMENTED |
| 1' | Schema extraction (SQLite) | `.sqlite` file | `sqlite_master`, `PRAGMA table_info`, `PRAGMA foreign_key_list`, type mapping | Schema dict (same format) | Makes Spider DBs compatible with the unchanged pipeline | `backend/app/spider_eval/sqlite_schema_extractor.py:154-221` | IMPLEMENTED |
| 2 | Metadata enrichment | Schema JSON | A local LLM writes short Persian keyword descriptions for tables, columns and relations | Enriched Schema JSON | Bridges the gap between NL vocabulary and schema identifiers | `backend/enrich_schema.py:193-239` (called from `extract_schema.py:230`) | PARTIALLY IMPLEMENTED: production only; relation output unused |
| 3 | Retrieval-unit construction | Schema JSON | One text template per table, column and FK relation | `ids[]`, `documents[]` | Defines what can be retrieved | `backend/app/schema_manager.py:20-69, 188-213` | IMPLEMENTED |
| 4 | Embedding + indexing | Unit texts | Embeds with a local SentenceTransformer (L2-normalised) or OpenAI `text-embedding-3-small`, then upserts into a Chroma collection in batches of 10 | Persistent Chroma collection | Makes semantic nearest-neighbour search possible | `backend/app/utilities.py:79-168`; Spider: `spider_runner.py:68-110` | IMPLEMENTED |
| 5 | Query enhancement | Question | None. The raw question is embedded directly. Production only checks a 250-character limit. | – | – | – | PLANNED (diagram only) |
| 6 | Dense retrieval | Question | `collection.query(query_texts=[q], n_results=15)` | Top-15 unit texts + distances | Schema linking and pruning | `nl2sql_chain.py:122-158`, K at `:395` and `spider_runner.py:151,194` | IMPLEMENTED |
| 6' | BM25 / lexical retrieval | – | – | – | – | – | PLANNED |
| 6'' | RRF fusion | – | – | – | – | – | PLANNED |
| 7 | Reranking | – | – | – | – | – | PLANNED |
| 8 | Context assembly | Unit texts | Classifies each unit by the substring ` Table:` / ` Column:` / `Relation:` into three bulleted sections, keeping retrieval order | Schema context string | Gives the LLM a structured, compact schema | `nl2sql_chain.py:160-209` | IMPLEMENTED |
| 9 | Prompt + LLM | Question + context (+ feedback) | System prompt (FA/EN, normal/feedback) plus a user prompt; streaming chat completion, temperature 0.1 | Raw LLM text | SQL generation | `nl2sql_chain.py:107-120, 211-304`; `system_prompt.py` | IMPLEMENTED |
| 10 | Output cleaning | Raw text | Removes ```` ```sql ```` fences and `--` / `/* */` comments, flattens newlines, appends `;` | SQL string | Makes free-form LLM output executable | `sql_validator.py:203-233` | IMPLEMENTED |
| 11 | Static validation | SQL | Checks that the first DML token is SELECT (sqlparse) and that regex-extracted FROM/JOIN names exist in the full schema | valid? + error | Cheap automatic feedback signal | `sql_validator.py:43-136` | PARTIALLY IMPLEMENTED: column check is a no-op |
| 12 | Execution validation | SQL | Runs `text(sql)` on the SQL Server execution DB and catches the DB error | ok? + error | Catches runtime errors (bad columns, types) | `sql_validator.py:138-172`, used at `nl2sql_chain.py:470-484` | PARTIALLY IMPLEMENTED: production only |
| 13 | Automatic feedback loop | Failed SQL + error | Builds a feedback prompt from the **last** failure, switches to the feedback system prompt and regenerates | New SQL | Self-correction | `sql_validator.py:236-300`, `nl2sql_chain.py:407-506`, `spider_runner.py:190-247` | IMPLEMENTED (validation in both paths, execution in production) |
| 14 | Human semantic feedback | 👍/👎, corrected SQL, comment | Stored in PostgreSQL. If a comment is present, the frontend calls `/regenerate`, which re-runs the full pipeline with the comment in the prompt. | New SQL | Fixes semantic errors that automation cannot detect | `main.py:137-235`, `frontend/src/Scripts/Components/Message.tsx:270-320`, `index.tsx:416-460` | IMPLEMENTED (production only; not evaluated) |
| 15 | Logging | Run data | PostgreSQL table `nltosql`: run_id, thread_id, Jalali start time, latency, question, raw output, culture, schema, feedback, status, corrected_sql, comment | DB rows; `/history` endpoint | Usage log and feedback storage | `models.py`, `nl2sql_chain.py:511-529`, `main.py:87-134` | IMPLEMENTED (minimal; see §10.6) |
| 16 | Spider evaluation | dev.json + SQLite DBs | Runs inference per sample, then string EM and result-set EX | Aggregate % | Controlled benchmark | `backend/app/spider_eval/*`, `cli_spider_eval.py` | IMPLEMENTED (non-standard metrics) |

### 1.4 Behavioural differences between the two paths

| Aspect | Production `/nl2sql` | Spider evaluation |
|---|---|---|
| Schema source | `data_schema/<name>_schema.json` (enriched offline) | SQLite introspection at run time (placeholders, **not enriched**) |
| Vector store | `./chroma_db`, collection `Schema_<name>`; built only if `./chroma_db` does not exist (`main.py:32`) | `./chroma_db/spider_eval`, `Schema_spider_<db_id>`; embedded only if the collection is empty (`spider_runner.py:99`) |
| Culture / prompt language | Request field `culture` (`fa` default in the UI, from `<html lang>`) | Hard-coded `"en"` (`spider_runner.py:321`) |
| K | 15 | 15 (not a CLI flag) |
| Feedback | Always on, `max_iterations=4` | Off by default; `--feedback` or `--compare`; `--max-iter` (default 4). The programmatic default is 3 (`spider_runner.py:260`). |
| Execution feedback | If `validate_execution` (request default `False` in `schemas.py:11`; the frontend sends `true`; `/regenerate` implicitly `True`) | **None** |
| All attempts fail | SSE `on_error`, nothing stored | Returns `None`, which counts as wrong for EM and EX |
| User feedback / regenerate | Yes | No |
| Logging | PostgreSQL row per successful run | stdout only |

---

## 2. Offline Preparation Layer

### 2.1 Schema extraction

**SQL Server** (`backend/extract_schema.py`, class `SchemaExtractor`)
- **Tables:** `INFORMATION_SCHEMA.TABLES` where `TABLE_TYPE='BASE TABLE'` and `TABLE_SCHEMA='dbo'`. The description is taken from `MS_Description` if present, otherwise the placeholder `"Table <name>"` (`:38-62`). Views and non-`dbo` schemas are ignored.
- **Columns:** name, data type, nullability, PK flag (via `TABLE_CONSTRAINTS` + `KEY_COLUMN_USAGE`) and `MS_Description`, otherwise `"Column <name>"` (`:64-105`). Nullability and PK flag are read but **not written** to the JSON, except that PK columns become the table's `key_columns`.
- **Primary keys → `key_columns`:** if a table has no PK, the **first three columns** are used as `key_columns` (`:192`). This is a heuristic, not real key information.
- **Foreign keys:** from `sys.foreign_keys` and `sys.foreign_key_columns`, one relation per FK column pair. `relationship_type` is **always** `"many-to-one"` (`:133`) and is not inferred. `join_purpose` gets the placeholder "connecting A to B".
- **Type mapping:** SQL Server types are mapped to a generic vocabulary (integer, decimal, varchar, date, datetime, time, boolean) at `:138-164`.
- **Configuration:** connection details are hard-coded in `main()` (`:256-261`). The script writes `data_schema/simacnashr_schema.json`, then enriches it in place.

**SQLite / Spider** (`sqlite_schema_extractor.py`)
- Same output format. Descriptions are always placeholders: `"Table <t>"`, `"Column <c> of table <t>"`. There is the same "first three columns" fallback for tables without a PK, and all FKs are `"many-to-one"`.
- The Spider `tables.json` is **not used**. `load_spider_tables` exists (`spider_loader.py:70`) but is never called, so Spider's normalised natural-language column names (`column_names`, e.g. "singer id") are ignored.

**Data-provenance note.** The committed `backend/data_schema/simacnashr_schema.json` actually contains **`"database_name": "Team10BookShop"`**: 9 tables, 61 columns, 3 relations, 73 retrieval units. The file name says SimacNashr but the content is the BookShop DB. The latest commit also changed the enrichment model from `gemma4:e4b` to `gemma3:4b`, so it is not recorded which model produced the committed descriptions. Record the database and enrichment model used for any production-side example on a slide.

### 2.2 Schema JSON representation

```json
{
  "database_name": "...", "description": "...",
  "tables":    [{"name": "Book", "description": "<text>", "key_columns": ["BookID"]}],
  "columns":   [{"table_name": "Book", "column_name": "Title", "meaning": "<text>", "data_type": "varchar"}],
  "relations": [{"source_table": "OrderDetails", "source_column": "BookID",
                 "target_table": "Book", "target_column": "BookID",
                 "relationship_type": "many-to-one", "join_purpose": "<text>"}]
}
```
`SchemaManager.load_schema_from_json` / `load_schema_from_dict` (`schema_manager.py:80-186`) read only `name`, `description`, `key_columns`, `table_name`, `column_name`, `meaning`, `data_type` and the four relation endpoints plus `relationship_type`. They ignore `join_purpose`, `database_name` and the schema-level `description`.

### 2.3 Retrieval unit design

A **retrieval unit** is one schema element rendered as one sentence-like string. There are three unit types, stored as three kinds of document in the same Chroma collection:

| Unit type | Template (`schema_manager.py`) | Real example (BookShop, enriched) | Real example (Spider, raw) |
|---|---|---|---|
| **Table** (`table_i`) | `"{name} Table: {description}. شامل ستون های {key_columns}. "` ("includes columns …") | `Book Table: کتاب، شناسه، عنوان، نویسنده، قیمت، وضعیت. شامل ستون های BookID.` | `singer Table: Table singer. شامل ستون های Singer_ID.` |
| **Column** (`column_i`) | `"{table}.{column} Column: {meaning}, نوع داده {data_type}."` ("data type …") | `AspNetUsers.Email Column: ایمیل، آدرس الکترونیکی، شناسایی کاربر, نوع داده varchar.` | `singer.Name Column: Column Name of table singer, نوع داده varchar.` |
| **Relation** (`relation_i`) | `"Relation: {src}.{col} ↔ {tgt}.{col}. نوع رابطه {type}. "` ("relationship type …") | `Relation: OrderDetails.BookID ↔ Book.BookID. نوع رابطه many-to-one.` | `Relation: singer_in_concert.Singer_ID ↔ singer.Singer_ID. نوع رابطه many-to-one.` |

Properties that matter for the research:
- **Granularity:** fine-grained, one unit per column. A table unit lists only its *key* columns, not all of them.
- **Units are independent.** Retrieving a column does not bring in its table, and retrieving a table does not bring in its non-key columns. There is no FK-graph expansion to add missing join paths or bridge tables.
- **The glue words are always Persian** (`شامل ستون های`, `نوع داده`, `نوع رابطه`), **even for English Spider schemas**, so Spider units are mixed-language.
- **Relation units carry almost no semantics:** identifiers plus "many-to-one". The LLM-generated `join_purpose` is dropped. It was part of the template until commit `ea07602`, together with the table `business_role` and column `operations` fields.
- **No cell values or example values** are indexed.
- **No Chroma metadata** is stored (documents and ids only). Unit type and parent table can only be recovered by string matching, so metadata filters such as "only columns of table X" are impossible.
- **Unit counts:** BookShop has 73 units, so K=15 retrieves about 21 % of the schema. A replica of Spider's `concert_singer` gives 28 units (4 + 21 + 3), so K=15 retrieves about 54 %. On small Spider databases, retrieval prunes little.

### 2.4 Vector database structure

- **Engine:** ChromaDB `1.3.7`, `PersistentClient`.
- **Production:** `./chroma_db` (relative to `backend/`), one collection `Schema_<schema_name>` per schema JSON in `data_schema/`. It is built at FastAPI startup **only if the directory does not exist** (`main.py:31-33`, `utilities.py:21-76`). `create_schema_vector_store` also writes a debug dump, `backend/schema_text.txt`.
- **Spider:** `./chroma_db/spider_eval`, collection `Schema_spider_<db_id>`, populated only when empty.
- **Index:** Chroma default HNSW. No distance space is configured, so Chroma's default (squared L2) applies. With unit-normalised vectors, squared L2 equals 2·(1 − cos), so ranking is **equivalent to cosine similarity**.
- **Lifecycle caveat:** changing the schema JSON, the unit template or the embedding model does **not** re-embed existing collections. The Chroma directory must be deleted manually, otherwise experiments silently run on stale vectors (§10.7).

---

## 3. Metadata Enrichment

**Status: PARTIALLY IMPLEMENTED.** It is implemented as an offline step in the SQL Server path. It is not integrated into Spider evaluation, and the relation part of its output is unused.

| Item | Finding |
|---|---|
| Model | Ollama, `gemma3:4b` (`enrich_schema.py:17`; `gemma4:e4b` before the latest commit), host `http://127.0.0.1:11434`, temperature 0.1, `think=False` |
| Invocation | Automatically at the end of `extract_schema.py` (`:230`), or standalone: `python enrich_schema.py <schema.json> [out.json]` |
| Language | **Persian only** ("Persian only." is a rule in every prompt) |
| Output style | **2–6 (tables) or 2–5 (columns, relations) comma-separated Persian keywords, not sentences** |
| In-context learning | **None.** All three prompts are zero-shot instruction prompts with no examples. |
| Output parsing | Regex `^\s*\**LABEL\**\s*:\s*(.+)$` (`_extract_label`, `:173`). If the label is missing, the original value is kept (a placeholder or MS_Description). |
| Calls | Sequential: one LLM call per table, then per column, then per relation. There is no batching and no caching. |

### 3.1 Prompt structure (quoted and condensed)

**Table prompt** (`enrich_schema.py:35-70`):
```
You are a database documentation expert.
Goal: Generate VERY SHORT Persian (Farsi) descriptions using keywords only (no full sentences).
Table name: {name}
Key columns: {key_columns}
Columns:
  - {col} ({type})            ← all columns of the table
Outgoing foreign-key relations:
  - {src_col} → {tgt_table}.{tgt_col}
Output exactly one lines:
DESCRIPTION: <2-6 Persian keywords about table content/purpose>
Rules: Persian only. Use keywords, NOT sentences. No long text. No punctuation except commas. Keep it minimal and compact.
```
**Column prompt** (`:92-115`) takes: the table name, the **already-enriched table description**, the column name, the data type and an "Is primary key" flag. It outputs `MEANING: <2-5 Persian keywords>`.
**Relation prompt** (`:136-157`) takes: source and target table and column, and the relationship type. It outputs `JOIN_PURPOSE: <2-5 Persian keywords>`.

### 3.2 Design properties inferred from the code

- **Hierarchical conditioning.** Tables are enriched first. The dict objects are mutated in place and the column prompt reads `table.get('description')`, so every column is described in the context of its table's enriched description. This propagates table-level semantics down to columns.
- **Structural context for tables.** The table prompt sees all column names and types and the outgoing FKs, so the LLM can infer purpose from structure (e.g. `OrderDetails` with `BookID` and `OrderID` means order line items).
- **Keyword-style output is a deliberate retrieval choice.** Short keyword lists keep each unit's embedding focused. Long prose would dilute the vector and add unrelated tokens. This is a reasonable design, but it has not been measured.
- **Existing documentation is overwritten.** `MS_Description` values are extracted but **not passed** to the enrichment prompt, and they are **replaced** by the LLM output. Human-authored comments are lost.
- **No data values.** The LLM never sees sample rows, so descriptions are inferred from identifiers alone. For cryptic names (e.g. `GateWayes`) the output is generic: `شناسه، نام، دروازه‌ها، ارتباطات، سیستم`.
- **`join_purpose` is generated but never used**, because `Relation.to_embedding_text` does not include it and `SchemaManager` does not load it.

### 3.3 How enrichment affects retrieval

The enrichment text is concatenated into the table and column unit strings (`description` and `meaning`). It therefore changes **both** the embedding vectors used for retrieval **and** the schema context the LLM reads. For a Persian question, a raw unit such as `AspNetUsers.Email Column: Column Email, …` has to be matched cross-lingually by the embedding model alone. The enriched unit `AspNetUsers.Email Column: ایمیل، آدرس الکترونیکی، شناسایی کاربر, …` shares vocabulary with the question. This is the central research motivation for enrichment in this project: **cross-lingual and semantic bridging between Persian user vocabulary and English or abbreviated identifiers.**

### 3.4 Why in-context examples would help (currently not used, so PLANNED or future work)

A few curated examples of "(table/column signature) → ideal keyword description" would:
- stabilise the output format and granularity,
- teach domain conventions (e.g. `*ID` → identifier, `Is*` → boolean status, `*Date` → temporal filter),
- reduce generic outputs for cryptic names,
- make descriptions consistent across tables. This matters because retrieval compares units with each other.

This is a legitimate, low-cost extension. Do not describe it as implemented.

### 3.5 Implication for the Spider experiments

To run "Raw vs Enriched" on Spider, three changes are needed:
- (a) call `enrich_schema(schema_dict)` inside `spider_runner.py`, after `SQLiteSchemaExtractor.extract()`,
- (b) decide the enrichment language. English matches Spider questions. Persian keeps the method identical to production but tests cross-lingual robustness.
- (c) cache the enriched JSON per `db_id`, so that the LLM's non-determinism does not change descriptions between runs.

The enrichment function works on plain dicts and is compatible with the Spider schema dict format.

---

## 4. Embedding

| Item | Finding |
|---|---|
| Selection | Env var `USE_LOCAL_EMBEDDING` (`dotenv.py`) |
| Local | `LocalSTEmbeddingFunction` (`utilities.py:147-168`): `SentenceTransformer(EMBEDDING_MODEL_DIR, local_files_only=True, device="cpu")`, fully offline, CPU |
| Local model identity | Printed label `"google/embeddinggemma-300m"` (`utilities.py:15`, misleadingly named `OLLAMA_EMBEDDING_MODEL_NAME`). **The model actually loaded is whatever is in `EMBEDDING_MODEL_DIR`, which is not recorded in the repo.** Confirm it before claiming the model on a slide. |
| Online | Chroma `OpenAIEmbeddingFunction`, model `text-embedding-3-small` (`utilities.py:16`) |
| Dimension | Not set in code. According to the model cards: EmbeddingGemma-300m outputs 768-d (Matryoshka truncation to 512/256/128 is possible but unused), and text-embedding-3-small outputs 1536-d. |
| Normalisation | Local: `normalize_embeddings=True` (L2). OpenAI embeddings are unit-length by the provider. |
| Input text | The unit strings of §2.3 for documents, and the **raw question** for queries |
| Query vs document encoding | **Symmetric.** The same function and the same `encode()` call are used for both, and no `prompt_name` is passed. EmbeddingGemma's model card recommends asymmetric task prompts (e.g. `task: search result \| query: …` vs `title: none \| text: …`, applied by `encode_query` / `encode_document` in sentence-transformers). They are not applied here unless the local model config sets a default prompt. This is a low-effort improvement to test. |
| Batching | Offline upsert batches of 10 (`utilities.py:97`, `spider_runner.py:73`) |
| Chroma usage | `get_or_create_collection(name, embedding_function=ef)` + `upsert(ids, documents)`; retrieval via `get_collection(...).query(query_texts=[q], n_results=K)` |

**Research implication.** Schema linking means mapping phrases in the question to schema elements. Pure string matching fails when:
- the user's words differ from the identifiers ("how many customers" vs `AspNetUsers`),
- the question and the schema are in different languages (Persian vs English),
- identifiers are abbreviated or misspelled (`GateWayes`).

A multilingual dense encoder maps paraphrases and translations close together, so a question can retrieve a unit it shares no token with. The enrichment text strengthens this by putting Persian vocabulary inside each unit. The known weakness of dense retrieval is **exact-term matching** (rare identifiers, codes, literal values), which is the standard argument for adding BM25 (§13).

---

## 5. Retrieval

### 5.1 Exact current configuration (IMPLEMENTED)

| Parameter | Value | Location |
|---|---|---|
| Method | Dense kNN only (Chroma HNSW) | `nl2sql_chain.py:143` |
| Query | Raw question string, embedded with the same model as the documents | `:143` |
| Similarity | Chroma default space (squared L2 on unit vectors, equivalent to cosine ranking) | collection creation, `utilities.py:125`, `spider_runner.py:91` |
| K | **15** (method default 10 is unused) | `nl2sql_chain.py:395`; `spider_runner.py:151, 194` |
| Threshold | **None.** `# if dist < 1:` is commented out (EXPERIMENTAL / disabled). | `nl2sql_chain.py:154` |
| Filtering | None (no `where`, no type quotas, no per-table caps) | – |
| Distances | Returned but **discarded**. They are not in the prompt, not logged, and not used for ranking decisions. | `:158`, callers ignore them |
| Post-processing | Grouped by unit type into Tables / Columns / Relations, preserving rank order within groups | `:160-209` |
| Empty result | Production: SSE `on_error`. Spider: `None` (counted as wrong). | `:397-404`, `spider_runner.py:160-163` |

If K exceeds the collection size, Chroma returns all units, so the whole schema is included.

### 5.2 Not implemented (PLANNED): BM25, RRF, reranking, query enhancement

- **BM25:** no corpus tokenisation, no `rank_bm25` or other lexical index. `scikit-learn` is in `requirements.txt` but unused.
- **RRF:** no fusion code.
- **Reranker:** no cross-encoder or LLM reranker. The design doc's planned setting is Dense Top-20 + BM25 Top-20, a pool of 40, reranked to Top-10.
- **Query enhancement:** no rewriting, translation, decomposition or keyword extraction.

The planned design is plausible and well motivated, but none of it can be presented as implemented.

---

## 6. Query-to-Schema Matching (the core research problem)

**Problem.** Given a question q and a schema S = {tables ∪ columns ∪ FK relations}, select the minimal subset S_q that is sufficient to write the correct SQL, and present it so that the LLM uses the right elements and joins.

The architecture approximates S_q by the top-K nearest units to q. Each mismatch type below is tied to evidence in the code. Examples marked *illustrative* were built from the templates and are **not** logged retrieval results.

| Mismatch type | How it appears in this architecture | Evidence / mechanism |
|---|---|---|
| **Lexical mismatch** | User words ≠ identifier tokens ("users" vs `AspNetUsers`, "price" vs `UnitPrice`) | Dense encoder plus enriched keywords are the only bridge; there is no lexical channel |
| **Cross-lingual mismatch** | Persian question vs English identifiers (the production default is `culture="fa"`) | Enrichment prompts are Persian-only precisely to close this gap (`enrich_schema.py`) |
| **Semantic mismatch** | "Best-selling" means an aggregate over `OrderDetails` quantity; no unit says "sales" | Keyword enrichment of `OrderDetails` ("جزئیات سفارش، شناسه، کتاب، قیمت") partly helps; no value or statistics context |
| **Ambiguous column names** | `Name`, `Id`, `Year`, `Stadium_ID` appear in several tables | Every column unit is prefixed `table.column`, which disambiguates the *identity*, but the retrieval score may still favour the wrong table's `Name` |
| **Value grounding** | "singers from France" needs `singer.Country`, but "France" appears in no unit | No values are indexed (§2.3); the model must infer the column from semantics only |
| **Missing schema context** | A retrieved column's table unit, or other needed columns, fall outside Top-K | Units are independent and there is no expansion; the prompt rule "Do not invent tables or columns" then forces the LLM to guess or fail |
| **Multi-table / join ambiguity** | A question spans a bridge table (many-to-many), e.g. singer ↔ singer_in_concert ↔ concert | Relation units are near-content-free (identifiers + "many-to-one"), so they are unlikely to rank high for NL questions. `join_purpose` is unused. No FK-path completion. |

*Illustrative rendering* (produced by running the real `build_schema_context` / `build_user_prompt` on a replica of Spider `concert_singer`, with a **hand-picked** subset standing in for a partial retrieval). The question "What is the name of the singer who performed in the most concerts?" requires `singer_in_concert` and both of its relations. The prompt would contain `singer`, `concert`, `singer.Name` and only one of the two relations:
```
Tables:
  - singer Table: Table singer. شامل ستون های Singer_ID.
  - concert Table: Table concert. شامل ستون های concert_ID.
Columns:
  - concert.concert_Name Column: Column concert_Name of table concert, نوع داده varchar.
  - singer.Name Column: Column Name of table singer, نوع داده varchar.
Relations:
  - Relation: singer_in_concert.concert_ID ↔ concert.concert_ID. نوع رابطه many-to-one.
```
The LLM has to infer the missing `singer_in_concert.Singer_ID ↔ singer.Singer_ID` link. This failure mode is architectural, which makes it a good slide, **as long as it is labelled as illustrative until measured.**

---

## 7. LLM Generation

### 7.1 Models and parameters (IMPLEMENTED)

| Setting | Local (`USE_LOCAL_LLM=true`) | Online (`USE_LOCAL_LLM=false`) |
|---|---|---|
| Client | `ollama.AsyncClient` | `openai.AsyncOpenAI` |
| Model | `gemma4:12b` (Ollama tag as configured, `nl2sql_chain.py:42`) | `gpt-4o-mini` (`:301`) |
| Endpoint | `http://ai.ig.local:11434` (internal GPU server) | OpenAI API |
| Temperature | 0.1 | 0.1 |
| Max tokens | not set | not set |
| Seed / top_p / num_ctx | not set. Ollama's default context window applies. Check it if K grows, because Ollama truncates long prompts. | not set |
| Reasoning | `think=False` | – |
| Streaming | yes (tokens forwarded as SSE `on_stream`) | yes |

The model names are hard-coded, so changing the model is a code edit; only local vs online is an env switch. A third provider (GapGPT → `gemini-2.5-flash`) was added in commit `6330d33` and later removed. Only the unused `GAPGPT_API_KEY` env variable remains (EXPERIMENTAL / legacy).

### 7.2 Prompt structure

Each call is **single-turn**: `[system, user]`. There is no conversation memory and no few-shot examples.

**System prompts** (`app/system_prompt.py`), four variants:
- `SYSTEM_PROMPT_NL2SQL_FA`: Persian. `[ROLE]` "You are a **T-SQL** expert…", `[INPUT]`, `[CRITICAL RULES]` (use only schema tables/columns/relations, invent nothing, infer JOINs from schema, standard executable SQL, use aggregates properly, WHERE filters, DATE functions), `[OUTPUT FORMAT]` `SELECT… FROM… WHERE…`, no explanation, **put SQL inside a ```` ```sql ```` block**.
- `SYSTEM_PROMPT_NL2SQL_EN`: the same rules in English, **generic SQL** (no dialect named; SQLite is never mentioned for Spider), and no code-block instruction.
- `SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA` / `_EN`: "You are correcting a previous query that failed". Read the error, output only corrected SQL, check spelling of tables and columns, verify JOINs, qualify ambiguous columns with aliases.
- The rule lists start at "2." because rule 1 is missing. This is cosmetic.

Switching the culture changes three things at once: the prompt language, the **SQL dialect instruction** (T-SQL vs generic) and the code-block instruction. Treat these as confounded if culture is ever an experimental variable.

**User prompt** (`build_user_prompt`, `nl2sql_chain.py:211-258`):
```
[User feedback that you should fix it: <comment>]        ← only when /regenerate is used
User Question:
<question>

Available Database Schema:
Tables:
  - <table unit text>
Columns:
  - <column unit text>
Relations:
  - <relation unit text>

Rules:                         (Persian equivalent when culture=fa)
- Use only provided schema
- Do not invent tables or columns
- Output SQL only

SQL Query:
```
Feedback iterations use a different layout (§8). The retrieved units are pasted verbatim, including the Persian glue words and data types, grouped by type. **Distances, full column lists, sample values and DDL formatting are absent.**

### 7.3 Output handling

`clean_sql_output` removes Markdown fences and comments, collapses newlines and tabs to spaces, and appends `;` (`sql_validator.py:203-233`). It does not extract SQL from surrounding prose, so an explanation sentence before the SQL would survive and then fail. Production stores `full_sql`, the **raw** LLM text of the successful attempt (fences included), not the cleaned SQL (`nl2sql_chain.py:521`).

---

## 8. Feedback Loop

### 8.1 Mechanisms

| | Mechanism | Detects | Sent back to LLM | Paths | Status |
|---|---|---|---|---|---|
| **A** | Automatic validation feedback | Empty SQL; first DML keyword ≠ SELECT; a FROM/JOIN name not in the full schema | Last failed SQL + error + canned hint | Production + Spider (`--feedback`) | IMPLEMENTED (weak detector, §9) |
| **B** | SQL execution feedback | Any DB runtime error (unknown column, type error, syntax error from the engine) | Last failed SQL + DB error message + hint chosen by keyword ("does not exist" / "syntax error" / "ambiguous") | **Production only** (SQL Server `ExecutionDB`) | PARTIALLY IMPLEMENTED |
| **C** | User semantic feedback | Human judgement: 👍 (`feedback=1`) or 👎 (`feedback=-1`) + **mandatory corrected SQL** + optional comment | Only the **comment**, injected as "User feedback that you should fix it: …" | Production UI → `/feedback` → `/regenerate` | IMPLEMENTED (not evaluated) |
| **D** | Regeneration | Triggered by A or B (automatic, inside the loop) or by C (`/regenerate`) | See above | Both | IMPLEMENTED |

### 8.2 Loop semantics (A/B), from `nl2sql_chain.py:407-506` and `sql_validator.py:236-300`

1. `max_iterations` counts **total attempts**, not retries (`should_continue: len(history) < max`). Production: 4 attempts, i.e. 1 initial + up to 3 corrections. Spider CLI: `--max-iter N`, default 4. `--max-iter 1` is effectively single-pass with validation gating, and `--max-iter 2` is a single retry.
2. Each attempt runs clean → `validate_query` → (optional) execute. On failure, the history gets `(sql, error, success=False)` and the SSE emits `on_retry`. The streamed tokens of the failed attempt were already shown and are cleared by the frontend.
3. **What changes between iterations:**
   - the system prompt switches to the FEEDBACK variant,
   - the user prompt becomes:
     ```
     Syntax error you should fix:
     Previous attempt failed (Iteration n):
     SQL: <last failed SQL>
     SQL execution failed:
     Error: <error>
     Please regenerate the SQL query fixing the following:
     - <hint lines>
     Generate corrected SQL query:

     User Question: <question>
     <same schema context>
     Generate corrected SQL query:
     ```
   - The labels "Syntax error" and "SQL execution failed" are used for **every** error type, including schema-validation errors.
4. **What does not change:**
   - The retrieved schema context. **Retrieval is not re-run**, so an error caused by a missing table or column in the context cannot be repaired from new schema information.
   - Only the **last** failure is shown. Earlier failed attempts are forgotten, which allows oscillation between two wrong queries.
   - The Rules block disappears in feedback iterations.
5. **When all attempts fail:** production emits `on_error` "Failed to generate a valid SQL query after N attempt(s). Last error: …" and stores nothing. Spider returns `None`, which counts as incorrect for EM and EX.
6. **User semantic feedback (C/D) in detail:**
   - The frontend requires corrected SQL for a 👎 (`Message.tsx:280-283`).
   - A regeneration is triggered only if a comment was entered (`:304-308`).
   - `/regenerate` (`main.py:196-235`) reloads the original question, schema and culture, and re-runs the **whole** pipeline with `user_semantic_feedback`: new retrieval (identical question, so identical units) and the feedback loop with `validate_execution` defaulting to True.
   - The **previous SQL is not shown to the LLM, and the user's corrected SQL is not used**. The model gets only the comment, without the query it refers to.
   - The corrected SQL is stored (`status='corrected'`) but never read back. It could become a few-shot memory or a fine-tuning set (PLANNED / possible future work).

### 8.3 Why the feedback variable is subtle on Spider

In Spider evaluation only mechanism A exists. Because the detector is weak, three things follow:
- (i) Real errors, such as a wrong column, a wrong join or broken syntax, are mostly **not** detected, so the loop rarely fires.
- (ii) False positives (a column named `*_from`, `EXTRACT(... FROM col)`, §9) can force regeneration of a *correct* query, or turn it into `None` after N failures.
- (iii) Single-pass mode evaluates whatever SQL was produced, but feedback mode can return `None`.

A small "feedback delta" from `--compare` would therefore mostly measure validator precision and sampling noise, not the value of iterative correction. Adding SQLite execution feedback (mechanism B) to the Spider runner is the key step for a credible feedback experiment.

---

## 9. SQL Validation

### 9.1 Levels

| Level | Implementation | What it really checks | Status |
|---|---|---|---|
| 0. Cleaning | `clean_sql_output` | Formatting only | IMPLEMENTED |
| 1. "Syntax" | `validate_syntax` (`sql_validator.py:43-75`) using `sqlparse` | Non-empty; **if** the first token is a DML keyword it must be SELECT. `sqlparse` is a non-validating tokenizer, so real syntax errors pass. | IMPLEMENTED, but nominal |
| 2. Schema | `validate_schema_elements` (`:77-114`) | Regex `(?:from\|join)\s+([a-z_][a-z0-9_]*)` on the lowercased SQL; each captured name must be a table in the **full** schema, not only the retrieved subset. The column check (`:105-112`) is a **no-op loop**. | PARTIALLY IMPLEMENTED |
| 3. Execution | `execute_and_validate` (`:138-172`) | Runs on SQL Server via `ExecutionDB`; any `SQLAlchemyError` becomes feedback. The session is never committed. | PARTIALLY IMPLEMENTED (production only, flag-controlled) |
| 4. Semantic | – | No automatic semantic check (result plausibility, LLM self-verification, question/SQL consistency). Only the human feedback of §8. | PLANNED / future work |

### 9.2 Empirical probe (I executed the real `SQLValidator` against a two-table schema)

| Input | Result | Interpretation |
|---|---|---|
| `SELEC * FRM singer` | valid | Syntax errors are not detected |
| `SELECT name FROM singer WHERE` | valid | Incomplete SQL is accepted |
| `hello world` | valid | Non-SQL is accepted |
| `SELECT * FROM singers` | invalid: "Table 'singers' does not exist" | The table check works (true positive) |
| `SELECT nonexistent_col FROM singer` | valid | Column hallucination is not detected |
| `SELECT valid_from FROM singer` | invalid: "Table 'from'…" | False positive (no word boundary in the regex) |
| `SELECT EXTRACT(YEAR FROM birth_date) FROM singer` | invalid: "Table 'birth_date'…" | False positive |
| `DELETE FROM singer` | invalid: "Only SELECT…" | Read-only guard works for a leading DML keyword |
| `WITH x AS (SELECT 1) DELETE FROM singer` | valid | Read-only guard is bypassed through a CTE |
| `SELECT 1; DROP TABLE singer` | valid | Only the first statement is checked |

### 9.3 What the framework considers "valid SQL"

"Valid SQL" means **non-empty, not led by a non-SELECT DML keyword, and every identifier after FROM/JOIN is a known table name**. With `validate_execution=true` in production, it must additionally **execute without error on the execution database**. Validity implies neither syntactic correctness (without execution) nor semantic correctness.

Security note (outside the research scope): the read-only guard can be bypassed (CTE, multi-statement). The production execution database should be accessed with a **read-only DB login**.

---

## 10. Evaluation / Spider

### 10.1 Integration (IMPLEMENTED)

- **Entry point:** `python cli_spider_eval.py --spider_path <dir> [--limit N] [--feedback | --compare] [--max-iter N] [--quiet]`. VS Code launch configs exist for single-pass, feedback and compare modes (`.vscode/launch.json`, default limit 20).
- **Expected layout:** `<spider>/dev.json`, `<spider>/tables.json`, `<spider>/database/<db_id>/<db_id>.sqlite`. The Spider data is git-ignored (`*/spider/`).
- **Splits:**
  - **Only `dev.json`** is used: `question`, `query` (gold), `db_id`. The dev set has 1,034 questions over 20 databases.
  - **train** is unused. There are no few-shot examples and no fine-tuning.
  - **test** is unused.
  - `tables.json` is loadable but unused.
- **Per sample:**
  1. Resolve the SQLite path.
  2. On the first visit to a `db_id`: extract the schema, build or reuse the Chroma collection `Schema_spider_<db_id>`, and build an `NL2SQLChain` (culture `en`) with the shared Chroma client and embedding function injected.
  3. Run inference, single-pass (`_infer_sql`) or with validation feedback (`_infer_sql_with_feedback`).
  4. Compute EM and EX.
- **Skips:** if a SQLite file is missing or schema building throws, the sample is **skipped and not counted** in `total` (`spider_runner.py:296-335`). If inference returns nothing, the sample **is** counted as wrong.

### 10.2 Exact Match (as implemented, `spider_evaluator.py:17-56`)

EM = lowercase, whitespace collapse, strip one trailing `;`, then string equality. This is **not** Spider's official EM, which parses both queries into clause components, compares them as sets, and by default ignores literal values. Aliases (`T1`/`T2` in gold), column order, spacing inside parentheses and quote style all break the implemented EM. Expect values **far below** published EM, and do not compare them with the literature.

### 10.3 Execution Accuracy (as implemented, `spider_sqlite_executor.py`)

Both queries run on the same SQLite file. The gold query fails → False; the prediction fails → False. Rows are compared after converting every value to `str(v).strip().lower()` and **sorting**. This is multiset equality with column order preserved.

Differences from the official test-suite EX:
- Order is ignored even for `ORDER BY` queries.
- There is no alternative-database test suite, so spurious matches on a single database are possible.
- There are no timeouts, so a runaway query can hang the run.
- String conversion may flag `1` vs `1.0` as different.

### 10.4 Gold vs predicted SQL

The gold SQL is used **only** for EM and EX. It never enters prompts, retrieval or validation.

### 10.5 Leakage and validity assessment

| Risk | Present? | Notes |
|---|---|---|
| Gold SQL in the prompt | **No** | – |
| Schema derived from gold | **No** | The schema comes from the SQLite file |
| Few-shot examples from dev | **No** | – |
| Execution feedback compared with gold results | **No** | There is no execution feedback in eval. Keep it that way: if added, feedback must use only the prediction's own execution error or result, never the gold result. |
| Tuning on the same split used for reporting | **Yes (methodological)** | Prompts, K and so on are developed on dev and reported on dev. Mitigation: hold out part of dev, or use a train subset for tuning, or the official test split if available. |
| Pretraining contamination | *Possible (hypothesis)* | Spider has been public since 2018. gpt-4o-mini and Gemma may have seen it. This is a known limitation of all LLM-on-Spider results; mention it. |
| Biased subsets | **Yes, if `--limit` is used** | `dev.json` is grouped by database (it starts with `concert_singer`), so `--limit 20` evaluates essentially **one** database. Use a stratified or random sample, or the full dev set. |
| Stale vector stores across experiments | **Yes** | Collections are only built when empty. Changing the embedding model or unit template without deleting `chroma_db/spider_eval` reuses old vectors. Depending on Chroma's embedding-function conflict checks, collection loading may instead fail, and that database's samples are then **silently skipped and not counted**. |
| Evaluation DB mutation | *Low probability, real* | In single-pass mode nothing blocks a predicted DML statement. The executor uses `with sqlite3.connect(...) as conn`, which **commits** on success, so a `DELETE` would persist. It also switches the files to WAL journal mode. Keep a pristine copy of `database/`, or open SQLite read-only (`file:...?mode=ro`). |
| Non-determinism | **Yes** | Temperature 0.1 with no seed. Single-pass vs feedback runs are separate samples, so part of the delta is noise. Use T=0 and/or repeated runs and paired statistics. |

### 10.6 Logging and experiment tracking

- **Production:** one PostgreSQL row per *successful* run (question, raw output, latency, culture, schema, feedback fields). Failures, retrieved units, distances, iteration counts, errors, model name, prompt and token usage are **not** logged.
- **Spider:** stdout only. Per sample it prints `[i/N] STATUS db=<id> | Q: <first 60 chars>`, plus aggregates. **Predicted SQL is not printed or saved**, and no configuration snapshot is recorded.
- **Consequence:** the design document's metrics "Average Tokens Used", "Syntax Error Rate" and "Semantic Error Rate" are **not measurable** with the current code (PLANNED).

### 10.7 Reproducibility notes

- Importing `app.nl2sql_chain` creates SQLAlchemy async engines from `EXECUTION_DATABASE_URL` and `MAIN_DATABASE_URL` at import time. The Spider CLI therefore needs both env variables set to valid URLs, even though it never uses those databases.
- The LLM and embedding model identity comes from hard-coded names plus env variables. Record them manually for every reported run.

---

## 11. Experimental Variables

| Variable | Baseline | Proposed | Implemented? | Config location |
|---|---|---|---|---|
| LLM provider | Online `gpt-4o-mini` | Local Ollama `gemma4:12b` (or vice versa) | **Yes** (env switch) | `USE_LOCAL_LLM`; names at `nl2sql_chain.py:42, 301` |
| LLM temperature | 0.1 | 0 for evaluation | Fixed, code edit needed | `nl2sql_chain.py:41, 301` |
| Max tokens / seed | not set | fixed for reproducibility | **No** | – |
| Embedding model | OpenAI `text-embedding-3-small` | Local SentenceTransformer (labelled EmbeddingGemma-300m) | **Yes** (env switch; Chroma dir must be rebuilt) | `USE_LOCAL_EMBEDDING`, `EMBEDDING_MODEL_DIR`; `utilities.py:15-16` |
| Query/document embedding prompts | none (symmetric) | model-specific asymmetric prompts | **No** | `utilities.py:163-168` |
| Retrieval strategy | Full schema in prompt (no retrieval) | Dense Schema-RAG | Dense: **Yes**. Full-schema baseline: **No** (would need a bypass flag). | `nl2sql_chain.py:122-209` |
| Retrieval K | – | 5 / 10 / 15 / 20 / all | **Hard-coded 15**, no CLI flag | `nl2sql_chain.py:395`; `spider_runner.py:151, 194` |
| Relevance threshold | none | distance cut-off | **Disabled** (commented out) | `nl2sql_chain.py:154` |
| BM25 lexical retrieval | – | BM25 Top-20 | **No** (PLANNED) | – |
| Dense + BM25 fusion (RRF) | – | RRF over both lists | **No** (PLANNED) | – |
| Reranker | – | Cross-encoder on a pool of 40 → Top-10 | **No** (PLANNED) | – |
| Query enhancement | raw question | rewrite / translate / decompose | **No** (PLANNED) | – |
| Retrieval-unit design | table + column + relation units | + FK-path expansion, + values, + `join_purpose` | Base: **Yes**. Extensions: **No**. | `schema_manager.py` |
| Metadata enrichment | Raw placeholders | LLM Persian keyword descriptions | Production: **Yes** (offline). Spider: **No**. | `enrich_schema.py`; would hook in at `spider_runner.py:307-309` |
| Enrichment model / language | – | `gemma3:4b`, Persian | Fixed in code | `enrich_schema.py:16-18` |
| Enrichment ICL examples | zero-shot | few-shot | **No** | `enrich_schema.py:35-157` |
| Validation feedback | single-pass | iterative (N attempts) | **Yes** on Spider | CLI `--feedback`, `--compare`, `--max-iter` |
| Number of feedback iterations | 1 (no feedback) | 2 (single retry) / 4 (iterative) | **Yes** | `--max-iter`; production `nl2sql_chain.py:408` |
| Execution feedback | off | on | Production: **Yes** (`validate_execution`). Spider: **No**. | `schemas.py:11`, `frontend/src/Scripts/config.ts` |
| Retrieval re-run inside feedback | no | re-retrieve using the error | **No** | – |
| User semantic feedback | none | comment-driven regeneration | Production: **Yes**. Evaluation: **No**. | `/feedback`, `/regenerate` |
| Prompt language / culture | `en` | `fa` | **Yes** (request field; Spider fixed `en`) | `schemas.py`, `system_prompt.py` |
| Prompt configuration (rules, format, dialect) | current prompts | e.g. SQLite dialect hint, DDL-style context, few-shot | Only one fixed variant per language | `system_prompt.py`, `nl2sql_chain.py:211-258` |
| Evaluation subset | full dev | – | **Yes** (`--limit`, first N only) | `cli_spider_eval.py` |
| EM / EX definition | string EM, sorted-row EX | official Spider EM + test-suite EX | Custom only | `spider_evaluator.py`, `spider_sqlite_executor.py` |

---

## 12. Research Contribution (strictly implementation-based)

The components below exist in code. None is novel *merely because it exists*. Schema linking and pruning, schema-description augmentation and self-correction loops all have prior art; related-work examples to position against include DIN-SQL, RESDSQL, C3, CHESS and execution-guided decoding (verify the citations). The defensible contribution is the specific **combination, the setting (Persian enterprise databases, local models) and the controlled ablation**, not any single mechanism.

### C1: Typed schema-unit retrieval (Schema-RAG). Status: IMPLEMENTED

- **Problem:** real schemas are too large, noisy or costly to include fully in every prompt.
- **Limitation of straightforward approaches:** full-schema prompting scales poorly and distracts the LLM. Generic text-chunk RAG ignores schema structure.
- **Proposed modification:** split the schema into typed units (table, column, FK relation), each a short self-contained sentence. Embed them, retrieve the Top-K per question, and reassemble them into a typed context (Tables / Columns / Relations).
- **Expected mechanism:** higher signal-to-noise context, fewer hallucinated identifiers, lower token cost.
- **Experimental variables:** full schema vs Schema-RAG; K ∈ {5, 10, 15, 20}.
- **Metrics:** EX; schema-linking recall@K of gold tables and columns (computable from Spider's parsed `sql` field in `dev.json`); prompt tokens.
- **Caveat:** Spider databases are small, so the benefit may appear only on larger schemas, such as the production database or a large-schema benchmark.

### C2: Hierarchical, keyword-style LLM metadata enrichment for (cross-lingual) schema linking. Status: PARTIALLY IMPLEMENTED

- **Problem:** Persian (or lay-English) questions vs English, abbreviated or cryptic identifiers.
- **Limitation:** raw identifiers give weak semantic and cross-lingual anchors for dense retrieval, and DB comments are usually missing.
- **Proposed modification:** an offline zero-shot LLM generates compact Persian keyword descriptions. Tables are described from their structure; columns are described conditioned on the enriched table description. The descriptions are embedded inside the units.
- **Expected mechanism:** shared vocabulary between question and unit, giving better retrieval ranking and a more informative context for the LLM.
- **Experimental variables:** raw vs enriched; optionally the enrichment language (EN vs FA) and zero-shot vs few-shot enrichment.
- **Metrics:** recall@K and EX.
- **Missing piece:** needs Spider integration, and for the cross-lingual claim a Persian question set (e.g. a translated Spider-dev subset or an in-house Persian set over the production DB).

### C3: Validation-driven iterative self-correction. Status: IMPLEMENTED (with a weak validator)

- **Problem:** single-shot generation produces invalid SQL.
- **Limitation:** no recovery path.
- **Proposed modification:** a bounded loop. On failure, the failed SQL and the diagnostic are fed back with a correction-specific system prompt.
- **Expected mechanism:** fixes surface errors such as wrong table names and non-SELECT output.
- **Experimental variable:** `--max-iter` ∈ {1, 2, 4}.
- **Metrics:** EX, retry rate, fix rate per iteration.
- **Honest limitation:** the detector catches few errors (§9), so the expected effect is small until mechanism B is added.

### C4: Execution-guided feedback. Status: PARTIALLY IMPLEMENTED (production only)

- **Problem:** statically "valid" SQL still fails at run time (wrong columns, types).
- **Proposed modification:** execute on the target DB and feed the engine's error back.
- **Expected mechanism:** DB errors are precise and actionable.
- **Experimental variable:** static-only vs static + execution feedback on Spider SQLite. This needs a roughly 15-line addition to `_infer_sql_with_feedback`, using the prediction's own execution only.

### C5: Human-in-the-loop semantic feedback. Status: IMPLEMENTED in the product, NOT EVALUATED

- **Problem:** execution-valid SQL can be semantically wrong, and automation cannot see intent.
- **Proposed modification:** a user comment drives regeneration; corrected SQL is stored.
- **Evaluation options:**
  - a simulated-user study (an LLM critic produces the comment, without access to gold SQL);
  - an oracle upper bound (a comment derived from gold), explicitly labelled as leakage and an upper bound;
  - a small real user study on the production DB.
- Keep this as an *engineering or system contribution* unless it is evaluated.

### C6: Reproducible Spider evaluation harness around the same pipeline. Status: IMPLEMENTED

This is an engineering contribution: the pipeline is identical to production except for SSE and logging. It is valuable for methodology, but it is not research novelty. It needs official metrics to be credible.

---

## 13. Failure-Driven Research Gaps

Evidence-based means the gap follows directly from the code. Hypothesis means it is plausible but unmeasured.

| # | Gap | Type | Where | Suggested probe |
|---|---|---|---|---|
| G1 | **Fragmented context:** a column is retrieved without its table, or a join path or bridge table is missing | Evidence-based (no expansion logic) | `build_schema_context` | Measure gold-table/column recall@K; add FK-path completion |
| G2 | **Relation units are semantically empty**, so join information is under-retrieved | Evidence-based (template) + hypothesis (effect) | `Relation.to_embedding_text`; `join_purpose` unused | Include `join_purpose`; measure relation recall on multi-table questions |
| G3 | **Dense-only retrieval misses exact identifiers and literal values** | Hypothesis (standard IR finding) | Retrieval | Dense vs BM25 vs hybrid (after implementing) |
| G4 | **Lexical retrieval would fail cross-lingually** (Persian question vs English identifiers) unless units contain Persian text | Hypothesis | Motivates the combination of enrichment and BM25 | BM25 on raw vs enriched units with Persian questions |
| G5 | **Fixed K ignores schema size** (54 % of a small Spider DB vs 21 % of BookShop) | Evidence-based | K=15 constant | K sweep; relative K or a score threshold |
| G6 | **Too many units add noise; too few lose recall** | Hypothesis | K | Plot EX vs K together with recall@K |
| G7 | **Mixed-language unit templates** (Persian glue words in English units) | Evidence-based (template) + hypothesis (small effect) | `schema_manager.py` | Language-matched templates, ablation |
| G8 | **No value grounding** (no cell values or examples indexed) | Evidence-based | Offline layer | Add sampled distinct values to column units |
| G9 | **Validator misses most errors and has false positives** | Evidence-based (empirical probe) | `sql_validator.py` | Replace with `sqlglot` parsing, SQLite `EXPLAIN`, or execution |
| G10 | **Feedback cannot repair retrieval misses** (context is fixed across iterations) | Evidence-based | Loop design | Error-conditioned re-retrieval |
| G11 | **Only the last failure is in the feedback prompt**, which risks oscillation | Evidence-based | `get_feedback_prompt` | Include the full attempt history |
| G12 | **Execution-valid ≠ semantically correct** | Evidence-based (no semantic check) | – | EX minus "executes without error" rate; LLM self-verification |
| G13 | **Dialect not specified for Spider** (EN prompt says "standard SQL"; FA prompt says T-SQL) | Evidence-based + hypothesis (effect) | `system_prompt.py` | Add a "SQLite" instruction; count dialect errors |
| G14 | **Regeneration ignores the previous SQL and the user's corrected SQL** | Evidence-based | `/regenerate`, `build_user_prompt` | Include the previous SQL; reuse corrected SQL as few-shot |
| G15 | **Enrichment discards existing DB comments and sees no data** | Evidence-based | `enrich_schema.py` | Pass `MS_Description` and sample values into the prompt |
| G16 | **Complex SQL (nesting, set operations, GROUP BY/HAVING) may need iterative correction** | Hypothesis | – | Break EX down by Spider hardness level |

---

## 14. Recommended Evidence for the Presentation

### 14.1 Evidence you can show today (no new experiments)

- The **real architecture diagram**, redrawn from §1.2, with PLANNED boxes (Query Enhancement, BM25, RRF, Reranker) visually marked, e.g. dashed as "next phase".
- The **retrieval-unit templates** with real examples, raw vs enriched (§2.3).
- The **enrichment prompt** (§3.1) and a before/after for a few BookShop units: placeholder `Column Email` vs `ایمیل، آدرس الکترونیکی، شناسایی کاربر`.
- The **rendered LLM prompt** and **feedback prompt** (§6, §8.2).
- The **validator probe table** (§9.2), as motivation for the next step.
- The **feedback-loop state machine** (attempts, prompt switch, terminal failure) and the **human feedback flow** (👎 → corrected SQL + comment → `/regenerate`).
- The **evaluation harness design** (§10), including an honest "metric fidelity" note.

### 14.2 Experiments to run, per component (report only measured numbers)

**Retrieval (currently runnable only in part):**
- Full-schema vs Dense Schema-RAG (needs a bypass flag).
- Dense K ∈ {5, 10, 15, 20} (needs a `--k` flag), showing **recall@K of gold schema items** (from `dev.json`'s parsed `sql`), EX, and average prompt length.
- After implementation: Dense-only, BM25-only, Dense + BM25 (union), Dense + BM25 + RRF, Dense + BM25 + RRF + reranker, with the final context size fixed (e.g. 10).

**Metadata enrichment (needs Spider hook):**
- Raw vs enriched (EN) vs enriched (FA): recall@K and EX.
- Two or three qualitative examples of retrieved units before and after enrichment for the same question.
- For the cross-lingual claim: Persian questions (translated subset) × {raw, enriched}.

**Feedback:**
- `--max-iter` 1 / 2 / 4 with validation feedback (runnable now).
- Plus execution feedback on SQLite (needs the addition).
- Report the fraction of samples entering a retry, the fix rate per iteration, and the EX delta with a paired test (McNemar) or repeated runs.

**Error analysis** (needs saved predictions):
- A taxonomy: retrieval miss (gold item not in Top-K), join error, aggregation error, value error, dialect error, execution error, semantically wrong.
- EX broken down by Spider hardness (easy / medium / hard / extra).

**Metric fidelity:**
- Report both the repository's EM/EX and the **official** Spider EM (exact set match) and test-suite EX.
- Always state the denominator (samples evaluated vs skipped).

### 14.3 Minimal code additions before any results slide (priority order)

1. **Save a per-sample JSONL** with db_id, question, gold, pred, retrieved units + distances, iterations and errors, EM and EX. This is required for everything else.
2. **Add the official Spider evaluation** (component EM + test-suite EX), or run it offline on the saved predictions.
3. **Expose `--k`** and add a **full-schema baseline flag**. Compute schema-linking recall@K.
4. **Hook `enrich_schema` into `spider_runner`**, with a language option and per-DB caching.
5. **Add SQLite execution feedback** in `_infer_sql_with_feedback` (the prediction's own error only), and open databases read-only.
6. **Evaluation hygiene:**
   - set temperature 0 or a fixed seed,
   - use a stratified or random subset instead of the first N,
   - delete or version `chroma_db/spider_eval` per configuration,
   - record the model and embedding identifiers.
7. Only then, if time allows: BM25 (`rank_bm25`), RRF and a cross-encoder reranker.

---

## 15. Final Technical Summary

**PROJECT GOAL**
Translate natural-language questions (Persian and English) into executable SQL over relational databases. Instead of placing the whole schema in the prompt, retrieve only the relevant schema elements (Schema-RAG), and improve correctness with validation, execution and human feedback. The target setting is a Persian enterprise SQL Server database. Spider 1.0 dev (SQLite, English) is the controlled benchmark.

**BASELINE**
Implemented baseline: single-pass generation with dense Top-15 schema retrieval, raw (placeholder) schema descriptions, temperature 0.1, no feedback. This is the Spider CLI default mode. A "full schema, no retrieval" baseline is the natural reference but is **not implemented**. The design document's "Dense Only" baseline uses K=10, while the code uses 15.

**PROPOSED ARCHITECTURE**
Offline: DB → schema extraction → schema JSON → LLM metadata enrichment → per-element retrieval units → embeddings → ChromaDB.
Online: question → dense retrieval (Top-K units) → typed schema context → LLM → cleaning → validation (static, plus execution in production) → iterative feedback → final SQL, with optional human semantic feedback and regeneration.
**Implemented:** dense retrieval, enrichment (production only), validation and execution feedback (execution in production only), human feedback.
**Planned (diagram or document only):** query enhancement, BM25, RRF, reranker.

**OFFLINE PIPELINE**
- `extract_schema.py`: SQL Server `dbo` tables, columns, PKs, FKs, `MS_Description`, generic type mapping. Tables without a PK use their first three columns as `key_columns`. All FKs are labelled many-to-one.
- `enrich_schema.py`: Ollama `gemma3:4b`, temperature 0.1, zero-shot, Persian keyword descriptions. Tables are enriched first; columns are conditioned on the enriched table description; relations get a `join_purpose` that is **unused downstream**. Existing DB comments are overwritten.
- `SchemaManager`: three unit types.
  - Table: `"{T} Table: {desc}. شامل ستون های {keys}."`
  - Column: `"{T}.{C} Column: {meaning}, نوع داده {type}."`
  - Relation: `"Relation: {T1}.{c} ↔ {T2}.{c}. نوع رابطه many-to-one."`
- `utilities.py`: embeds the units with a local SentenceTransformer from `EMBEDDING_MODEL_DIR` (labelled EmbeddingGemma-300m, normalised, CPU) or OpenAI `text-embedding-3-small`. Stored in Chroma `Schema_<name>` without metadata; default distance, equivalent to cosine ranking.
- Spider path: SQLite introspection with placeholder descriptions and **no enrichment**. Collections `Schema_spider_<db_id>` are cached and never refreshed.
- The committed production schema file `simacnashr_schema.json` actually contains the Team10BookShop DB: 9 tables, 61 columns, 3 relations, 73 units.

**ONLINE PIPELINE**
`POST /nl2sql` (API key, SSE) → `LoadNL2SQLChain`:
1. Check the 250-character question limit.
2. Load the schema JSON.
3. Retrieve the dense Top-15 units.
4. Group them into Tables / Columns / Relations.
5. Build the system prompt (FA = T-SQL expert with a code-block instruction; EN = generic SQL) and the user prompt (question + schema + rules).
6. Stream LLM tokens.
7. Clean the output, then validate.
8. Optionally execute on the SQL Server execution DB.
9. On failure, feed back the last failed SQL, the error and a hint (up to 4 total attempts, same retrieved context).
10. Log successful runs to PostgreSQL.

`/feedback` stores 👍/👎, corrected SQL and a comment. `/regenerate` re-runs the pipeline with the user's comment injected; the previous SQL and the corrected SQL are not passed to the LLM.

**RETRIEVAL**
- Dense-only Chroma kNN. The query is the raw question, embedded with the same model as the documents; symmetric encoding, no task prompts.
- K=15, hard-coded in both paths. No threshold (commented out), no metadata filters, no reranking, no query enhancement.
- Distances are discarded.
- BM25, RRF and the cross-encoder reranker (planned: Dense Top-20 + BM25 Top-20, a pool of 40, reranked to Top-10) are **not implemented** anywhere in the code or the git history.

**LLM**
- Local: Ollama `gemma4:12b` at `ai.ig.local:11434`, `think=False`.
- Online: OpenAI `gpt-4o-mini`.
- Temperature 0.1 for both. No max_tokens, no seed, no num_ctx.
- Single-turn `[system, user]` messages, no few-shot examples, streaming.
- Four system prompts (FA/EN × normal/feedback).
- Output cleaning removes fences and comments and appends `;`.

**FEEDBACK**
- (A) Static validation feedback: implemented in both paths, with a weak detector.
- (B) Execution feedback: production only.
- (C) Human semantic feedback: comment-driven regeneration, production only, not evaluated.
- (D) Regeneration: `max_iterations` = total attempts (production 4; Spider `--max-iter`, default 4). Only the last failure is shown. Retrieval is not re-run.
- When all attempts fail: production returns `on_error`; Spider returns `None`, which is scored as wrong.
- Empirically, the validator accepts `SELEC * FRM x`, incomplete SQL, non-SQL and hallucinated columns. It rejects correct queries containing `EXTRACT(… FROM col)` or columns named `*_from`, and it can be bypassed with a CTE or multi-statement SQL.

**EVALUATION**
- `cli_spider_eval.py`: Spider **dev.json only** (1,034 questions / 20 DBs); train, test and tables.json are unused. Modes are single-pass, `--feedback` and `--compare`; `--limit N` takes the first N samples, which covers only about one database for small N.
- Schemas come from SQLite at run time. Culture is `en`. There is no execution feedback.
- **EM** is normalised string equality, not the official component EM.
- **EX** compares sorted, lowercased row multisets on a single database: order-insensitive, no test suite, no timeout.
- There is no gold leakage into prompts.
- Validity risks:
  - tuning and reporting on dev,
  - possible pretraining contamination,
  - stale Chroma caches, with skipped samples not counted,
  - the evaluation DB can be mutated by predicted DML (commit on the context manager),
  - non-determinism.
- Nothing is saved per sample.

**EXPERIMENTAL VARIABLES**
- Switchable now: LLM (local/online via env), embedding model (via env + rebuild), validation feedback on/off, and the number of attempts (`--max-iter`); culture in production.
- Code constants: K (15), temperature (0.1), model names, enrichment model and language.
- Missing: full-schema baseline, K flag, BM25, RRF, reranker, query enhancement, Spider enrichment, Spider execution feedback, few-shot, official metrics, token and error-rate metrics.

**IMPLEMENTED CONTRIBUTIONS**
1. Typed schema-unit dense retrieval (Schema-RAG) with a typed context layout.
2. Offline hierarchical LLM metadata enrichment (Persian keywords) for the SQL Server path.
3. Bounded validation-driven self-correction loop with a correction-specific prompt.
4. Execution-guided feedback in the production path.
5. Human-in-the-loop semantic feedback with comment-driven regeneration and corrected-SQL capture.
6. A Spider evaluation harness reusing the production pipeline, with single-pass vs feedback comparison.

All of these are system contributions. Their empirical benefit is **not yet measured** in the repository.

**PLANNED CONTRIBUTIONS**
- Hybrid retrieval: BM25 + dense with RRF, cross-encoder reranking to a fixed final context size.
- Query enhancement.
- Raw vs enriched ablation on Spider, and a cross-lingual Persian evaluation.
- Execution-guided feedback on Spider; comparison of single retry vs iterative refinement.
- Few-shot (ICL) enrichment.
- Use of `join_purpose` and FK-path expansion.
- Retrieval re-run during feedback.
- Semantic validation.
- Corrected-SQL memory.
- Token-usage, syntax-error-rate and semantic-error-rate metrics.
- Official Spider EM and test-suite EX.

**OPEN QUESTIONS**
1. Is the thesis claim about **Persian / cross-lingual enterprise NL2SQL** (where enrichment and retrieval matter most) or about **generic Spider accuracy**? The evaluation design follows from this answer.
2. Which enrichment language should be used for Spider (EN, to match the questions, or FA, to match the method)? Is a Persian question set available?
3. Which embedding model is actually in `EMBEDDING_MODEL_DIR`, and which model produced the committed enriched schema?
4. Will BM25, RRF and the reranker be implemented before the final defence? If not, the design-doc tables must be removed.
5. Does Schema-RAG beat full-schema prompting on Spider's small schemas? If not, is there a large-schema test bed (the production DB, a large-schema benchmark)?
6. What final context size and K will be used? The design doc says 10; the code uses 15.
7. Does the feedback loop help once execution feedback exists on SQLite, and how many iterations are worthwhile?
8. How will human semantic feedback be evaluated: simulated critic, oracle upper bound, or a user study?

**RECOMMENDED PRESENTATION EMPHASIS**
- Present the progress honestly as "**framework built end-to-end; experimental phase starting**". Strong points to show:
  - the working offline and online pipeline,
  - the retrieval-unit design,
  - the Persian enrichment method with before/after units,
  - the three-tier feedback design (static, execution, human),
  - the Spider harness.
- Mark BM25, RRF, reranker and query enhancement as **next-phase work**, and remove or relabel the design document's numeric tables as **hypotheses**.
- Use §6 (unit fragmentation, join ambiguity, cross-lingual mismatch) and §9.2 (validator probe) as **motivation slides** for the planned components.
- Show the concrete **experiment plan** of §14.2 and the **evaluation-fidelity fixes** of §14.3.
- Report only numbers produced by the harness, together with their exact configuration (LLM, embedding model, K, feedback mode, sample count, metric definition).

---

### Appendix A: File map

| Concern | File(s) |
|---|---|
| API, endpoints, startup | `backend/main.py`, `backend/app/schemas.py`, `backend/app/models.py`, `backend/app/dotenv.py`, `backend/.env.tempelate` |
| Orchestration, retrieval, prompts, LLM | `backend/app/nl2sql_chain.py`, `backend/app/system_prompt.py` |
| Retrieval units | `backend/app/schema_manager.py` |
| Embedding + vector store | `backend/app/utilities.py` |
| Validation + feedback loop | `backend/app/sql_validator.py` |
| Offline extraction + enrichment | `backend/extract_schema.py`, `backend/enrich_schema.py`, `backend/data_schema/simacnashr_schema.json`, `backend/schema_text.txt` (debug dump) |
| Spider evaluation | `backend/cli_spider_eval.py`, `backend/app/spider_eval/{spider_loader,sqlite_schema_extractor,spider_runner,spider_evaluator,spider_sqlite_executor}.py` |
| Frontend (chat, SSE, feedback modal, regenerate) | `frontend/src/Scripts/index.tsx`, `frontend/src/Scripts/Components/Message.tsx`, `frontend/src/Scripts/config.ts` |
| Design docs (contain planned or illustrative content) | `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md`, `docs/diagrams/*.png`, `backend/ARCHITECTURE.md` (stale), `backend/prompt.md` (codegen spec) |
