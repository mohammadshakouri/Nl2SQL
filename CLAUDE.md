# NL2SQL with Schema-RAG (thesis project)

Natural-language-to-SQL for a thesis. The code is an evaluation harness for **Spider 1 dev (1034 questions)**: it retrieves schema units for a question, asks an LLM for SQLite SQL, optionally repairs it in a feedback loop, and scores execution accuracy (EX). Almost all work is running paid evaluations and analysing their logs.

## Language
The user writes Persian. Answer in Persian; keep code, identifiers, commit messages and this file in English. Thesis documents `docs/thesis/*_fa.md` are Persian.

## How it works
1. `app/schema_manager.py` turns each database into **units** (table / column / relation), embedded into one ChromaDB collection per database (`chroma_db/`, git-ignored).
2. `app/nl2sql_chain.py`: dense retrieval of the Top-K units (K=15), prompt assembly, LLM call. OpenAI (default model `gpt-6-luna`, temperature 1, reasoning_effort low) or Ollama (`USE_LOCAL_LLM`). Prompts: `app/system_prompt.py`.
3. `app/sql_validator.py` + `SQLFeedbackLoop`: with `--feedback` retries on static errors; with `--exec-feedback` also on SQLite execution errors (max 4 attempts). Attempt 1 is the single-pass answer, so one run gives paired single-pass and loop scores.
4. `app/spider_eval/`: `spider_runner.py` (the run), `spider_sqlite_executor.py` (**the scorer**), `run_log.py` (log format, `check`/`brief`/`prompt`), `error_analysis.py`.

## Commands
```bash
python cli_spider_eval.py --spider_path ./spider --exec-feedback --limit 20 --tag pilot   # pilot first
python cli_spider_eval.py --spider_path ./spider --exec-feedback --tag all_samples        # full run
python cli_spider_eval.py --spider_path ./spider --resume runs/<run_dir>                  # continue an interrupted run
python -m app.spider_eval.run_log check runs/<run_dir>                                    # verify a log
python -m app.spider_eval.error_analysis runs/<run_dir> --check-only                      # validate error_labels.tsv
python -m app.spider_eval.error_analysis runs/<run_dir> --spider_path ./spider            # all analysis numbers
```
Config comes from `.env` (copy `.env.template`: `OPENAI_API_KEY`, `USE_LOCAL_LLM`, `USE_LOCAL_EMBEDDING`, `EMBEDDING_MODEL_DIR`). The repo has no test suite and no linter; verify with `run_log check`, `python -m py_compile`, and a `--limit` pilot.

## Data and logs
- **Spider data is not in the repo**: `./spider/` needs `dev.json`, `tables.json`, `database/<db_id>/<db_id>.sqlite`. It is not git-ignored: **never `git add` it**.
- Each run writes `runs/<time>_<mode>_<model>_k<K>[_tag]/`. Format: `docs/run-log-format.md`. `samples.jsonl` is the source of truth (append-only); metrics are recomputed from it. Treat committed run directories as evidence: do not edit them.
- `error_labels.tsv` next to a log is **judgement** (H scorer / G gold or ambiguity / M model; written by reading each failing sample). `error_analysis.py` computes everything else mechanically. Report: `docs/thesis/Error_Analysis_Full_Run_fa.md`.
- `sample_index` is 0-based (= `idx` in `brief.jsonl`); `schema_units.json[db_id]` resolves unit ids (`column_3`) to tables and columns; ids are only unique within one database.

## Rules
- Work on `main`. **Do not commit or push unless asked**: the user reviews diffs locally first. Never put API keys in files.
- A full run costs money (~730k tokens, ~47 min for 1034 samples). Pilot with `--limit` first, ask before a full run, and commit before a run that will be reported (the manifest records `code.dirty`).
- Changing prompts, unit text templates, the scorer or `dev.json` changes the run **fingerprint**: old logs then refuse `--resume`. That is intended.
- Scoring: EX ignores row order, case and column order; invalid UTF-8 is dropped. EX is the only metric; the old string-match "EM" was deliberately removed (it was not Spider's EM), so do not add it back. Ties at `ORDER BY ... LIMIT 1` and wrong gold queries are not handled (they are the G category in the analysis).
- The user is on Windows.

## State (last full run: gpt-6-luna, K=15, exec-feedback, `runs/20261120T164326Z_..._all_samples`)
EX 69.63% (single pass 64.41%) with the **old** scorer; the scorer fix is expected to give about 73-74%, to be confirmed by a new run (needs `./spider` locally). Of 314 failures: H 47, G 135 (82 arguable), M 132. Findings that drive the next steps:
- 107 of 115 first-attempt rejections are SQLite dialect errors (`FETCH FIRST`, `>= ALL`); the system prompt says "standard SQL" and never names SQLite.
- 73 of 132 model errors had a needed column/table missing from the Top-15 (model error rate 46% vs 7% when retrieval is complete); join keys have the lowest recall (86%).
- The loop never sees semantic errors (all 314 failures ran without error).

Ideas, not decided: SQLite hint in the system prompt; "return only the requested columns" rule (31 projection errors); complete retrieval (FK closure / larger K); value grounding; lint for `WHERE 1 = 0` / `NULL AS`; an "oracle schema" run to test whether missing units cause the errors. Details and expected gains: report section 8.

## Known gaps
`--limit N` takes the first N samples, not a random sample. The static validator mistakes an alias in `EXTRACT(YEAR FROM r.col)` for a table. `enrich_schema.py` is unwired and still generates Persian text. The original design document is `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md`.
