# Spider run log format (version 2)

Every `cli_spider_eval.py` run writes one directory, `runs/<UTC timestamp>_<mode>_<model>_k<K>[_<tag>]/`:

| file | what it is |
|---|---|
| `samples.jsonl` | **The source of truth.** One compact JSON line per sample. Append-only; each line is flushed and fsync'ed when the sample finishes. |
| `brief.jsonl` | One short line per sample (question, gold, prediction, outcome, row counts, reason). Rewritten at the end of every session; made for reading failures. |
| `manifest.json` | What was run (settings, model, prompts, code version, dataset hash, environment), the sessions that wrote the log, and the final results. |
| `schema_units.json` | For each database, every retrieval unit that was indexed: `id`, `kind`, the schema element it stands for, and its text. |
| `console.txt` | A copy of everything printed to the terminal, including the output before the run started (settings, preflight). |

The metrics (EX, failures, tokens) are **recomputed from `samples.jsonl`**, never accumulated separately, so the log can always be re-aggregated or re-scored offline from the stored SQL.

**Nothing that can be recomputed exactly is stored per sample.** The text of the retrieved units is looked up by id in `schema_units.json`, and the user prompt of each attempt is rebuilt from the question, the retrieved ids and the earlier attempts; `prompt_sha` per attempt proves the rebuilt text is identical (`check` does this for every attempt of the run). A full 1,034-sample run is on the order of 1–2 MB.

## Running, checking, resuming

```bash
# 1. small pilot: proves the model, the log and the token counts work
python cli_spider_eval.py --spider_path ./spider --exec-feedback --limit 20 --tag pilot

# 2. verify the log (also works on a partial run)
python -m app.spider_eval.run_log check runs/<run_dir>

# 3. continue the same run to the whole dev set (finished samples are NOT re-run)
python cli_spider_eval.py --spider_path ./spider --resume runs/<run_dir>
```

Other commands:

```bash
python -m app.spider_eval.run_log brief  runs/<run_dir>                  # rewrite brief.jsonl
python -m app.spider_eval.run_log prompt runs/<run_dir> <sample_index> [attempt]   # show the exact prompt sent
```

* A run that stops for any reason (Ctrl-C, SIGTERM, crash, network loss) leaves a valid log; `--resume` continues it.
  `--limit` is not remembered: without it a resumed run goes on to the whole dev set.
* On resume, samples that failed on **infrastructure** (`llm_error`, `retrieval_error`, `internal_error`, `schema_build_failed`) are re-run; their old records stay in the file and the newer record supersedes them. Model failures such as an empty response are kept as the model's answer.
* `--resume` takes model, temperature, reasoning effort, K, mode and max attempts from the manifest, and refuses to continue if the prompts, the prompt-building code, the retrieval-unit text templates, the embedding model, the scorer or `dev.json` changed (the *fingerprint* in the manifest), or if the log was written in another format version.
* A feedback-mode run also contains the single-pass answer: attempt 1 uses the single-pass prompt, and `scoring.first_*` scores it, so one run gives both numbers, paired.
* Chroma collections left by earlier runs are reused only if they hold exactly the units the current code produces; a collection with outdated units (e.g. from an older text template) is rebuilt automatically and the run prints a note. `schema_units.json` records `collection.reused` / `collection.rebuilt_stale`. The collection does not record which embedding *model* made its vectors, so after changing the embedding model use `--rebuild-index` once.
* `check` warns when `code.dirty` is true: the run used uncommitted changes to tracked or new source files (the `runs/` directory itself is not counted). Commit before a run you intend to report.

## How a prediction is scored

`EX` compares the result of the predicted SQL with the result of the gold SQL, both executed on the SQLite database (`app/spider_eval/spider_sqlite_executor.py`, `results_match`):

