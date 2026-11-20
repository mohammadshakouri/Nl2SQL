# Spider run log format

Every `cli_spider_eval.py` run writes one directory, `runs/<UTC timestamp>_<mode>_<model>_k<K>[_<tag>]/`:

| file | what it is |
|---|---|
| `samples.jsonl` | **The source of truth.** One JSON line per sample with everything observed for it. Append-only; each line is flushed and fsync'ed when the sample finishes. |
| `manifest.json` | What was run (settings, model, prompts, code version, dataset hash, environment), the sessions that wrote the log, and the final results. |
| `schema_units.json` | For each database: every retrieval unit (`id`, `kind`, `text`) that was indexed, plus how its Chroma collection was built (`reused`, `rebuilt_stale`). |
| `console.txt` | A copy of everything printed to the terminal, including the output before the run started (settings, preflight). |

The metrics (EM, EX, failures, tokens) are **recomputed from `samples.jsonl`**, never accumulated separately, so the log can always be re-aggregated or re-scored offline from the stored SQL.

## Running, checking, resuming

```bash
# 1. small pilot (20 samples): proves the model, the log and the token counts work
python cli_spider_eval.py --spider_path ./spider --model <MODEL> --feedback --exec-feedback --limit 20 --tag pilot

# 2. verify the log (also works on a partial run)
python -m app.spider_eval.run_log check runs/<run_dir>

# 3. continue the same run to the whole dev set (finished samples are NOT re-run)
python cli_spider_eval.py --spider_path ./spider --resume runs/<run_dir>
```

* A run that stops for any reason (Ctrl-C, SIGTERM, crash, network loss) leaves a valid log; `--resume` continues it.
  `--limit` is not remembered: without it a resumed run goes on to the whole dev set.
* On resume, samples that failed on **infrastructure** (`llm_error`, `retrieval_error`, `internal_error`, `schema_build_failed`) are re-run; their old records stay in the file and the newer record supersedes them. Model failures such as an empty response are kept as the model's answer.
* `--resume` takes model, temperature, K, mode and max attempts from the manifest, and refuses to continue if the prompts, the prompt-building code, the retrieval-unit text templates, the embedding model or `dev.json` changed (the *fingerprint* in the manifest).
* A feedback-mode run also contains the single-pass answer: attempt 1 uses the single-pass prompt, and `scoring.first_attempt_*` scores it, so one run gives both numbers, paired.
* Chroma collections left by earlier runs are reused only if they hold exactly the units the current code produces; a collection with outdated units (e.g. from an older text template) is rebuilt automatically and the run prints a note. `schema_units.json` records `collection.reused` / `collection.rebuilt_stale`. The collection does not record which embedding *model* made its vectors, so after changing the embedding model use `--rebuild-index` once.
* The run directory is not git-ignored. Estimate: roughly 10–20 MB of `samples.jsonl` for the full 1,034 samples (check the pilot's file size and scale it).

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
| `mode` | `single-pass` or `feedback` |
| `status` | `scored` (SQL produced and scored), `no_sql` (no usable SQL), `skipped` (SQLite file missing or schema build failed), `internal_error` (a bug inside the sample; has a traceback in `error`) |
| `failure_kind` | for `no_sql`/`internal_error`: `llm_error`, `empty_response`, `retrieval_error`, `no_retrieval`, `internal_error` |
| `skip_reason` | for `skipped`: `sqlite_missing`, `schema_build_failed` |
| `error` | why there is no SQL, or why the feedback loop gave up |
| `retrieval` | `k`, `ms`, `n_units`, and `units[]` = `{rank, id, kind, distance, text}` (ids like `table_3`, `column_12`, `relation_1`, resolvable through `schema_units.json`) |
| `attempts[]` | one entry per LLM call, see below |
| `n_attempts` | number of LLM calls |
| `first_sql` | cleaned SQL of attempt 1 (= the single-pass answer) |
| `final_sql`, `final_attempt`, `final_source` | the SQL that was scored; `final_source` is `attempt_N` or `attempt_1_fallback` (no attempt passed the checks) |
| `recovered` | a retry passed the checks after attempt 1 was rejected |
| `scoring` | `em`, `ex`, `ex_error`, `ex_error_kind`, `first_attempt_em`, `first_attempt_ex`, `first_attempt_ex_error` |
| `results` | `gold`, `final`, `first`: execution snapshots (below); `first` only when attempt 1 differs from the final SQL |
| `usage` | token counts summed over the sample's attempts (`prompt_tokens`, `completion_tokens`, `total_tokens`, and `reasoning_tokens` / `cached_tokens` when the provider reports them) |
| `timing_ms` | `total`, `retrieval`, `llm`, `scoring` |
| `started_at`, `finished_at`, `session` | UTC timestamps; which process invocation wrote the record |

`scoring.ex_error_kind` is `null` on a match, otherwise `gold_failed`, `pred_failed` or `result_mismatch` (these are the categories of the earlier log analysis).

**`attempts[]`**: `attempt`, `system_prompt` (`first` / `feedback`; the texts are in `manifest.prompts`), `user_prompt` (exact text sent, including any feedback), `llm` {`model`, `raw_output`, `finish_reason`, `usage` (as reported by the provider), `latency_ms`, `ttft_ms`, `error`, `error_type`}, `sql` (cleaned), `sql_empty`, `check` {`ran`, `valid`, `stage` (`static` or `execution`), `error`}, `exec` (snapshot of the query's execution during the feedback check, when `--exec-feedback`).

**Execution snapshot**: `ok`, `error`, `ms`, `n_rows`, `n_cols`, `rows_head` (first 50 rows, cells capped at 200 chars), `rows_truncated`, `rows_sha256` (full result as returned) and `rows_sha256_sorted` (rows sorted), so two results can be compared without storing them in full.

## `manifest.json`

`config` (mode, k, max_attempts, execution_feedback), `llm` (provider, model, temperature, host, timeout, retries; never the API key), `embedding`, `prompts` (full system prompts + hashes), `dataset` (`dev.json` sha256, sample count), `code` (git commit, branch, `dirty`), `environment` (Python, SQLite, package versions), `fingerprint` (what must match to resume), `sessions[]` (one per process: argv, limit, start/end, status `complete` / `interrupted` / `failed`, wall time), and `results` (metrics, token totals, status counts).

If `code.dirty` is true the run used uncommitted changes: commit before a run you intend to report.

## What is not logged

API keys; the full `schema_context` as a separate field (it is inside `attempts[].user_prompt`); embedding-API token usage.
