# NL2SQL with Schema-RAG (thesis project)

Evaluation harness for NL2SQL on **Spider 1 dev (1034 questions)** and **BIRD dev (1534)**: retrieve schema units for a question, ask an LLM for SQLite SQL, optionally repair it in a feedback loop, score execution accuracy (EX). Most work is running paid evaluations and analysing their logs.

## Language
The user writes Persian. Answer in Persian; keep code, identifiers, commit messages and this file in English. `docs/thesis/*_fa.md` are Persian.

## How it works
1. `app/schema_manager.py`: each database becomes **units** (table / column / relation), embedded into one ChromaDB collection per database (`chroma_db/`, git-ignored).
2. `app/nl2sql_chain.py`, `app/retrieval.py`: hybrid retrieval, prompt assembly, LLM call (OpenAI, or Ollama with `USE_LOCAL_LLM`). Retrieval: dense Top-K + BM25 Top-K → RRF merge, capped at ceil(1.5·K) units. `--rerank` (off by default) reranks that list with a cross-encoder (`BAAI/bge-reranker-v2-m3` from the local HuggingFace cache, or `RERANKER_MODEL_DIR`) and keeps the best K. Completion then appends, for every retrieved table, its key columns and a name column, and the relations and foreign-key columns between retrieved tables; so the prompt holds more than K units. Prompts: `app/system_prompt.py`.
3. `app/sql_validator.py` + `SQLFeedbackLoop`: `--feedback` retries on static errors, `--exec-feedback` also on SQLite execution errors (max 4 attempts). Attempt 1 is the single-pass answer, so one run gives paired single-pass and loop scores.
4. `app/evaluation/`: `benchmarks.py` (everything that differs between Spider and BIRD), `runner.py` (the run), `executor.py` (the scorers), `run_log.py` (log format, `check`/`brief`/`prompt`), `error_analysis.py`. A new dataset means a new entry in `benchmarks.py`, not a new pipeline.

## Commands
```bash
python cli_eval.py --dataset spider --exec-feedback --limit 20 --tag pilot   # pilot first (spider is the default dataset)
python cli_eval.py --dataset spider --exec-feedback --tag all_samples        # full run
python cli_eval.py --dataset bird --exec-feedback --limit 20 --tag pilot     # BIRD: evidence on, raw schema
python cli_eval.py --dataset bird --exec-feedback --descriptions             # BIRD with database_description/*.csv in the units
python cli_eval.py --exec-feedback --rerank                                  # reranker on (off by default)
python cli_eval.py --resume runs/<run_dir>                                   # continue an interrupted run (settings come from the log)
python -m app.evaluation.run_log check runs/<run_dir>                        # verify a log
python -m app.evaluation.error_analysis runs/<run_dir> --check-only          # validate error_labels.tsv
python -m app.evaluation.error_analysis runs/<run_dir> --data_path ./Spider  # analysis numbers (./BIRD for a BIRD run)
```
`--data_path` overrides the dataset folder (default `./Spider` or `./BIRD`). Config comes from `.env` (copy `.env.template`). No test suite, no linter: verify with `run_log check`, `python -m py_compile` and a `--limit` pilot.

## Data and logs
- `Spider/` and `BIRD/` are not in the repo and are git-ignored: **never `git add` them**. Spider needs `dev.json`, `tables.json`, `database/<db_id>/<db_id>.sqlite`; BIRD needs `dev.json`, `dev_databases/<db_id>/<db_id>.sqlite` and, for `--descriptions`, `dev_databases/<db_id>/database_description/*.csv`.
- Each run writes `runs/<time>_<dataset>_<mode>_<model>_k<K>[_tag]/` (format: `docs/run-log-format.md`). `samples.jsonl` is the source of truth; metrics are recomputed from it. Committed run directories are evidence: do not edit them. Runs from before BIRD support have no dataset in the name; `check` reads them as Spider.
- `error_labels.tsv` next to a log is judgement (H scorer / G gold or ambiguity / M model). `error_analysis.py` computes everything else; it may add `error_analysis.json` and `result_relations.json` next to a log, never edit the log.
- `sample_index` is 0-based (= `idx` in `brief.jsonl`); `schema_units.json[db_id]` resolves unit ids (`column_3`) to tables and columns; ids are only unique within one database.

## Rules
- Work on `main`. **Do not commit or push unless asked.** Never put API keys in files.
- A full run costs money: pilot with `--limit` first, ask before a full run, commit before a run that will be reported (the manifest records `code.dirty`).
- Changing prompts, unit text templates, the scorer, `dev.json`, the retrieval code or settings (including `--rerank`), or a BIRD option (`--no-evidence`, `--descriptions`) changes the run **fingerprint**: old logs then refuse `--resume`. That is intended.
- Scoring (chosen by the dataset, recorded in the manifest): **Spider** EX compares rows as a multiset, ignoring row order, case and column order. **BIRD** EX is `set(pred_rows) == set(gold_rows)`: row order and duplicates do not matter, case and column order do. The two numbers are not comparable. EX is the only metric; the old string-match "EM" was removed on purpose, do not add it back. Ties at `ORDER BY ... LIMIT 1` and wrong gold queries are not handled (the G category in the analysis).
- BIRD: the question's `evidence` goes into the prompt **and** the retrieval query (`--no-evidence` turns both off). `--descriptions` is an ablation, not BIRD's standard setting. `dev_tied_append.json` is unused. Two gold queries (#518 card_games, #701 codebase_community) exceed the 30 s timeout and always count as `gold_failed`.
- The user is on Windows.

## Baselines
The last full runs predate hybrid retrieval (dense Top-K only): Spider `runs/20261120T164326Z_..._all_samples` (old scorer; `runs/20261123T094706Z_spider_..._all_after_fix_scorer` is a rerun with the fixed scorer) and BIRD `runs/20261123T110920Z_bird_..._k30_all_samples_with_desc`. Their error analysis, findings and improvement ideas are in `docs/thesis/Error_Analysis_Full_Run_fa.md` (Spider) and `docs/thesis/Error_Analysis_BIRD_Full_Run_fa.md` (BIRD).

## Known gaps
`--limit N` takes the first N samples, not a random sample (BIRD's `dev.json` is ordered by database). The static validator mistakes an alias in `EXTRACT(YEAR FROM r.col)` for a table. `enrich_schema.py` is unwired and still generates Persian text. The original design document is `Overall Architecture of the Proposed RAG-based NL2SQL Framework.md`.
