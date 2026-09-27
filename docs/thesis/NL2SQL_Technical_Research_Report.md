# NL2SQL Schema-RAG Framework: Technical and Research Report

*Input for building the 6-month thesis progress presentation. This file is not slides.*

- **Repository:** `mohammadshakouri/Nl2SQL`
- **Code state inspected:** commit `8cde135` ("Strip chatbot components; keep research/Spider evaluation core only"), 2026-09-27
- **Scope:** the entire repository (the Spider-research backend, its docs, diagrams) and the relevant git history
- **Method:** I followed the call graph from the entry point (`cli_spider_eval.py`) through `app.spider_eval.spider_runner`, `app.nl2sql_chain`, `app.sql_validator` and `app.schema_manager`. I re-ran the schema extractor, the embedding-unit builder, the validator and the prompt builder locally on a synthetic SQLite database to confirm behaviour instead of inferring it, and reinstalled `requirements.txt` and imported every remaining module to confirm nothing was left dangling by the cleanup. **No experiment was run and no accuracy number appears in this report.**

## Revision note: what changed since the previous version of this report

The first version of this report (written against commit `6e55aee`) described a repository that mixed two things: a general-purpose NL2SQL **chatbot product** (FastAPI server, React chat UI, PostgreSQL logging, a live SQL Server connection, human 👍/👎 feedback with SQL correction) and a **Spider 1 research harness** bolted on top of it for the university assignment. Per direction, the chatbot product has since been **removed in full** (commit `8cde135`) so the repository now contains only the Schema-RAG research core and its Spider evaluation harness. Concretely, this changes the *status* of several items from the previous report, and this is worth stating plainly rather than silently:

| Item | Status before cleanup | Status now | Why |
|---|---|---|---|
| SQL Server schema extraction (`extract_schema.py`) | IMPLEMENTED | **REMOVED** | Deleted with the chatbot layer; hard-coded production credentials, out of scope for Spider-only research |
| Execution-guided feedback (mechanism B, §8) | PARTIALLY IMPLEMENTED (chatbot only) | **REMOVED** | `SQLValidator.execute_and_validate` (SQLAlchemy against SQL Server) was deleted; it is not currently present anywhere in the code |
| Human-in-the-loop semantic feedback (mechanism C, §8) | IMPLEMENTED (chatbot only, not evaluated) | **REMOVED** | The `/feedback` and `/regenerate` endpoints, the corrected-SQL storage, and the frontend modal were deleted with the chatbot layer |
| Metadata enrichment (`enrich_schema.py`) | PARTIALLY IMPLEMENTED (auto-invoked by the SQL Server extractor) | **IMPLEMENTED as a standalone, disconnected CLI tool** | Its only caller (`extract_schema.py`) is gone; it still runs correctly on any schema dict, it is just not invoked automatically by anything anymore |
| Two divergent execution paths (chatbot vs Spider) | Yes — the main source of confusion in the first report | **Gone — one pipeline** | The whole repository is now just the Spider research harness |
| SQLAlchemy engines created at import time regardless of use (a reproducibility bug flagged in the first report) | Present | **Fixed** | Those engines no longer exist |
| Ollama host | `http://ai.ig.local:11434` (an internal company GPU host) | `http://127.0.0.1:11434` | Reset to a generic default now that the chatbot's infrastructure is gone |
| `requirements.txt` | 123 packages | 106 packages | 17 chatbot-only packages removed (FastAPI/uvicorn stack, SQLAlchemy/asyncpg, pyodbc, Persian-calendar libs, unused office-file libs) |

Two of the five modules described in the original Farsi proposal — module 3 ("ماژول بازیابی و غنی‌سازی", partially — the retrieval half stays, only the feedback-adjacent execution piece is gone) and module 5 ("ماژول بازخورد کاربر", the user-feedback module) — now have **no code representation at all** in this repository. That is flagged explicitly throughout this report (§8, §12 C4/C5, §15) rather than glossed over, since a thesis committee will ask why a described component is absent.

## Status legend (used throughout)

| Label | Meaning |
|---|---|
| **IMPLEMENTED** | The code exists and runs on the active execution path (the Spider harness — there is only one path now). |
| **PARTIALLY IMPLEMENTED** | The code exists but is incomplete (e.g. a check that is a no-op, a value computed but never consumed). |
| **REMOVED** | The mechanism existed in an earlier version of this repository (the chatbot layer) and has been deleted as part of the cleanup. It is not merely "planned" — it was built, then intentionally stripped for scope, and would need to be rebuilt against the Spider harness's shape if wanted again. |
| **PLANNED** | It appears only in documentation or diagrams, with no code ever having existed in the repository or its git history. |

---

## 0. Critical findings (read these first)

These findings decide what can be shown in the presentation.

1. **The repository is now a single pipeline.** There is no more chatbot/production path to confuse with the research path — `cli_spider_eval.py` is the only entry point, and `app.nl2sql_chain.NL2SQLChain` + `app.spider_eval.spider_runner` is the only orchestration. This removes an entire category of confusion from the first report, but it also means two previously-implemented mechanisms are simply gone (see the revision note above and §8).
2. **Retrieval is still dense-only.** Query Enhancement, BM25, RRF and the Reranker appear in `docs/diagrams/OnlineInference.drawio.png` and in `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md`. None of them exists in the code, and none has ever existed in the git history (confirmed again after the cleanup: `requirements.txt` still has no BM25/cross-encoder dependency, and no such code was ever committed). All four are **PLANNED**.
3. **The results tables in `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md` were not produced by this code**, and cannot have been, for three reasons that all still hold: (a) BM25 and the reranker do not exist; (b) the Spider pipeline never applies metadata enrichment; (c) this repository's Exact Match is a strict string comparison, not the official Spider EM, and would score much lower than the numbers in that table. Present those tables only as *hypotheses or expected outcomes*, clearly labelled, or remove them.
4. **Metadata enrichment (`enrich_schema.py`) is implemented but currently disconnected from the only pipeline that runs.** It was previously invoked automatically by the (now-removed) SQL Server extractor; nothing calls it today. It is a working, generic, standalone tool — `python enrich_schema.py <schema.json>` — but Spider evaluation never sees enriched schemas. There is **no runnable "Raw vs Enriched" experiment yet**.
5. **There is currently no execution-guided feedback anywhere in the code**, and there is no comment-driven human feedback anywhere in the code. Both existed in the removed chatbot layer and would need to be rebuilt from scratch, directly against the Spider harness, if the thesis still wants to claim them (§8, §12).
6. **The validator is weak.** Confirmed empirically, unchanged by the cleanup (the validator logic itself was not touched):
   - `SELEC * FRM singer` and `hello world` both pass the "syntax" check.
   - The column check is a no-op.
   - There are false positives: `SELECT EXTRACT(YEAR FROM birth_date) ...` is rejected as "Table 'birth_date' does not exist".
7. **The evaluation metrics are non-standard.** EM is lowercase/whitespace-normalised string equality, not Spider's official component-based exact-set-match; EX compares sorted, lower-cased result rows, not the official test-suite evaluation. Numbers from this harness are not comparable with published Spider results unless the official scripts are added (§10).
8. **The Spider harness saves no predictions or retrieval traces.** Error analysis, schema-linking recall and before/after examples cannot be produced without a small code addition (§14).
9. **The retrieval depth is fixed at K = 15.** `retrieve_schema_elements`'s own default of 10 is never used by any caller. K is not exposed as a CLI flag, and the relevance threshold is commented out (disabled).
10. **The repository has no automated tests** (no `test_*.py`, no pytest configuration) and no saved experiment results of any kind.

---

## 1. Overall Architecture

### 1.1 One pipeline, three layers

Unlike the previous version of this repository, there is now exactly one execution path. `cli_spider_eval.py` calls `run_spider_evaluation` (`app/spider_eval/spider_runner.py:254`), which for each Spider question:

1. extracts (or reuses a cached) SQLite schema,
2. builds (or reuses) a Chroma collection of retrieval units for that database,
3. instantiates `NL2SQLChain` (`app/nl2sql_chain.py`) for retrieval, prompt-building and LLM calls,
4. runs single-pass or validation-feedback inference (`SQLFeedbackLoop`, `app/sql_validator.py`),
5. scores the result with Exact Match and Execution Accuracy (`app/spider_eval/spider_evaluator.py`, `spider_sqlite_executor.py`).

Two components exist in the repository but sit **outside** this call graph, invocable only by hand:
- `enrich_schema.py` — a standalone CLI (`python enrich_schema.py <schema.json>`) with zero callers elsewhere in the code.
- `app.utilities.create_schema_vector_store()` — a generic "schema JSON → Chroma collection" builder with zero callers; `spider_runner.py` builds its own collections directly (`_build_collection`) instead of using it.

Both are legitimate, working pieces of the offline layer — they are just not wired into the one pipeline that currently runs.

### 1.2 Actual data flow (as implemented)