* rows are compared as a multiset: their order does not matter, duplicates do;
* values are compared as trimmed, lower-case text, NULL as the empty string;
* **the order of the columns does not matter** (Spider's own `result_eq` does the same), but every gold column must appear exactly once;
* TEXT values with invalid UTF-8 are decoded with the bad bytes dropped (also what Spider's test-suite does), so a gold query over such a database (e.g. `wta_1`) can run; the same decoding applies to the executions of the feedback loop.

Not handled: ties at `ORDER BY ... LIMIT 1` (gold and prediction may legitimately pick different rows) and gold queries that are themselves wrong.

## `samples.jsonl` records

Read it with last-record-wins per `sample_index`:

```python
import json
latest = {}
for line in open("runs/<run_dir>/samples.jsonl", encoding="utf-8"):
    r = json.loads(line)
    latest[r["sample_index"]] = r
```

| field | meaning |
|---|---|
| `sample_index` | 0-based position in `dev.json` (add 1 for the row numbers used in earlier analyses) |
| `db_id`, `question`, `gold_sql` | the sample |
| `status` | `scored` (SQL produced and scored), `no_sql` (no usable SQL), `skipped` (SQLite file missing or schema build failed), `internal_error` (a bug inside the sample; traceback in `error`) |
| `failure_kind` | for `no_sql`/`internal_error`: `llm_error`, `empty_response`, `retrieval_error`, `no_retrieval`, `internal_error` |
| `skip_reason` | for `skipped`: `sqlite_missing`, `schema_build_failed` |
| `error` | why there is no SQL, or why the feedback loop gave up |
| `retrieved`, `distances` | the Top-K unit ids (`table_3`, `column_12`, `relation_1`, …; resolve them in `schema_units.json`), best first, and their distances (4 decimals) |
| `attempts[]` | one entry per LLM call, see below |
| `final_sql` | the SQL that was scored |
| `final_attempt` | which attempt it came from (1-based); `fallback` is true when no attempt passed the checks and attempt 1 was kept |
| `recovered` | a retry passed the checks after attempt 1 was rejected |
| `scoring` | `ex`, `kind`, `first_ex`, `permuted` |
| `results` | `gold`, `final`, `first`: execution snapshots (below); `first` only when attempt 1 differs from the final SQL |
| `ms` | wall time for the sample |
| `session` | which process invocation wrote the record |

`scoring.permuted` is true when the final SQL matched the gold result only after its columns were reordered (the scorer ignores column order, see below); the end-of-run summary counts these. `scoring.kind` is `null` on a match, otherwise `gold_failed`, `pred_failed` or `result_mismatch` (the categories of the earlier log analysis). The text of the reason (e.g. `Result mismatch: predicted 5 row(s), gold 5 row(s)`) is rebuilt from `kind` and `results` by `run_log.describe_outcome`.

**`attempts[]`** (position + 1 is the attempt number): `sql` (cleaned), `raw_output` (exactly what the model returned), `prompt_sha` (12 hex chars of the user prompt sent), `tokens` (`{prompt, completion[, reasoning][, cached]}` as reported by the provider, `null` if not reported), `ms` (call latency), `rejected` (`null`, or `{stage: "static"|"execution", error}` when the checks of the feedback loop refused the SQL), `exec_rows` (rows returned when the query was executed during `--exec-feedback`). Optional keys: `finish` (only when the finish reason is not `stop`, e.g. `length`), `error` (the LLM call failed; the other fields are then empty).

**Execution snapshot** (`results.*`): `{ok: false, error}` for a query that failed, otherwise `n_rows`, `n_cols`, `rows` (the first 20 rows, cells capped at 200 chars), `truncated` (only when there were more rows) and `sha` (hash of the complete result with rows sorted). A result of 20 rows or fewer is stored in full, so it can be re-scored offline exactly.

## `schema_units.json`

`{db_id: {db_id, summary, collection, units[]}}`. Each unit has `id`, `kind` and `text`, plus:

| kind | extra fields |
|---|---|
| `table` | `table`, `key_columns` |
| `column` | `table`, `column`, `data_type` |
| `relation` | `source_table`, `source_column`, `target_table`, `target_column` |

It is what makes the per-sample records small, and it is the universe needed for retrieval analysis: Recall@K (map the tables and columns of the gold SQL to unit ids and intersect with `retrieved`), which units were never retrieved, and how much K prunes (e.g. K=15 of 28 units).

## `manifest.json`

`config` (mode, k, max_attempts, execution_feedback), `llm` (provider, model, temperature, reasoning_effort, host, timeout, retries; never the API key), `embedding`, `prompts` (full system prompts + hashes), `retrieval_units` (hash of the unit text templates), `scorer` (hash of the comparison code), `dataset` (`dev.json` sha256, sample count), `code` (git commit, branch, `dirty`), `environment` (Python, SQLite, package versions), `fingerprint` (what must match to resume), `sessions[]` (one per process: argv, limit, start/end, status `complete` / `interrupted` / `failed`, wall time, code version), and `results` (metrics, token totals, status counts).

## Error analysis of a finished run

```bash
python -m app.spider_eval.error_analysis runs/<run_dir> --check-only                  # validate error_labels.tsv
python -m app.spider_eval.error_analysis runs/<run_dir> --spider_path ./spider        # tables + error_analysis.json
```

Two files are kept next to the log: `error_labels.tsv` (one hand-made label per failing sample: category `H` scorer / `G` gold or ambiguity / `M` model, a subtype, an `arguable` flag) and `error_analysis.json` (every number of the analysis, recomputed from the log, `dev.json`/`tables.json` and the labels: retry and dialect statistics, Recall@K, hardness, per-database results, adjusted EX). The labels are judgement; everything else is a pure function of the log. The report built from them is `docs/thesis/Error_Analysis_Full_Run_fa.md`.

## What is not logged

API keys; the prompt text itself (rebuild it with `run_log prompt`); the unit text per sample; per-sample timestamps and timing breakdowns; embedding-API token usage.