```
OFFLINE (per Spider db_id, on the fly, cached in Chroma once built)
Spider SQLite DB
  └─ SQLiteSchemaExtractor (spider_eval/sqlite_schema_extractor.py)
       sqlite_master + PRAGMA table_info / foreign_key_list
  └─ Schema dict {tables, columns, relations} — placeholder descriptions, NOT enriched
       (enrich_schema.py exists and works on this exact dict shape, but nothing calls it here)
  └─ SchemaManager → one text unit per table / column / relation
  └─ Embedding fn (local SentenceTransformer | OpenAI) → ChromaDB collection "Schema_spider_<db_id>"
       (only populated if the collection is empty — no re-embedding on later runs)

ONLINE (per question)
NL question ──(no query enhancement)──► embed question (same embedding fn as the documents)
  └─ Chroma dense Top-K (K=15, no threshold, no filter) → list of unit texts (distances discarded)
  └─ build_schema_context(): group units into Tables / Columns / Relations sections
  └─ build_user_prompt() + culture="en" system prompt → LLM (Ollama local | OpenAI gpt-4o-mini), streaming
  └─ clean_sql_output(): strip ``` fences and comments, flatten, add ';'
  └─ validate_query(): SELECT-first check + FROM/JOIN table-name check   [only validation signal that exists]
  └─ on failure: feedback prompt (last failed SQL + error + hint) → regenerate (same retrieved context, not re-run)
       up to max_iterations total attempts (Spider CLI: --max-iter, default 4)
  └─ EM (string match against gold) + EX (separate, read-only SQLite execution of pred vs gold — scoring only,
       never fed back into generation)
```

### 1.3 Stage-by-stage table

| # | Stage | Input | What happens | Output | Why it exists | Where | Status |
|---|---|---|---|---|---|---|---|
| 1 | Schema extraction | `.sqlite` file | `sqlite_master`, `PRAGMA table_info`, `PRAGMA foreign_key_list`; SQLite types mapped to a generic vocabulary; tables without a PK fall back to their first three columns as `key_columns`; every FK is labelled `"many-to-one"` (not inferred) | Schema dict `{tables, columns, relations}` | Turns a Spider SQLite database into a model-independent description | `app/spider_eval/sqlite_schema_extractor.py:154-221` | IMPLEMENTED |
| 2 | Metadata enrichment | Schema dict/JSON | A local LLM writes short Persian keyword descriptions for tables (from structure), then columns (conditioned on the enriched table description), then relations (`join_purpose`, itself unused downstream) | Enriched schema dict/JSON | Bridges the gap between NL vocabulary and schema identifiers | `enrich_schema.py:193-239` | IMPLEMENTED **as a standalone tool; not called by the Spider pipeline** |
| 3 | Retrieval-unit construction | Schema dict | One text template per table, column and FK relation | `ids[]`, `documents[]` | Defines what can be retrieved | `app/schema_manager.py:20-69, 188-213` | IMPLEMENTED |
| 4 | Embedding + indexing | Unit texts | Embeds with a local SentenceTransformer (L2-normalised) or OpenAI `text-embedding-3-small`, upserts into a per-`db_id` Chroma collection in batches of 10, only if empty | Persistent Chroma collection | Makes semantic nearest-neighbour search possible | `app/spider_eval/spider_runner.py:68-110` (production-facing `create_schema_vector_store` in `app/utilities.py:27-91` also exists but is unused) | IMPLEMENTED |
| 5 | Query enhancement | Question | None. The raw question is embedded directly. | – | – | – | PLANNED (diagram only) |
| 6 | Dense retrieval | Question | `collection.query(query_texts=[q], n_results=15)` | Top-15 unit texts + distances | Schema linking and pruning | `nl2sql_chain.py:97-126`, K at `spider_runner.py:151, 193` | IMPLEMENTED |
| 6' | BM25 / lexical retrieval | – | – | – | – | – | PLANNED |
| 6'' | RRF fusion | – | – | – | – | – | PLANNED |
| 7 | Reranking | – | – | – | – | – | PLANNED |
| 8 | Context assembly | Unit texts | Classifies each unit by the substring ` Table:` / ` Column:` / `Relation:` into three bulleted sections, keeping retrieval order | Schema context string | Gives the LLM a structured, compact schema | `nl2sql_chain.py:128-177` | IMPLEMENTED |
| 9 | Prompt + LLM | Question + context (+ feedback) | System prompt (FA/EN, normal/feedback — only EN is ever selected today) plus a user prompt; streaming chat completion, temperature 0.1 | Raw LLM text | SQL generation | `nl2sql_chain.py:82-96, 179-272`; `system_prompt.py` | IMPLEMENTED |
| 10 | Output cleaning | Raw text | Removes ```` ```sql ```` fences and `--` / `/* */` comments, flattens newlines, appends `;` | SQL string | Makes free-form LLM output executable | `sql_validator.py:166-196` | IMPLEMENTED |
| 11 | Static validation | SQL | Checks that the first DML token is SELECT (sqlparse) and that regex-extracted FROM/JOIN names exist in the full schema | valid? + error | Cheap automatic feedback signal | `sql_validator.py:42-113` | PARTIALLY IMPLEMENTED: column check is a no-op |
| 12 | Execution validation (as feedback) | SQL | **Does not exist.** `SQLValidator.execute_and_validate` was removed with the chatbot layer. | – | – | – | REMOVED |
| 13 | Automatic feedback loop | Failed SQL + error | Builds a feedback prompt from the **last** failure, switches to the feedback system prompt, re-uses the same retrieved context, and regenerates | New SQL | Self-correction | `sql_validator.py:199-263`, `spider_runner.py:190-247` | IMPLEMENTED (validation-only) |
| 14 | Human semantic feedback | – | **Does not exist.** The `/feedback`/`/regenerate` endpoints and the corrected-SQL/comment storage were removed with the chatbot layer. | – | – | – | REMOVED |
| 15 | Logging | Run data | `print()`-only per-sample status lines and final aggregate metrics to stdout | Console output | Minimal progress reporting | `spider_runner.py:374-379`, `cli_spider_eval.py:83-88, 159-162` | IMPLEMENTED (minimal; see §10.6) |
| 16 | Spider evaluation | dev.json + SQLite DBs | Runs inference per sample, then string EM and result-set EX | Aggregate % | Controlled benchmark | `app/spider_eval/*`, `cli_spider_eval.py` | IMPLEMENTED (non-standard metrics) |

---

## 2. Offline Preparation Layer

### 2.1 Schema extraction

Only one extractor exists now: **`SQLiteSchemaExtractor`** (`app/spider_eval/sqlite_schema_extractor.py`).

- **Tables:** enumerated via `sqlite_master`. Description is always the placeholder `"Table <name>"` — SQLite has no built-in comment/description mechanism to read, unlike SQL Server's `MS_Description` extended properties.
- **Columns:** `PRAGMA table_info(<table>)`, giving name, declared type, nullability and PK flag. Description is always the placeholder `"Column <c> of table <t>"`.
- **Primary keys → `key_columns`:** if `PRAGMA table_info` reports no PK column, the extractor falls back to the table's **first three columns**. This heuristic is a leftover from the design's original SQL Server extractor and is not SQLite-specific; it is still a heuristic, not a guarantee of key semantics.
- **Foreign keys:** `PRAGMA foreign_key_list(<table>)`, one relation per FK column pair. `relationship_type` is always `"many-to-one"` (not inferred from cardinality), and `join_purpose` gets the placeholder `"connecting <t> to <target>"`.
- **Type mapping:** SQLite's loosely-typed column declarations are mapped to the same generic vocabulary used elsewhere (`integer`, `decimal`, `varchar`, `date`, `datetime`, `boolean`, `blob`) at `sqlite_schema_extractor.py:147-191`.
- Spider's own `tables.json` (with its curated, human-written, natural-language column names such as "singer id") is **loadable** (`app/spider_eval/spider_loader.py:70-88`, `load_spider_tables`) but **never called** by anything — the extractor re-derives everything from the live SQLite file instead of using Spider's own richer metadata.

**A SQL Server extractor (`extract_schema.py`) existed in an earlier version of this repository**, targeting a live production database with hard-coded connection credentials. It has been removed as out of scope for the now Spider-only research core (§ revision note). If the thesis later wants to demonstrate generalization to a live enterprise RDBMS as part of its contribution, that extractor needs to be rebuilt — ideally parameterized via environment variables from the start rather than hard-coded, and kept separate from any one company's infrastructure.

### 2.2 Schema JSON / dict representation

*(unchanged by the cleanup — `SchemaManager`'s loader was not touched)*

```json
{
  "database_name": "...", "description": "...",
  "tables":    [{"name": "singer", "description": "<text>", "key_columns": ["Singer_ID"]}],
  "columns":   [{"table_name": "singer", "column_name": "Name", "meaning": "<text>", "data_type": "varchar"}],
  "relations": [{"source_table": "singer_in_concert", "source_column": "Singer_ID",
                 "target_table": "singer", "target_column": "Singer_ID",
                 "relationship_type": "many-to-one", "join_purpose": "<text>"}]
}
```
`SchemaManager.load_schema_from_json` / `load_schema_from_dict` (`schema_manager.py:80-186`) read only `name`, `description`, `key_columns`, `table_name`, `column_name`, `meaning`, `data_type` and the four relation endpoints plus `relationship_type`. They ignore `join_purpose`, `database_name` and the schema-level `description`.

### 2.3 Retrieval unit design

*(unchanged by the cleanup — `SchemaManager`'s embedding-text templates were not touched)*

A **retrieval unit** is one schema element rendered as one sentence-like string. There are three unit types, stored as three kinds of document in the same Chroma collection:

| Unit type | Template (`schema_manager.py`) | Real example (Spider `singer`/`concert`, raw — the only kind that currently exists in this pipeline) |
|---|---|---|
| **Table** (`table_i`) | `"{name} Table: {description}. شامل ستون های {key_columns}. "` ("includes columns …") | `singer Table: Table singer. شامل ستون های Singer_ID.` |
| **Column** (`column_i`) | `"{table}.{column} Column: {meaning}, نوع داده {data_type}."` ("data type …") | `singer.Name Column: Column Name of table singer, نوع داده varchar.` |
| **Relation** (`relation_i`) | `"Relation: {src}.{col} ↔ {tgt}.{col}. نوع رابطه {type}. "` ("relationship type …") | `Relation: singer_in_concert.Singer_ID ↔ singer.Singer_ID. نوع رابطه many-to-one.` |

Properties that matter for the research:
- **Granularity:** fine-grained, one unit per column. A table unit lists only its *key* columns, not all of them.
- **Units are independent.** Retrieving a column does not bring in its table, and retrieving a table does not bring in its non-key columns. There is no FK-graph expansion to add missing join paths or bridge tables.
- **The glue words are always Persian** (`شامل ستون های`, `نوع داده`, `نوع رابطه`), **even though every unit the current pipeline ever builds is otherwise in English** (placeholder descriptions from the SQLite extractor, English Spider questions). This mixed-language template is a direct, measurable leftover of the design being built for a Persian production system; it has not been adapted now that the only running data source is English.
- **Relation units carry almost no semantics:** identifiers plus "many-to-one". The LLM-generated `join_purpose` is dropped (present in the schema dict, never read by `SchemaManager`).
- **No cell values or example values** are indexed.
- **No Chroma metadata** is stored (documents and ids only). Unit type and parent table can only be recovered by string matching, so metadata filters such as "only columns of table X" are impossible.
- **Unit counts on a small Spider database:** a replica of `concert_singer` (4 tables, 21 columns, 3 FKs) gives 28 units, so K=15 retrieves about 54% of the schema — on small Spider databases, retrieval prunes little. Verified empirically on a synthetic two-table database as well (§ smoke test, method note above).

### 2.4 Vector database structure

- **Engine:** ChromaDB `1.3.7`, `PersistentClient`.
- **The only collections the running code ever creates** live under `./chroma_db/spider_eval/`, named `Schema_spider_<db_id>`, one per Spider database, populated only if the collection is currently empty (`spider_runner.py:99, 46-48`).
- `app.utilities.create_schema_vector_store()` (a generic "any schema JSON → `./chroma_db/Schema_<name>`" builder) still exists and still works, but as noted in §1.1 it has **zero callers** anywhere in the current codebase — it is available for reuse (e.g. to build a one-off collection from an enriched schema for a manual experiment) but nothing invokes it automatically.
- **Index:** Chroma's default space (squared L2). With unit-normalised vectors, squared L2 equals 2·(1 − cos), so ranking is **equivalent to cosine similarity**.
- **Lifecycle caveat:** changing the schema dict, the unit template or the embedding model does **not** re-embed an existing collection (only empty collections are populated). The `chroma_db/spider_eval` directory must be deleted manually between experiments that change any of those, otherwise a run silently uses stale vectors (§10.7).

---

## 3. Metadata Enrichment

**Status: IMPLEMENTED as a standalone tool; NOT INTEGRATED into the Spider pipeline.** Before the cleanup it was "partially implemented — production only"; the "production" caller (`extract_schema.py`) that used to invoke it automatically is now gone, so today `enrich_schema.py` is a fully working, generic script that nothing in the repository calls for you. You have to run it yourself and then separately point evaluation at its output (which the current `spider_runner.py` does not do).

| Item | Finding |
|---|---|
| Model | Ollama, `gemma3:4b` (`enrich_schema.py:17`), host `http://127.0.0.1:11434`, temperature 0.1, `think=False` |
| Invocation | Standalone only: `python enrich_schema.py <schema.json> [output.json]`, or by calling `enrich_schema(schema_dict)` / `enrich_schema_file(...)` from other code — which nothing currently does |
| Language | **Persian only** ("Persian only." is a rule in every prompt) |
| Output style | **2–6 (tables) or 2–5 (columns, relations) comma-separated Persian keywords, not sentences** |
| In-context learning | **None.** All three prompts are zero-shot instruction prompts with no examples. |
| Output parsing | Regex `^\s*\**LABEL\**\s*:\s*(.+)$` (`_extract_label`, `:173`). If the label is missing, the original value is kept (here, always a placeholder, since the only extractor left is SQLite's). |
| Calls | Sequential: one LLM call per table, then per column, then per relation. There is no batching and no caching. |
| Input compatibility | Confirmed compatible with the exact dict shape `SQLiteSchemaExtractor.extract()` produces — both use the same `{name, description, key_columns}` / `{table_name, column_name, meaning, data_type}` / `{source_table, source_column, target_table, target_column, relationship_type, join_purpose}` keys. |

### 3.1 Prompt structure (quoted and condensed)

*(unchanged by the cleanup)*

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

*(unchanged by the cleanup)*

- **Hierarchical conditioning.** Tables are enriched first. The dict objects are mutated in place and the column prompt reads `table.get('description')`, so every column is described in the context of its table's enriched description.
- **Structural context for tables.** The table prompt sees all column names and types and the outgoing FKs, so the LLM can infer purpose from structure.
- **Keyword-style output is a deliberate retrieval choice.** Short keyword lists keep each unit's embedding focused. This is a reasonable design, but it has not been measured.
- **No data values.** The LLM never sees sample rows, so descriptions are inferred from identifiers alone.
- **`join_purpose` is generated but never used**, because `Relation.to_embedding_text` does not include it and `SchemaManager` does not load it.
- Since the only remaining extractor (SQLite) never reads a comment/description field the way the removed SQL Server extractor read `MS_Description`, there is no longer any "existing documentation gets overwritten" concern for the current pipeline — that finding from the first report applied specifically to the now-removed production path.

### 3.3 How enrichment would affect retrieval, if wired in

The enrichment text is concatenated into the table and column unit strings (`description` and `meaning`). It would therefore change **both** the embedding vectors used for retrieval **and** the schema context the LLM reads. For a Persian question against an English/abbreviated schema, a raw unit such as `singer.Name Column: Column Name of table singer, …` has to be matched cross-lingually by the embedding model alone; an enriched unit sharing Persian vocabulary with the question would not need to. This is the central research motivation for enrichment: **cross-lingual and semantic bridging between Persian user vocabulary and English or abbreviated identifiers.** It is currently unmeasured on Spider, since nothing invokes it there.

### 3.4 Why in-context examples would help (currently not used, so PLANNED / future work)

A few curated examples of "(table/column signature) → ideal keyword description" would stabilise the output format and granularity, teach domain conventions (`*ID` → identifier, `Is*` → boolean status, `*Date` → temporal filter), reduce generic outputs for cryptic names, and make descriptions consistent across tables (which matters because retrieval compares units with each other). This is a legitimate, low-cost extension. Do not describe it as implemented.

### 3.5 Implication for the Spider experiments

To run "Raw vs Enriched" on Spider, three changes are needed:
- (a) call `enrich_schema(schema_dict)` inside `spider_runner.py`, right after `SQLiteSchemaExtractor.extract()` and before `_build_collection` embeds it — the dict shapes are already compatible, so this is a small, mechanical change, not a redesign;
- (b) decide the enrichment language. English matches Spider questions and is the more defensible default for a Spider-only claim. Persian keeps the method identical to the original motivating use case (a Persian production system) but requires a Persian question set to actually test the cross-lingual claim (which does not currently exist anywhere in this repository);
- (c) cache the enriched dict per `db_id` (e.g. to a JSON file next to the sqlite database, or in memory keyed by `db_id` the way the Chroma collection is already cached), so that the LLM's non-determinism does not silently change descriptions between repeated runs of the same experiment.

---

## 4. Embedding

*(the embedding function and its configuration are unchanged by the cleanup)*

| Item | Finding |
|---|---|
| Selection | Env var `USE_LOCAL_EMBEDDING` (`app/dotenv.py`) |
| Local | `LocalSTEmbeddingFunction` (`app/utilities.py:94-115`): `SentenceTransformer(EMBEDDING_MODEL_DIR, local_files_only=True, device="cpu")`, fully offline, CPU |
| Local model identity | Printed label `"google/embeddinggemma-300m"` (`utilities.py:21`, misleadingly named `OLLAMA_EMBEDDING_MODEL_NAME`). **The model actually loaded is whatever is in `EMBEDDING_MODEL_DIR`, which is not recorded in the repo** (the `.env.template` leaves it blank). Confirm it before claiming a model on a slide. |
| Online | Chroma `OpenAIEmbeddingFunction`, model `text-embedding-3-small` (`utilities.py:22`) |
| Dimension | Not set in code. According to the model cards: EmbeddingGemma-300m outputs 768-d (Matryoshka truncation to 512/256/128 is possible but unused), and text-embedding-3-small outputs 1536-d. |
| Normalisation | Local: `normalize_embeddings=True` (L2). OpenAI embeddings are unit-length by the provider. |
| Input text | The unit strings of §2.3 for documents, and the **raw question** for queries |
| Query vs document encoding | **Symmetric.** The same function and the same `encode()` call are used for both, and no `prompt_name` is passed. EmbeddingGemma's model card recommends asymmetric task prompts (`encode_query` / `encode_document` in sentence-transformers). Not applied here. This is a low-effort improvement to test. |
| Batching | Offline upsert batches of 10 (`utilities.py:44`, `spider_runner.py:73`) |
| Chroma usage | `get_or_create_collection(name, embedding_function=ef)` + `upsert(ids, documents)`; retrieval via `get_collection(...).query(query_texts=[q], n_results=K)` |

**Research implication.** Schema linking means mapping phrases in the question to schema elements. Pure string matching fails when the user's words differ from the identifiers, the question and the schema are in different languages, or identifiers are abbreviated/cryptic. A multilingual dense encoder maps paraphrases and translations close together even with zero token overlap. The known weakness of dense retrieval is **exact-term matching** (rare identifiers, codes, literal values), which is the standard argument for adding BM25 (§13).

---

## 5. Retrieval

### 5.1 Exact current configuration (IMPLEMENTED)

| Parameter | Value | Location |
|---|---|---|
| Method | Dense kNN only (Chroma HNSW) | `nl2sql_chain.py:118` |
| Query | Raw question string, embedded with the same model as the documents | same |
| Similarity | Chroma default space (squared L2 on unit vectors, equivalent to cosine ranking) | collection creation, `spider_runner.py:91` |
| K | **15** (method default 10 is never used by any caller) | `spider_runner.py:151, 193` |
| Threshold | **None.** No relevance-distance cutoff exists in the current code. | – |
| Filtering | None (no `where`, no type quotas, no per-table caps) | – |
| Distances | Returned by `retrieve_schema_elements` but **discarded** by every caller. Not in the prompt, not logged, not used for ranking decisions. | `nl2sql_chain.py:97-126`; callers ignore the second tuple element |
| Post-processing | Grouped by unit type into Tables / Columns / Relations, preserving rank order within groups | `nl2sql_chain.py:128-177` |
| Empty result | `None` is returned by the inference helper, which counts as wrong for both EM and EX | `spider_runner.py:159-163, 204-207` |

If K exceeds the collection size, Chroma returns all units, so the whole schema is included.

### 5.2 Not implemented (PLANNED): BM25, RRF, reranking, query enhancement

- **BM25:** no corpus tokenisation, no `rank_bm25` or other lexical index. `scikit-learn` is still in `requirements.txt` but is unused for this purpose (it is a plausible transitive dependency of `sentence-transformers`).
- **RRF:** no fusion code.
- **Reranker:** no cross-encoder or LLM reranker. The design doc's planned setting is Dense Top-20 + BM25 Top-20, a pool of 40, reranked to Top-10.
- **Query enhancement:** no rewriting, translation, decomposition or keyword extraction.

The planned design is plausible and well motivated, but none of it can be presented as implemented.

---

## 6. Query-to-Schema Matching (the core research problem)

**Problem.** Given a question q and a schema S = {tables ∪ columns ∪ FK relations}, select the minimal subset S_q that is sufficient to write the correct SQL, and present it so that the LLM uses the right elements and joins.

The architecture approximates S_q by the top-K nearest units to q. Each mismatch type below is tied to evidence in the (unchanged) code. Examples marked *illustrative* were built from the templates and are **not** logged retrieval results.

| Mismatch type | How it appears in this architecture | Evidence / mechanism |
|---|---|---|
| **Lexical mismatch** | User words ≠ identifier tokens ("users" vs a table literally named `Users`, "price" vs `UnitPrice`) | Dense encoder is the only bridge; there is no lexical channel |
| **Cross-lingual mismatch** | A Persian question vs English/abbreviated identifiers | This is exactly what enrichment (§3) is meant to close — but on the one pipeline that currently runs, enrichment is disconnected, so this gap is currently fully open |
| **Semantic mismatch** | "Best-selling" implies an aggregate over order-line quantities; no unit literally says "sales" | Nothing currently mitigates this on the Spider path (enrichment, which would partly help, is not wired in) |
| **Ambiguous column names** | `Name`, `Id`, `Year` appear in several tables | Every column unit is prefixed `table.column`, which disambiguates the *identity*, but the retrieval score may still favour the wrong table's `Name` |
| **Value grounding** | "singers from France" needs `singer.Country`, but "France" appears in no unit | No values are indexed (§2.3); the model must infer the column from semantics only |
| **Missing schema context** | A retrieved column's table unit, or other needed columns, fall outside Top-K | Units are independent and there is no expansion; the prompt rule "Do not invent tables or columns" then forces the LLM to guess or fail |
| **Multi-table / join ambiguity** | A question spans a bridge table (many-to-many), e.g. singer ↔ singer_in_concert ↔ concert | Relation units are near-content-free (identifiers + "many-to-one"), so they are unlikely to rank high for NL questions. `join_purpose` is unused. No FK-path completion. |

*Illustrative rendering* (produced by running the real `build_schema_context` / `build_user_prompt` on a synthetic two-table `singer`/`concert` SQLite database, with a **hand-picked** subset standing in for a partial retrieval — I re-ran this after the cleanup and the output is unchanged, since none of this code was touched):
```
Tables:
  - concert Table: Table concert. شامل ستون های concert_ID.
  - singer Table: Table singer. شامل ستون های Singer_ID.
Columns:
  - concert.concert_ID Column: Column concert_ID of table concert, نوع داده integer.
  - concert.concert_Name Column: Column concert_Name of table concert, نوع داده varchar.
  - concert.Stadium_ID Column: Column Stadium_ID of table concert, نوع داده integer.
  - singer.Singer_ID Column: Column Singer_ID of table singer, نوع داده integer.
  - singer.Name Column: Column Name of table singer, نوع داده varchar.
  - singer.Country Column: Column Country of table singer, نوع داده varchar.
```
A question needing a `singer ↔ singer_in_concert ↔ concert` join would have no relation unit at all here (this toy schema has none), which is the sharpest possible illustration of "missing schema context forces the LLM to guess a join it was never shown." This failure mode is architectural, which makes it a good slide, **as long as it is labelled as illustrative until measured.**

---

## 7. LLM Generation

### 7.1 Models and parameters (IMPLEMENTED)

| Setting | Local (`USE_LOCAL_LLM=true`) | Online (`USE_LOCAL_LLM=false`) |
|---|---|---|
| Client | `ollama.AsyncClient` | `openai.AsyncOpenAI` |
| Model | `gemma4:12b` (Ollama tag as configured, `nl2sql_chain.py:39`) | `gpt-4o-mini` (`:269`) |
| Endpoint | `http://127.0.0.1:11434` (reset to localhost by the cleanup; previously pointed at an internal company GPU host) | OpenAI API |
| Temperature | 0.1 | 0.1 |
| Max tokens | not set | not set |
| Seed / top_p / num_ctx | not set. Ollama's default context window applies. Check it if K grows, because Ollama truncates long prompts. | not set |
| Reasoning | `think=False` | – |
| Streaming | yes (the Spider runner collects the streamed tokens into one string) | yes |

The model names are hard-coded, so changing the model is a code edit; only local vs online is an env switch. A third provider (GapGPT → `gemini-2.5-flash`) was added and later removed well before this cleanup pass; no trace of it remains in `requirements.txt` or `dotenv.py` now.

### 7.2 Prompt structure

*(unchanged mechanism; `culture` is now always `"en"` in the only caller that exists — see below)*

Each call is **single-turn**: `[system, user]`. There is no conversation memory and no few-shot examples.

**System prompts** (`app/system_prompt.py`), four variants exist in code, but only two are ever reachable today:
- `SYSTEM_PROMPT_NL2SQL_EN` (reachable): `[ROLE]` generic SQL expert, `[INPUT]`, `[CRITICAL RULES]` (use only schema tables/columns/relations, invent nothing, infer JOINs from schema, standard executable SQL, use aggregates properly, WHERE filters, DATE functions), `[OUTPUT FORMAT]` `SELECT… FROM… WHERE…`, no explanation, no code-block instruction, and — notably — **no SQL dialect is named**, even though Spider databases are SQLite.
- `SYSTEM_PROMPT_NL2SQL_FEEDBACK_EN` (reachable): "You are correcting a previous query that failed". Read the error, output only corrected SQL, check spelling of tables and columns, verify JOINs, qualify ambiguous columns with aliases.
- `SYSTEM_PROMPT_NL2SQL_FA` / `SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA` **still exist in the file** but are **currently unreachable dead code**: `NL2SQLChain.__init__` defaults `culture` to `"en"`, and the sole place that constructs the chain (`spider_runner.py:321`) passes `culture="en"` explicitly. Nothing in the current codebase ever passes `culture="fa"`. These two prompts (which, notably, instruct the model to write **T-SQL** specifically, and to wrap output in a ```` ```sql ```` code block) are only reachable again if a future script explicitly requests Persian — for example, a planned Persian-translated Spider subset experiment (§ Open Questions).

**User prompt** (`build_user_prompt`, `nl2sql_chain.py:179-226`):
```
User Question:
<question>

Available Database Schema:
Tables:
  - <table unit text>
Columns:
  - <column unit text>
Relations:
  - <relation unit text>

Rules:
- Use only provided schema
- Do not invent tables or columns
- Output SQL only

SQL Query:
```
Feedback iterations use a different layout (§8). The retrieved units are pasted verbatim, including the Persian glue words (§2.3) inside otherwise-English units, and data types. **Distances, full column lists, sample values and DDL formatting are absent.**

### 7.3 Output handling

`clean_sql_output` removes Markdown fences and comments, collapses newlines and tabs to spaces, and appends `;` (`sql_validator.py:166-196`). It does not extract SQL from surrounding prose, so an explanation sentence before the SQL would survive and then fail validation.

---

## 8. Feedback Loop

### 8.1 Mechanisms — three of the four described in the original proposal are gone from the code

| | Mechanism | Status | Detail |
|---|---|---|---|
| **A** | Automatic validation feedback | **IMPLEMENTED** (weak detector, §9) | Empty SQL; first DML keyword ≠ SELECT; a FROM/JOIN name not in the full schema. Last failed SQL + error + canned hint fed back. Runs only via the Spider CLI's `--feedback`/`--compare` flags — there is no other caller left. |
| **B** | SQL execution feedback | **REMOVED** | Existed as `SQLValidator.execute_and_validate` (SQLAlchemy against a SQL Server execution database), reachable only from the now-deleted chatbot endpoint. Deleted along with the chatbot layer and the SQLAlchemy/asyncpg dependency. **Not present anywhere in the current code.** |
| **C** | User semantic feedback | **REMOVED** | Existed as the `/feedback` + `/regenerate` FastAPI endpoints, a PostgreSQL `feedback_comment`/`corrected_sql` column, and a React modal collecting a 👎 + mandatory corrected SQL + optional comment. All deleted along with the chatbot layer. **Not present anywhere in the current code.** |
| **D** | Regeneration | **IMPLEMENTED, but only the automatic kind (A)** | The comment-driven regeneration that used to also trigger this (via C) no longer exists. |

If the thesis still intends to claim an execution-feedback or human-feedback contribution, both need to be **built fresh**, shaped for a batch research harness rather than a chat product — see §12 (C4, C5) for concrete, minimal starting points.

### 8.2 Loop semantics (mechanism A), from `spider_runner.py:190-247` and `sql_validator.py:199-263`

1. `max_iterations` counts **total attempts**, not retries (`should_continue: len(history) < max`). Spider CLI: `--max-iter N`, default 4 (the CLI's own default; `run_spider_evaluation`'s programmatic default is 3). `--max-iter 1` is effectively single-pass with validation gating, and `--max-iter 2` is a single retry.
2. Each attempt runs clean → `validate_query`. On failure, the history gets `(sql, error, success=False)`.
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
   - The labels "Syntax error" and "SQL execution failed" are used for **every** error type, including plain schema-validation errors, since there is no execution feedback to distinguish them from anymore.
4. **What does not change:**
   - The retrieved schema context. **Retrieval is not re-run**, so an error caused by a missing table or column in the context cannot be repaired from new schema information.
   - Only the **last** failure is shown. Earlier failed attempts are forgotten, which allows oscillation between two wrong queries.
   - The Rules block disappears in feedback iterations.
5. **When all attempts fail:** the inference helper returns `None`, which counts as incorrect for both EM and EX (§5.1).

### 8.3 Why the feedback variable is subtle on Spider

Because the detector is weak (§9), two things follow: (i) real errors — a wrong column, a wrong join, broken syntax — are mostly **not** detected, so the loop rarely fires; (ii) false positives (a column named `*_from`, `EXTRACT(... FROM col)`, §9.2) can force regeneration of a *correct* query, or turn it into `None` after N failures. A "feedback delta" from `--compare` would therefore mostly measure validator precision and sampling noise, not the value of iterative correction. Adding SQLite execution feedback is the single highest-leverage next step for a credible feedback experiment (§12 C4, §14.3).

---

## 9. SQL Validation

### 9.1 Levels

| Level | Implementation | What it really checks | Status |
|---|---|---|---|
| 0. Cleaning | `clean_sql_output` | Formatting only | IMPLEMENTED |
| 1. "Syntax" | `validate_syntax` (`sql_validator.py:42-74`) using `sqlparse` | Non-empty; **if** the first token is a DML keyword it must be SELECT. `sqlparse` is a non-validating tokenizer, so real syntax errors pass. | IMPLEMENTED, but nominal |
| 2. Schema | `validate_schema_elements` (`:76-113`) | Regex `(?:from\|join)\s+([a-z_][a-z0-9_]*)` on the lowercased SQL; each captured name must be a table in the **full** schema, not only the retrieved subset. The column check (`:104-111`) is a **no-op loop**. | PARTIALLY IMPLEMENTED |
| 3. Execution (as feedback) | – | **Does not exist.** `execute_and_validate` was removed with the chatbot layer, along with SQLAlchemy. | **REMOVED** |
| 3'. Execution (as scoring, not feedback) | `SpiderSQLiteExecutor.compare` (`app/spider_eval/spider_sqlite_executor.py:208-248`) | Executes predicted and gold SQL via a connection that actually commits on success (§10.5), and compares sorted, lowercased rows. **Only used after a final SQL string is already chosen, to compute the EX metric — never as a signal fed back into generation.** | IMPLEMENTED, but scoring-only |
| 4. Semantic | – | No automatic semantic check exists. There is also no human-feedback channel left to catch this manually (§8, mechanism C removed). | PLANNED / future work |

### 9.2 Empirical probe (executed against the current, unchanged `SQLValidator` code)

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

"Valid SQL" now means, simply: **non-empty, not led by a non-SELECT DML keyword, and every identifier after FROM/JOIN is a known table name.** There is no longer an "additionally executes without error" tier available anywhere (that existed only in the removed chatbot's execution-validation flag). Validity implies neither syntactic correctness nor semantic correctness — and, unlike before the cleanup, it also no longer implies "runs against a real database," since nothing in the generation loop ever executes the SQL.

The read-only guard can still be bypassed (CTE, multi-statement) — this matters if the Spider database files are ever treated as anything other than disposable, since `SpiderSQLiteExecutor` opens them read-write (§10.5).

---

## 10. Evaluation / Spider

### 10.1 Integration (IMPLEMENTED)

- **Entry point:** `python cli_spider_eval.py --spider_path <dir> [--limit N] [--feedback | --compare] [--max-iter N] [--quiet]`. VS Code launch configs exist for single-pass, feedback and compare modes (`.vscode/launch.json`, default limit 20) — the cleanup trimmed this file down to only these three configs (the chatbot's Backend/Frontend debug configs were removed).
- **Expected layout:** `<spider>/dev.json`, `<spider>/tables.json`, `<spider>/database/<db_id>/<db_id>.sqlite`. The Spider data is git-ignored (`*/spider/`).
- **Splits:**
  - **Only `dev.json`** is used: `question`, `query` (gold), `db_id`. The dev set has 1,034 questions over 20 databases.
  - **train** is unused. There are no few-shot examples and no fine-tuning.
  - **test** is unused. `tables.json` is loadable but unused (§2.1).
- **Per sample:** resolve the SQLite path → build/reuse the schema + Chroma collection + `NL2SQLChain` for that `db_id` → run single-pass (`_infer_sql`) or validation-feedback (`_infer_sql_with_feedback`) inference → compute EM and EX.
- **Skips:** if a SQLite file is missing or schema building throws, the sample is **skipped and not counted** in `total` (`spider_runner.py:296-335`). If inference returns nothing, the sample **is** counted as wrong.

### 10.2 Exact Match (as implemented, `spider_evaluator.py:17-56`)

*(unchanged)* EM = lowercase, whitespace collapse, strip one trailing `;`, then string equality. This is **not** Spider's official EM, which parses both queries into clause components, compares them as sets, and by default ignores literal values. Aliases, column order, spacing and quote style all break the implemented EM. Expect values **far below** published EM, and do not compare them with the literature.

### 10.3 Execution Accuracy (as implemented, `spider_sqlite_executor.py`)

*(unchanged)* Both queries run on the same SQLite file. The gold query fails → False; the prediction fails → False. Rows are compared after converting every value to `str(v).strip().lower()` and **sorting** — multiset equality with column order preserved. Differences from the official test-suite EX: order is ignored even for `ORDER BY` queries; there is no alternative-database test suite; there are no timeouts; string conversion may flag `1` vs `1.0` as different.

### 10.4 Gold vs predicted SQL

The gold SQL is used **only** for EM and EX. It never enters prompts, retrieval or validation.

### 10.5 Leakage and validity assessment

| Risk | Present? | Notes |
|---|---|---|
| Gold SQL in the prompt | **No** | – |
| Schema derived from gold | **No** | The schema comes from the SQLite file |
| Few-shot examples from dev | **No** | – |
| Execution feedback compared with gold results | **N/A** | There is no execution feedback at all right now (§8). If mechanism B is rebuilt, it must use only the prediction's own execution error, never the gold result. |
| Tuning on the same split used for reporting | **Yes (methodological)** | Prompts, K and so on are developed on dev and reported on dev. Mitigation: hold out part of dev, or use a train subset for tuning, or the official test split if available. |
| Pretraining contamination | *Possible (hypothesis)* | Spider has been public since 2018; gpt-4o-mini and Gemma may have seen it. A known limitation of all LLM-on-Spider results; mention it. |
| Biased subsets | **Yes, if `--limit` is used** | `dev.json` is grouped by database (it starts with `concert_singer`), so `--limit 20` evaluates essentially **one** database. Use a stratified or random sample, or the full dev set. |
| Stale vector stores across experiments | **Yes** | Collections are only built when empty. Changing the embedding model or unit template without deleting `chroma_db/spider_eval` reuses old vectors, or fails and silently skips that database's samples. |
| Evaluation DB mutation | *Low probability, real* | Nothing blocks a predicted DML statement in single-pass mode. `SpiderSQLiteExecutor` opens with `with sqlite3.connect(...) as conn`, which **commits** on success, so a `DELETE` would persist; it also switches the files to WAL journal mode. Keep a pristine copy of `database/`, or open SQLite read-only (`file:...?mode=ro`). |
| Non-determinism | **Yes** | Temperature 0.1 with no seed. Single-pass vs feedback runs are separate samples, so part of the delta is noise. Use T=0 and/or repeated runs and paired statistics. |

### 10.6 Logging and experiment tracking

- Every run prints `[i/N] STATUS db=<id> | Q: <first 60 chars>` to stdout, plus final aggregates. **Predicted SQL is not printed or saved**, retrieved units and distances are not logged, and no configuration snapshot (model, embedding model, K, feedback mode) is recorded anywhere.
- **Consequence:** the design document's metrics "Average Tokens Used", "Syntax Error Rate" and "Semantic Error Rate" are **not measurable** with the current code (PLANNED).

### 10.7 Reproducibility notes — one previously-flagged bug is now fixed

- **Fixed by the cleanup:** the first version of this report flagged that merely *importing* `app.nl2sql_chain` created SQLAlchemy async engines from `EXECUTION_DATABASE_URL`/`MAIN_DATABASE_URL` at import time, even for the Spider CLI, which never used them. Those engines (and the SQLAlchemy dependency itself) are gone; importing `app.nl2sql_chain` now only sets a few module-level constants and defines the `NL2SQLChain` class — verified by a clean import smoke test after the cleanup.
- **Still true:** the LLM and embedding model identity comes from hard-coded names plus env variables (`.env` — not committed, templated by `.env.template`). Record them manually for every reported run.

---

## 11. Experimental Variables

| Variable | Baseline | Proposed | Implemented? | Config Location |
|---|---|---|---|---|
| LLM provider | Online `gpt-4o-mini` | Local Ollama `gemma4:12b` (or vice versa) | **Yes** (env switch) | `USE_LOCAL_LLM`; names at `nl2sql_chain.py:39, 269` |
| LLM temperature | 0.1 | 0 for evaluation | Fixed, code edit needed | `nl2sql_chain.py:38, 269` |
| Max tokens / seed | not set | fixed for reproducibility | **No** | – |
| Embedding model | OpenAI `text-embedding-3-small` | Local SentenceTransformer (labelled EmbeddingGemma-300m) | **Yes** (env switch; Chroma dir must be rebuilt) | `USE_LOCAL_EMBEDDING`, `EMBEDDING_MODEL_DIR`; `app/dotenv.py:12-13` |
| Query/document embedding prompts | none (symmetric) | model-specific asymmetric prompts | **No** | `utilities.py:110-115` |
| Retrieval strategy | Full schema in prompt (no retrieval) | Dense Schema-RAG | Dense: **Yes**. Full-schema baseline: **No** (would need a bypass flag). | `nl2sql_chain.py:97-177` |
| Retrieval K | – | 5 / 10 / 15 / 20 / all | **Hard-coded 15**, no CLI flag | `spider_runner.py:151, 193` |
| Relevance threshold | none | distance cut-off | **No** (no code path for it at all now) | – |
| BM25 lexical retrieval | – | BM25 Top-20 | **No** (PLANNED) | – |
| Dense + BM25 fusion (RRF) | – | RRF over both lists | **No** (PLANNED) | – |
| Reranker | – | Cross-encoder on a pool of 40 → Top-10 | **No** (PLANNED) | – |
| Query enhancement | raw question | rewrite / translate / decompose | **No** (PLANNED) | – |
| Retrieval-unit design | table + column + relation units | + FK-path expansion, + values, + `join_purpose` | Base: **Yes**. Extensions: **No**. | `schema_manager.py` |
| Metadata enrichment | Raw placeholders | LLM Persian keyword descriptions | Standalone tool: **Yes**. Wired into Spider: **No**. | `enrich_schema.py`; would hook in at `spider_runner.py` right after schema extraction (§3.5) |
| Enrichment model / language | – | `gemma3:4b`, Persian | Fixed in code | `enrich_schema.py:16-18` |
| Enrichment ICL examples | zero-shot | few-shot | **No** | `enrich_schema.py` |
| Validation feedback | single-pass | iterative (N attempts) | **Yes** | CLI `--feedback`, `--compare`, `--max-iter` |
| Number of feedback iterations | 1 (no feedback) | 2 (single retry) / 4 (iterative) | **Yes** | `--max-iter` |
| Execution feedback | off | on | **No — removed from the codebase entirely** (§8, mechanism B) | Would need to be added fresh in `spider_runner.py::_infer_sql_with_feedback`, using `SpiderSQLiteExecutor` |
| Retrieval re-run inside feedback | no | re-retrieve using the error | **No** | – |
| User semantic feedback | none | comment-driven regeneration | **No — removed from the codebase entirely** (§8, mechanism C) | Would need a fresh design (§12 C5) |
| Prompt language / culture | `en` (the only value ever passed) | `fa` | Code path **exists** (`system_prompt.py`) but **unreachable** — no current caller ever requests `"fa"` | `nl2sql_chain.py:82-96`; the one call site, `spider_runner.py:321`, hard-codes `"en"` |
| Prompt configuration (rules, format, dialect) | current prompts | e.g. SQLite dialect hint, DDL-style context, few-shot | Only one fixed variant per language | `system_prompt.py`, `nl2sql_chain.py:179-226` |
| Evaluation subset | full dev | – | **Yes** (`--limit`, first N only) | `cli_spider_eval.py` |
| EM / EX definition | string EM, sorted-row EX | official Spider EM + test-suite EX | Custom only | `spider_evaluator.py`, `spider_sqlite_executor.py` |

---

## 12. Research Contribution (strictly implementation-based)

The components below exist in code. None is novel *merely because it exists*. Schema linking and pruning, schema-description augmentation and self-correction loops all have prior art; related-work examples to position against include DIN-SQL, RESDSQL, C3, CHESS and execution-guided decoding (verify the citations). The defensible contribution is the specific **combination, the setting (Persian enterprise databases, local models) and the controlled ablation**, not any single mechanism.

### C1: Typed schema-unit retrieval (Schema-RAG). Status: IMPLEMENTED

- **Problem:** real schemas are too large, noisy or costly to include fully in every prompt.
- **Proposed modification:** split the schema into typed units (table, column, FK relation), each a short self-contained sentence. Embed them, retrieve the Top-K per question, and reassemble them into a typed context.
- **Expected mechanism:** higher signal-to-noise context, fewer hallucinated identifiers, lower token cost.
- **Experimental variables:** full schema vs Schema-RAG (needs a bypass flag, currently absent); K ∈ {5, 10, 15, 20} (needs a CLI flag, currently absent).
- **Metrics:** EX; schema-linking recall@K of gold tables and columns (computable from Spider's parsed `sql` field in `dev.json`); prompt tokens.
- **Caveat:** Spider databases are small (§2.3 — K=15 already covers ~54% of a typical database), so the benefit may appear only on larger schemas.

### C2: Hierarchical, keyword-style LLM metadata enrichment for (cross-lingual) schema linking. Status: IMPLEMENTED (standalone tool), NOT INTEGRATED into any pipeline that currently runs

- **Problem:** Persian (or lay-English) questions vs English, abbreviated or cryptic identifiers.
- **Proposed modification:** an offline zero-shot LLM generates compact Persian keyword descriptions, hierarchically (tables first, then columns conditioned on the table description). The descriptions are embedded inside the units.
- **Expected mechanism:** shared vocabulary between question and unit, giving better retrieval ranking and a more informative context for the LLM.
- **Experimental variables:** raw vs enriched; enrichment language (EN vs FA); zero-shot vs few-shot enrichment.
- **Metrics:** recall@K and EX.
- **What's missing:** the one-line-ish Spider integration described in §3.5, and — for the cross-lingual claim specifically — a Persian question set, which does not exist anywhere in this repository today.

### C3: Validation-driven iterative self-correction. Status: IMPLEMENTED (with a weak validator)

- **Problem:** single-shot generation produces invalid SQL.
- **Proposed modification:** a bounded loop. On failure, the failed SQL and the diagnostic are fed back with a correction-specific system prompt.
- **Expected mechanism:** fixes surface errors such as wrong table names and non-SELECT output.
- **Experimental variable:** `--max-iter` ∈ {1, 2, 4}.
- **Metrics:** EX, retry rate, fix rate per iteration.
- **Honest limitation:** the detector catches few errors (§9), so the expected effect is small until execution feedback (C4) is added.

### C4: Execution-guided feedback. Status: **NOT IMPLEMENTED — removed with the chatbot layer, needs to be rebuilt from scratch**

- **Problem:** statically "valid" SQL still fails at run time (wrong columns, types).
- **Proposed modification:** execute on the target DB and feed the engine's error back into `SQLFeedbackLoop`.
- **What exists to build on:** `SpiderSQLiteExecutor` (`app/spider_eval/spider_sqlite_executor.py`) already executes SQL against the exact Spider SQLite databases and already surfaces error messages — today only for after-the-fact EX scoring. A concrete, small first step is to call it from inside `_infer_sql_with_feedback` (`spider_runner.py`), using **only the prediction's own execution outcome**, and feed a failure into `SQLFeedbackLoop.add_iteration(..., success=False)` the same way a validation failure is fed today. This is a genuinely small addition (roughly 10–15 lines), not a redesign — but it is currently zero lines, not "production only" as the earlier report said, since the code path it would have reused (`execute_and_validate`) no longer exists.
- **Experimental variable:** static-only vs static + execution feedback on Spider SQLite.

### C5: Human-in-the-loop semantic feedback. Status: **NOT IMPLEMENTED — removed with the chatbot layer, needs a fresh design**

- **Problem:** execution-valid SQL can still be semantically wrong, and no automated check sees intent.
- **What existed and is now gone:** a chat-product feature (👎 + mandatory corrected SQL + optional comment → `/regenerate`). It does not fit the batch-evaluation shape of the current harness and should not simply be re-added as-is.
- **A design that would fit this harness instead:** either (a) a simulated-user critique loop — an LLM critic reads the question, the schema context and the predicted SQL (never the gold SQL) and writes a correction comment, which is then injected into a rebuilt `build_user_prompt(..., user_semantic_feedback=...)` call (that keyword argument still exists in the function signature even though nothing currently passes it); or (b) an oracle upper bound, where the comment is derived from the gold SQL, explicitly labelled as leakage and reported only as a ceiling, never as a fair result; or (c) a small manual annotation pass over saved predictions (which requires §14.3 item 1 — saving predictions — as a prerequisite).
- Whichever design is chosen, evaluate it — an unevaluated feature is not a result.

### C6: Reproducible Spider evaluation harness. Status: IMPLEMENTED — arguably strengthened by the cleanup

The harness's dependency on chatbot infrastructure (SQLAlchemy engines created at import time regardless of use, a hard-coded production Ollama host) is gone (§10.7), and the codebase is now single-purpose. This is an engineering contribution: valuable for methodology and reproducibility, but not research novelty on its own. It needs official metrics (§10.2, §10.3) to be fully credible.

---

## 13. Failure-Driven Research Gaps

*(unchanged by the cleanup — none of the code these gaps refer to was touched, except where noted)*

Evidence-based means the gap follows directly from the code. Hypothesis means it is plausible but unmeasured.

| # | Gap | Type | Where | Suggested probe |
|---|---|---|---|---|
| G1 | **Fragmented context:** a column is retrieved without its table, or a join path or bridge table is missing | Evidence-based (no expansion logic) | `build_schema_context` | Measure gold-table/column recall@K; add FK-path completion |
| G2 | **Relation units are semantically empty**, so join information is under-retrieved | Evidence-based (template) + hypothesis (effect) | `Relation.to_embedding_text`; `join_purpose` unused | Include `join_purpose`; measure relation recall on multi-table questions |
| G3 | **Dense-only retrieval misses exact identifiers and literal values** | Hypothesis (standard IR finding) | Retrieval | Dense vs BM25 vs hybrid (after implementing) |
| G4 | **Lexical retrieval would fail cross-lingually** (Persian question vs English identifiers) unless units contain Persian text | Hypothesis | Motivates the combination of enrichment and BM25 | BM25 on raw vs enriched units with Persian questions |
| G5 | **Fixed K ignores schema size** (~54% of a small Spider DB retrieved at K=15) | Evidence-based | K=15 constant | K sweep; relative K or a score threshold |
| G6 | **Too many units add noise; too few lose recall** | Hypothesis | K | Plot EX vs K together with recall@K |
| G7 | **Mixed-language unit templates** (Persian glue words in otherwise-English units — now the *only* kind of unit this pipeline ever builds, since enrichment is disconnected) | Evidence-based (template) + hypothesis (small effect) | `schema_manager.py` | Language-matched templates, ablation |
| G8 | **No value grounding** (no cell values or examples indexed) | Evidence-based | Offline layer | Add sampled distinct values to column units |
| G9 | **Validator misses most errors and has false positives** | Evidence-based (empirical probe) | `sql_validator.py` | Replace with `sqlglot` parsing, SQLite `EXPLAIN`, or execution |
| G10 | **Feedback cannot repair retrieval misses** (context is fixed across iterations) | Evidence-based | Loop design | Error-conditioned re-retrieval |
| G11 | **Only the last failure is in the feedback prompt**, which risks oscillation | Evidence-based | `get_feedback_prompt` | Include the full attempt history |
| G12 | **Execution-valid ≠ semantically correct** — and there is currently no execution-as-feedback and no human-feedback channel at all to catch this | Evidence-based (no semantic check anywhere) | – | EX minus "executes without error" rate; LLM self-verification |
| G13 | **Dialect not specified for Spider** (the only reachable system prompt says "standard SQL"; SQLite is never named) | Evidence-based + hypothesis (effect) | `system_prompt.py` | Add a "SQLite" instruction; count dialect errors |
| G14 | *(Retired — no longer applicable.)* This gap previously described the removed comment-driven regeneration mechanism ignoring the previous SQL and the user's corrected SQL. That mechanism no longer exists (§8, §12 C5). If it is rebuilt, design it to avoid this defect from the start: pass the previous SQL, and reuse confirmed corrections rather than discarding them. |
| G15 | **Enrichment sees no data values** (the SQLite path never had `MS_Description`-style comments to lose, unlike the removed SQL Server path) | Evidence-based | `enrich_schema.py` | Pass sample values into the prompt |
| G16 | **Complex SQL (nesting, set operations, GROUP BY/HAVING) may need iterative correction** | Hypothesis | – | Break EX down by Spider hardness level |

---

## 14. Recommended Evidence for the Presentation

### 14.1 Evidence you can show today (no new experiments)

- The **real architecture diagram** (§1.2), with PLANNED boxes (Query Enhancement, BM25, RRF, Reranker) and REMOVED boxes (execution feedback, human feedback) visually distinguished from what actually runs today.
- The **retrieval-unit templates** with real examples (§2.3).
- The **enrichment prompt** (§3.1) and a before/after example built from a synthetic schema — since the enriched production schema example from the first report's data source (Team10BookShop) no longer exists in this repository, generate a fresh before/after pair by running `enrich_schema.py` once against a saved copy of a Spider schema dict, and cite that.
- The **rendered LLM prompt** and **feedback prompt** (§6, §8.2).
- The **validator probe table** (§9.2), as motivation for the next step.
- The **feedback-loop state machine** (attempts, prompt switch, terminal failure) — note that it is now single-mechanism (validation only); do not show the old three-tier (validation/execution/human) diagram as current state.
- The **evaluation harness design** (§10), including an honest "metric fidelity" note.

### 14.2 Experiments to run, per component (report only measured numbers)

**Retrieval (currently runnable only in part):**
- Full-schema vs Dense Schema-RAG (needs a bypass flag).
- Dense K ∈ {5, 10, 15, 20} (needs a `--k` flag), showing **recall@K of gold schema items** (from `dev.json`'s parsed `sql`), EX, and average prompt length.
- After implementation: Dense-only, BM25-only, Dense + BM25 (union), Dense + BM25 + RRF, Dense + BM25 + RRF + reranker, with the final context size fixed (e.g. 10).

**Metadata enrichment (needs the Spider hook of §3.5):**
- Raw vs enriched (EN) vs enriched (FA): recall@K and EX.
- Two or three qualitative examples of retrieved units before and after enrichment for the same question.
- For the cross-lingual claim: Persian questions (a translated subset — does not currently exist) × {raw, enriched}.

**Feedback:**
- `--max-iter` 1 / 2 / 4 with validation feedback (runnable now).
- Plus execution feedback on SQLite (needs the C4 addition — currently zero lines of code, not a port).
- Once a human-feedback design is rebuilt (C5): with vs without it, on whichever evaluation design was chosen.
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
4. **Hook `enrich_schema` into `spider_runner`** (§3.5), with a language option and per-DB caching.
5. **Add SQLite execution feedback** in `_infer_sql_with_feedback` (the prediction's own error only, via the already-existing `SpiderSQLiteExecutor`), and open databases read-only.
6. **Evaluation hygiene:**
   - set temperature 0 or a fixed seed,
   - use a stratified or random subset instead of the first N,
   - delete or version `chroma_db/spider_eval` per configuration,
   - record the model and embedding identifiers.
7. **If a human-feedback contribution is still wanted, design and build it fresh** (§12 C5) — do not attempt to resurrect the deleted chat-product code, which was never designed for batch evaluation.
8. Only then, if time allows: BM25 (`rank_bm25`), RRF and a cross-encoder reranker.

---

## 15. Final Technical Summary

**PROJECT GOAL**
Translate natural-language questions (Persian and English) into executable SQL over relational databases. Instead of placing the whole schema in the prompt, retrieve only the relevant schema elements (Schema-RAG), and improve correctness with validation and (planned) execution/human feedback. Spider 1.0 dev (SQLite, English) is the current controlled benchmark; the repository no longer contains any live production-database integration.

**BASELINE**
Single-pass generation with dense Top-15 schema retrieval, raw (placeholder) schema descriptions, temperature 0.1, no feedback — the Spider CLI's default mode. A "full schema, no retrieval" baseline is the natural reference but is **not implemented**. The design document's "Dense Only" baseline uses K=10, while the code uses 15.

**PROPOSED ARCHITECTURE**
Offline: SQLite DB → schema extraction → schema dict → (LLM metadata enrichment — implemented but disconnected) → per-element retrieval units → embeddings → ChromaDB.
Online: question → dense retrieval (Top-K units) → typed schema context → LLM → cleaning → validation (static only) → iterative feedback (validation only) → final SQL.
**Implemented and running today:** dense retrieval, validation feedback.
**Implemented but not wired in:** metadata enrichment (standalone tool).
**Removed** (existed in a now-deleted chatbot layer, would need to be rebuilt): execution-guided feedback, human semantic feedback.
**Planned (diagram or document only, never built):** query enhancement, BM25, RRF, reranker.

**OFFLINE PIPELINE**
- `SQLiteSchemaExtractor`: SQLite `sqlite_master` + PRAGMAs, generic type mapping, placeholder descriptions, tables without a PK fall back to their first three columns, all FKs labelled many-to-one.
- `enrich_schema.py`: Ollama `gemma3:4b`, temperature 0.1, zero-shot, Persian keyword descriptions, hierarchical (tables → columns). Works correctly and is compatible with the SQLite extractor's dict shape, but **nothing currently calls it**.
- `SchemaManager`: three unit types (unchanged templates):
  - Table: `"{T} Table: {desc}. شامل ستون های {keys}."`
  - Column: `"{T}.{C} Column: {meaning}, نوع داده {type}."`
  - Relation: `"Relation: {T1}.{c} ↔ {T2}.{c}. نوع رابطه many-to-one."`
- Embeds via a local SentenceTransformer (unrecorded model identity, normalised, CPU) or OpenAI `text-embedding-3-small`, into per-`db_id` Chroma collections cached under `./chroma_db/spider_eval/`.

**ONLINE PIPELINE**
For each Spider question, `run_spider_evaluation` → build/reuse chain for `db_id` → retrieve dense Top-15 → group into Tables/Columns/Relations → build the (always-English) system + user prompt → stream LLM tokens → clean → validate (static only) → on failure, feed back the last failed SQL + error + hint, same retrieved context, up to `--max-iter` total attempts → EM (string match) + EX (separate read-only-in-intent, actually read-write SQLite comparison, scoring-only) against gold.

**RETRIEVAL**
Dense-only Chroma kNN, K=15 hard-coded, no threshold, no metadata filters, no reranking, no query enhancement, distances discarded. BM25, RRF and the cross-encoder reranker are **not implemented** anywhere in the code or the git history — confirmed unchanged by this cleanup pass.

**LLM**
Local: Ollama `gemma4:12b` at `127.0.0.1:11434` (reset from an internal company host by this cleanup). Online: OpenAI `gpt-4o-mini`. Temperature 0.1 for both, no max_tokens/seed/num_ctx. Single-turn `[system, user]`, no few-shot, streaming. Four system prompts exist in `system_prompt.py`, but only the two English ones are ever reachable — the Persian pair (and its T-SQL-specific instruction) is currently dead code, reachable only if a future caller explicitly requests `culture="fa"`.

**FEEDBACK**
- (A) Static validation feedback: **implemented**, weak detector, the only mechanism that exists.
- (B) Execution feedback: **removed** — existed only in the deleted chatbot layer; needs to be built fresh against the already-existing `SpiderSQLiteExecutor`.
- (C) Human semantic feedback: **removed** — existed only in the deleted chatbot layer (chat UI + endpoints); needs a fresh design shaped for batch evaluation, not a resurrection of the chat-product code.
- (D) Regeneration: only the automatic kind (via A) remains. `max_iterations` = total attempts (`--max-iter`, default 4). Only the last failure is shown. Retrieval is not re-run.
- When all attempts fail: the run returns `None`, scored as wrong for both EM and EX.
- Empirically, the validator accepts `SELEC * FRM x`, incomplete SQL, non-SQL and hallucinated columns; it rejects correct queries containing `EXTRACT(… FROM col)` or columns named `*_from`; it can be bypassed with a CTE or multi-statement SQL.

**EVALUATION**
`cli_spider_eval.py`: Spider **dev.json only** (1,034 questions / 20 DBs); train, test and tables.json are unused. Modes are single-pass, `--feedback` and `--compare`; `--limit N` takes the first N samples (biased toward one database for small N). Culture is always `en`. There is no execution feedback and no human feedback. EM is normalised string equality; EX is a sorted, lowercased row-multiset comparison on a single (accidentally read-write-opened) database — neither matches the official Spider metrics. Validity risks: tuning-on-dev, possible pretraining contamination, stale Chroma caches with silently-skipped samples, evaluation-DB mutation risk, non-determinism. Nothing is saved per sample. One previously-flagged reproducibility bug (SQLAlchemy engines built at import time regardless of use) is now fixed by the cleanup.

**EXPERIMENTAL VARIABLES**
Switchable now: LLM (local/online via env), embedding model (via env + Chroma rebuild), validation-feedback on/off and its iteration count (`--max-iter`). Code constants: K (15), temperature (0.1), model names, enrichment model/language (though enrichment isn't wired in), culture (fixed to `en` at the one call site). Missing entirely: full-schema baseline, a K flag, BM25/RRF/reranker, query enhancement, the enrichment↔Spider hook, execution feedback (needs to be built from zero, not ported), human feedback (needs to be built from zero, not ported), few-shot enrichment, official metrics, token/error-rate metrics.

**IMPLEMENTED CONTRIBUTIONS**
1. Typed schema-unit dense retrieval (Schema-RAG) with a typed context layout.
2. Bounded validation-driven self-correction loop with a correction-specific prompt.
3. A reproducible Spider evaluation harness, single-pass vs feedback comparable via `--compare`, now free of chatbot-infrastructure coupling.

(Metadata enrichment is implemented as working, generic code, but is listed separately below because it is not wired into anything that currently runs — it is a half-built contribution, not a finished one.)

All of the above are system contributions. Their empirical benefit is **not yet measured** in the repository.

**PLANNED CONTRIBUTIONS**
- Wiring metadata enrichment into the Spider harness, and a raw-vs-enriched / cross-lingual ablation.
- Hybrid retrieval: BM25 + dense with RRF, cross-encoder reranking to a fixed final context size.
- Query enhancement.
- Execution-guided feedback on Spider — needs to be built fresh (the code that used to provide it in the chatbot layer is gone), directly against the already-existing `SpiderSQLiteExecutor`.
- Human-in-the-loop semantic feedback — needs a fresh design shaped for batch evaluation (simulated critic, oracle upper bound, or annotation pass), not a resurrection of the deleted chat product's endpoints.
- Few-shot (ICL) enrichment.
- Use of `join_purpose` and FK-path expansion.
- Retrieval re-run during feedback.
- Semantic validation.
- Token-usage, syntax-error-rate and semantic-error-rate metrics.
- Official Spider EM and test-suite EX.

**OPEN QUESTIONS**
1. Given that the human-feedback and execution-feedback mechanisms now have zero code (rather than "chatbot-only, unevaluated" code), does the thesis still want to claim both, one, or neither as contributions? Each now needs a from-scratch design and build, not a port.
2. Is the thesis claim about **Persian / cross-lingual enterprise NL2SQL** (where enrichment and, eventually, a Persian question set matter most) or about **generic Spider accuracy**? The evaluation design follows from this answer, and it also decides whether the now-unreachable Persian system prompts (§7.2) are worth keeping.
3. Which enrichment language should be used for the Spider hook (EN, to match the questions, or FA, to match the method's original motivation)?
4. Which embedding model is actually intended for `EMBEDDING_MODEL_DIR`? Nothing in the repository currently records this.
5. Will BM25, RRF and the reranker be implemented before the final defence? If not, the design-doc's numeric tables must be removed or explicitly relabelled as hypotheses.
6. Does Schema-RAG beat full-schema prompting on Spider's small schemas? If not, is there a larger-schema test bed planned (since the production-DB option that used to exist for this has been removed)?
7. What final context size and K will be used? The design doc says 10; the code uses 15.
8. Does the (currently nonexistent) feedback loop help once execution feedback is added, and how many iterations are worthwhile?

**RECOMMENDED PRESENTATION EMPHASIS**
- Present the progress honestly as: "**a focused Spider-research core, cleanly separated from an earlier chatbot prototype; the retrieval + validation-feedback pipeline works end-to-end; execution feedback, human feedback and hybrid retrieval are the next build items, not yet-unmeasured features.**" This is a more defensible framing than the first version of this report could offer, precisely because the scope is now narrower and cleaner.
- Strong points to show: the working offline+online Spider pipeline, the retrieval-unit design, the enrichment method (with a before/after example — regenerate one, since the previous example's source schema was removed), the validation-feedback loop, the harness's single-pass-vs-feedback comparison mode.
- Be explicit and unapologetic that execution feedback and human feedback are **not currently implemented** — say so once, clearly, rather than let a reviewer discover it. Frame it as a scope decision (chatbot removed to focus the thesis on the research core) rather than an oversight.
- Use §6 (unit fragmentation, join ambiguity, cross-lingual mismatch) and §9.2 (validator probe) as **motivation slides** for the planned components.
- Show the concrete **experiment plan** of §14.2 and the **evaluation-fidelity fixes** of §14.3.
- Report only numbers produced by the harness, together with their exact configuration (LLM, embedding model, K, feedback mode, sample count, metric definition).

---

### Appendix A: File map (post-cleanup)

| Concern | File(s) |
|---|---|
| Entry point | `cli_spider_eval.py` |
| Spider evaluation | `app/spider_eval/{spider_loader,sqlite_schema_extractor,spider_runner,spider_evaluator,spider_sqlite_executor}.py` |
| Orchestration, retrieval, prompts, LLM | `app/nl2sql_chain.py`, `app/system_prompt.py` |
| Retrieval units | `app/schema_manager.py` |
| Embedding + vector store (partly orphaned, see §1.1/§2.4) | `app/utilities.py` |
| Validation + feedback loop (validation only) | `app/sql_validator.py` |
| Metadata enrichment (standalone, disconnected) | `enrich_schema.py` |
| Config | `app/dotenv.py`, `.env.template`, `requirements.txt` |
| Design docs (contain planned or illustrative content, not verified results) | `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md`, `docs/diagrams/*.png` |
| This report | `docs/thesis/NL2SQL_Technical_Research_Report.md` |

**Removed in the cleanup** (no longer in the repository; see the revision note at the top of this file): `frontend/` (React chat UI), `backend/main.py` (FastAPI chatbot server), `backend/app/models.py` / `schemas.py` (chat-log ORM and HTTP schemas), `backend/extract_schema.py` (SQL Server extractor with hard-coded credentials), `backend/data_schema/` (production schema JSON), `backend/schema_text.txt` (debug dump), `backend/ARCHITECTURE.md` (stale chatbot architecture doc), `backend/prompt.md` (a one-off code-gen spec), `backend/Dockerfile`/`.dockerignore`.
