"""
Spider Runner

Main evaluation loop for the Spider 1 benchmark.

Architecture
------------
For each Spider sample the runner:
1. Extracts the SQLite schema → SchemaManager-compatible JSON dict
2. Loads (or reuses) a ChromaDB collection named ``Schema_spider_<db_id>``
3. Instantiates NL2SQLChain with that collection
4. Retrieves the Top-K schema units and generates SQL, either single-pass or
   with the feedback/retry loop (static validation, optionally plus the
   predicted query's own SQLite execution error)
5. Evaluates Exact Match and Execution Accuracy
6. Writes one complete record for the sample to the run log (see run_log.py)
   and, at the end, returns metrics recomputed from the log
"""

import inspect
import os
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

import chromadb

import app.dotenv as env
import app.utilities as utils
from app.utilities import LocalSTEmbeddingFunction
from app.schema_manager import SchemaManager
from app.nl2sql_chain import NL2SQLChain, get_llm_settings
from app.sql_validator import SQLFeedbackLoop
from app.system_prompt import SYSTEM_PROMPT_NL2SQL, SYSTEM_PROMPT_NL2SQL_FEEDBACK
from app.spider_eval.llm_io import LLMCall, call_llm, describe_exc, token_counts
from app.spider_eval.run_log import (
    MAX_RAW_OUTPUT_CHARS,
    RETRYABLE_FAILURE_KINDS,
    SCHEMA_VERSION,
    RunLog,
    environment_info,
    git_info,
    result_snapshot,
    sha256_file,
    sha256_text,
    summarize_records,
    token_totals,
    utc_now,
)
from app.spider_eval.spider_loader import SpiderSample, get_sqlite_path
from app.spider_eval.sqlite_schema_extractor import SQLiteSchemaExtractor
from app.spider_eval.spider_sqlite_executor import CompareResult, QueryRun, SpiderSQLiteExecutor
from app.spider_eval.spider_evaluator import exact_match
from chromadb.utils import embedding_functions

USE_LOCAL_EMBEDDING = env.use_local_embedding
OPENAI_API_KEY = env.openai_api_key
EMBEDDING_MODEL_DIR = env.embedding_model_dir

# ChromaDB directory dedicated to Spider evaluation so that production
# collections are never contaminated.
_SPIDER_CHROMA_DIR = os.path.join(
    utils.CHROMADB_PERSIST_DIRECTORY, "spider_eval"
)


# ---------------------------------------------------------------------------
# Embedding function factory (mirrors nl2sql_chain.py)
# ---------------------------------------------------------------------------

def _build_embedding_fn():
    if USE_LOCAL_EMBEDDING:
        return LocalSTEmbeddingFunction(EMBEDDING_MODEL_DIR, device="cpu")
    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=OPENAI_API_KEY,
        model_name=utils.OPENAI_EMBEDDING_MODEL_NAME,
    )


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------

def _build_collection(
    chroma_client: chromadb.PersistentClient,
    embedding_fn,
    db_id: str,
    schema_dict: dict,
    batch_size: int = 10,
    rebuild: bool = False,
) -> Tuple[str, dict]:
    """
    Create (or retrieve) a Chroma collection for the given Spider db_id and
    populate it with schema embeddings if it is empty.

    Args:
        chroma_client: Open ChromaDB persistent client.
        embedding_fn: Embedding function instance.
        db_id: Spider database identifier.
        schema_dict: Schema dict from SQLiteSchemaExtractor.extract().
        batch_size: Upsert batch size.
        rebuild: Drop an existing collection first, so every unit is embedded
                 afresh with the current embedding model.

    Returns:
        (collection name, info). ``info["reused"]`` is True when the collection
        already held units from an earlier run, and ``info["docs_match"]`` says
        whether those units are identical to the ones the current schema
        produces. Reused vectors were made by whatever embedding model was
        active then, which the collection itself does not record.
    """
    collection_name = f"Schema_spider_{db_id}"

    if rebuild:
        try:
            chroma_client.delete_collection(collection_name)
        except Exception:
            pass  # nothing to drop

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
    )

    manager = SchemaManager()
    manager.load_schema_from_dict(schema_dict)
    ids, documents = manager.get_all_embedding_texts()

    # Only populate if the collection is empty to avoid re-embedding on
    # repeated runs of the same db_id (possible within a single dev pass
    # because multiple questions share one database).
    stored_count = collection.count()
    reused = stored_count > 0
    if reused:
        stored = collection.get(ids=ids)
        stored_docs = dict(zip(stored["ids"], stored["documents"]))
        docs_match = stored_count == len(ids) and all(
            stored_docs.get(unit_id) == doc for unit_id, doc in zip(ids, documents)
        )
    else:
        for i in range(0, len(ids), batch_size):
            collection.upsert(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
            )
        docs_match = True

    info = {
        "name": collection_name,
        "reused": reused,
        "docs_match": docs_match,
        "n_units_expected": len(ids),
        "n_units_stored": collection.count(),
    }
    return collection_name, info


def _schema_units(schema_dict: dict) -> List[dict]:
    """Every retrieval unit of a schema as {"id", "kind", "text"}."""
    manager = SchemaManager()
    manager.load_schema_from_dict(schema_dict)
    ids, documents = manager.get_all_embedding_texts()
    return [
        {"id": unit_id, "kind": unit_id.split("_")[0], "text": text}
        for unit_id, text in zip(ids, documents)
    ]


# ---------------------------------------------------------------------------
# Inference result
# ---------------------------------------------------------------------------

@dataclass
class InferenceResult:
    """Outcome of generating SQL for one question."""
    sql: Optional[str]
    """SQL to score, or None when no usable SQL was produced."""
    error: Optional[str] = None
    """Why ``sql`` is None, or why the feedback loop gave up."""
    failure_kind: Optional[str] = None
    """Short category of the failure when ``sql`` is None."""
    first_sql: Optional[str] = None
    """First attempt; identical prompt to single-pass inference."""
    attempts: int = 0
    """Number of LLM calls made."""
    recovered: bool = False
    """True when a retry passed the checks after attempt 1 was rejected."""
    notes: List[str] = field(default_factory=list)
    """Per-attempt feedback messages, printed in verbose mode."""
    retrieval: Optional[dict] = None
    """The retrieval step (Top-K units with ids and distances) for the run log."""
    attempt_log: List[dict] = field(default_factory=list)
    """One dict per LLM attempt (prompt, raw output, usage, checks) for the run log."""
    final_attempt: Optional[int] = None
    """Number of the attempt whose SQL was kept (1 also when attempt 1 is the fallback)."""
    final_source: Optional[str] = None
    """``attempt_N`` (passed the checks / single-pass) or ``attempt_1_fallback``."""


def _is_empty_sql(sql: Optional[str]) -> bool:
    # clean_sql_output() turns an empty LLM response into ";"
    return not sql or not sql.strip().strip(";").strip()


def _retrieve_context(chain: NL2SQLChain, question: str, k: int):
    """Return (schema_context, retrieval trace, None) or (None, trace, failed InferenceResult)."""
    started = time.perf_counter()
    try:
        units = chain.retrieve_schema_units(question, n_results=k)
    except Exception as exc:
        trace = {"k": k, "ms": _ms(started), "n_units": 0, "units": [],
                 "error": describe_exc(exc)}
        return None, trace, InferenceResult(
            None, f"schema retrieval failed: {describe_exc(exc)}", "retrieval_error",
            retrieval=trace,
        )
    trace = {
        "k": k,
        "ms": _ms(started),
        "n_units": len(units),
        "units": [
            {"rank": u["rank"], "id": u["id"], "kind": u["id"].split("_")[0],
             "distance": u["distance"], "text": u["text"]}
            for u in units
        ],
        "error": None,
    }
    if not units:
        return None, trace, InferenceResult(
            None, "no schema elements retrieved", "no_retrieval", retrieval=trace
        )
    return chain.build_schema_context([u["text"] for u in units]), trace, None


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _build_messages(
    chain: NL2SQLChain, question: str, schema_context: str, feedback: Optional[str] = None
) -> list:
    return [
        {"role": "system", "content": chain.get_system_prompt(is_feedback=feedback is not None)},
        {"role": "user", "content": chain.build_user_prompt(question, schema_context, feedback)},
    ]


def _attempt_entry(number: int, messages: list, call: LLMCall) -> dict:
    """The run-log entry for one LLM attempt (SQL and check results are added later)."""
    raw = call.text
    return {
        "attempt": number,
        "system_prompt": "feedback" if number > 1 else "first",
        "user_prompt": messages[1]["content"],
        "llm": {
            "provider": call.provider,
            "model": call.model,
            "raw_output": raw[:MAX_RAW_OUTPUT_CHARS],
            "raw_output_truncated": len(raw) > MAX_RAW_OUTPUT_CHARS,
            "finish_reason": call.finish_reason,
            "usage": call.usage,
            "latency_ms": round(call.latency_ms, 2),
            "ttft_ms": None if call.ttft_ms is None else round(call.ttft_ms, 2),
            "error": call.error,
            "error_type": call.error_type,
        },
        "sql": None,
        "sql_empty": None,
        "check": {"ran": False, "valid": None, "stage": None, "error": None},
        "exec": None,
    }


# ---------------------------------------------------------------------------
# Single-pass inference  (no feedback retries)
# ---------------------------------------------------------------------------

async def _predict_sql(chain: NL2SQLChain, question: str, k: int) -> InferenceResult:
    """
    Single-pass SQL inference – no feedback loop, no DB logging.

    Args:
        chain: NL2SQLChain bound to the sample's database.
        question: Natural-language question.
        k: Number of schema retrieval units to retrieve (Top-K).
    """
    schema_context, retrieval, failed = _retrieve_context(chain, question, k)
    if failed:
        return failed

    messages = _build_messages(chain, question, schema_context)
    call = await call_llm(messages)
    attempt = _attempt_entry(1, messages, call)
    if call.error:
        return InferenceResult(
            None, f"LLM call failed: {call.error}", "llm_error", attempts=1,
            retrieval=retrieval, attempt_log=[attempt],
        )

    sql = chain.validator.clean_sql_output(call.text).strip()
    attempt["sql"], attempt["sql_empty"] = sql, _is_empty_sql(sql)
    if _is_empty_sql(sql):
        return InferenceResult(
            None, "LLM returned an empty response", "empty_response", attempts=1,
            retrieval=retrieval, attempt_log=[attempt],
        )
    return InferenceResult(
        sql, first_sql=sql, attempts=1, retrieval=retrieval, attempt_log=[attempt],
        final_attempt=1, final_source="attempt_1",
    )


# ---------------------------------------------------------------------------
# Inference WITH feedback/retry loop
# ---------------------------------------------------------------------------

def _check_sql(
    chain: NL2SQLChain, sql: str, executor: Optional[SpiderSQLiteExecutor]
) -> Tuple[bool, Optional[str], Optional[str], Optional[QueryRun]]:
    """
    Static validation, then (when ``executor`` is given) the query's own
    SQLite execution error. Only the predicted query is executed; the gold
    SQL is never consulted, so this is a legitimate inference-time signal.

    Returns:
        (ok, error, stage, execution) where ``stage`` is ``static`` or
        ``execution`` for a rejected query, and ``execution`` is the run of
        the query when it was executed.
    """
    is_valid, error = chain.validator.validate_query(sql)
    if not is_valid:
        return False, error, "static", None
    if executor is not None:
        started = time.perf_counter()
        ok, exec_error, rows = executor.execute(sql)
        run = QueryRun(ok, exec_error, rows, (time.perf_counter() - started) * 1000)
        if not ok:
            return False, f"SQLite execution error: {exec_error}", "execution", run
        return True, None, None, run
    return True, None, None, None


async def _predict_sql_with_feedback(
    chain: NL2SQLChain,
    question: str,
    k: int,
    max_iterations: int,
    executor: Optional[SpiderSQLiteExecutor] = None,
) -> InferenceResult:
    """
    SQL inference with the ``SQLFeedbackLoop`` validation + retry loop,
    without SSE streaming or database logging.

    Attempt 1 uses exactly the single-pass prompt. Each rejected attempt is
    fed back (with all earlier failures) and the model regenerates, up to
    ``max_iterations`` attempts in total. If no attempt passes, attempt 1 is
    kept, so the loop can only change the answer by finding a query that
    passes the checks.

    Args:
        chain: NL2SQLChain bound to the sample's database.
        question: Natural-language question.
        k: Number of schema retrieval units to retrieve (Top-K).
        max_iterations: Total attempts (1 initial + max_iterations-1 retries).
        executor: If given, SQLite execution errors also trigger a retry.
    """
    schema_context, retrieval, failed = _retrieve_context(chain, question, k)
    if failed:
        return failed

    feedback_loop = SQLFeedbackLoop(chain.validator, max_iterations=max_iterations)
    first_sql: Optional[str] = None
    attempts = 0
    error: Optional[str] = None
    notes: List[str] = []
    attempt_log: List[dict] = []

    while feedback_loop.should_continue():
        attempts += 1
        messages = _build_messages(
            chain, question, schema_context, feedback_loop.get_feedback_prompt()
        )
        call = await call_llm(messages)
        attempt = _attempt_entry(attempts, messages, call)
        attempt_log.append(attempt)
        if call.error:
            error = f"LLM call failed on attempt {attempts}: {call.error}"
            notes.append(error)
            break

        sql = chain.validator.clean_sql_output(call.text).strip()
        attempt["sql"], attempt["sql_empty"] = sql, _is_empty_sql(sql)
        if first_sql is None:
            first_sql = sql

        ok, check_error, stage, execution = _check_sql(chain, sql, executor)
        attempt["check"] = {"ran": True, "valid": ok, "stage": stage, "error": check_error}
        attempt["exec"] = result_snapshot(execution)
        feedback_loop.add_iteration(sql, check_error, success=ok)
        if ok:
            if attempts > 1:
                notes.append(f"attempt {attempts} passed")
            return InferenceResult(
                sql, first_sql=first_sql, attempts=attempts,
                recovered=attempts > 1, notes=notes,
                retrieval=retrieval, attempt_log=attempt_log,
                final_attempt=attempts, final_source=f"attempt_{attempts}",
            )
        error = f"attempt {attempts} rejected: {check_error}"
        notes.append(error)

    # No attempt passed the checks: keep attempt 1 (the single-pass answer).
    if _is_empty_sql(first_sql):
        kind = "llm_error" if first_sql is None else "empty_response"
        return InferenceResult(
            None, error, kind, attempts=attempts, notes=notes,
            retrieval=retrieval, attempt_log=attempt_log,
        )
    return InferenceResult(
        first_sql,
        f"no attempt passed the checks, kept attempt 1 (last: {error})",
        first_sql=first_sql, attempts=attempts, notes=notes,
        retrieval=retrieval, attempt_log=attempt_log,
        final_attempt=1, final_source="attempt_1_fallback",
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _compare(executor: SpiderSQLiteExecutor, pred_sql: str, gold_sql: str) -> CompareResult:
    """executor.compare_detailed, turning an unexpected exception into a failed comparison."""
    try:
        return executor.compare_detailed(pred_sql, gold_sql)
    except Exception as exc:
        failed = QueryRun(False, describe_exc(exc), None, 0.0)
        return CompareResult(False, describe_exc(exc), "scoring_error", failed, failed)


def _score(executor: SpiderSQLiteExecutor, result: InferenceResult, gold_sql: str):
    """
    Score the final SQL (and, for the feedback diagnostics, attempt 1).

    Returns:
        (scoring dict, results dict) for the run record.
    """
    pred_sql = result.sql
    em = exact_match(pred_sql, gold_sql)
    final = _compare(executor, pred_sql, gold_sql)

    if result.first_sql == pred_sql:
        first_em, first, first_run = em, final, final.pred
    elif _is_empty_sql(result.first_sql):
        first_em, first, first_run = False, None, None
    else:
        first_em = exact_match(result.first_sql, gold_sql)
        first = _compare(executor, result.first_sql, gold_sql)
        first_run = first.pred

    scoring = {
        "em": em,
        "ex": final.match,
        "ex_error": final.error,
        "ex_error_kind": final.kind,
        "first_attempt_em": first_em,
        "first_attempt_ex": bool(first and first.match),
        "first_attempt_ex_error": None if first is None else first.error,
    }
    results = {
        "gold": result_snapshot(final.gold),
        "final": result_snapshot(final.pred),
        "first": None if first_run is None or first is final else result_snapshot(first_run),
    }
    return scoring, results


# ---------------------------------------------------------------------------
# One sample -> one run-log record
# ---------------------------------------------------------------------------

def _usage_total(attempt_log: List[dict]) -> Optional[dict]:
    totals: Dict[str, int] = {}
    for attempt in attempt_log:
        for key, value in token_counts(attempt["llm"]["usage"]).items():
            totals[key] = totals.get(key, 0) + value
    return totals or None


def _base_record(index: int, sample: SpiderSample, mode: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_index": index,
        "db_id": sample.db_id,
        "question": sample.question,
        "gold_sql": sample.gold_sql,
        "mode": mode,
        "started_at": utc_now(),
        "finished_at": None,
        "status": None,
        "failure_kind": None,
        "skip_reason": None,
        "error": None,
        "retrieval": None,
        "attempts": [],
        "n_attempts": 0,
        "first_sql": None,
        "final_sql": None,
        "final_attempt": None,
        "final_source": None,
        "recovered": False,
        "scoring": None,
        "results": None,
        "usage": None,
        "timing_ms": None,
    }


async def _process_sample(
    index: int,
    sample: SpiderSample,
    chain: NL2SQLChain,
    executor: SpiderSQLiteExecutor,
    *,
    k: int,
    use_feedback_loop: bool,
    max_iterations: int,
    execution_feedback: bool,
) -> Tuple[dict, InferenceResult]:
    """Infer and score one sample. Never raises for ordinary failures: they are the record."""
    mode = "feedback" if use_feedback_loop else "single-pass"
    record = _base_record(index, sample, mode)
    started = time.perf_counter()
    result = InferenceResult(None, None, "internal_error")
    try:
        if use_feedback_loop:
            result = await _predict_sql_with_feedback(
                chain, sample.question, k=k, max_iterations=max_iterations,
                executor=executor if execution_feedback else None,
            )
        else:
            result = await _predict_sql(chain, sample.question, k=k)

        record.update(
            retrieval=result.retrieval,
            attempts=result.attempt_log,
            n_attempts=result.attempts,
            first_sql=result.first_sql,
            final_sql=result.sql,
            final_attempt=result.final_attempt,
            final_source=result.final_source,
            recovered=result.recovered,
            error=result.error,
            usage=_usage_total(result.attempt_log),
        )
        scoring_ms = 0.0
        if not result.sql:
            record.update(status="no_sql", failure_kind=result.failure_kind)
        else:
            scoring_started = time.perf_counter()
            scoring, results = _score(executor, result, sample.gold_sql)
            scoring_ms = (time.perf_counter() - scoring_started) * 1000
            record.update(status="scored", scoring=scoring, results=results)
    except Exception as exc:
        record.update(
            status="internal_error",
            failure_kind="internal_error",
            error=f"{describe_exc(exc)}\n{traceback.format_exc()}",
            n_attempts=result.attempts,
        )
        scoring_ms = 0.0

    llm_ms = sum(a["llm"]["latency_ms"] for a in record["attempts"])
    record["timing_ms"] = {
        "total": _ms(started),
        "retrieval": (record["retrieval"] or {}).get("ms"),
        "llm": round(llm_ms, 2),
        "scoring": round(scoring_ms, 2),
    }
    record["finished_at"] = utc_now()
    return record, result


def _skipped_record(index: int, sample: SpiderSample, mode: str, reason: str, detail: str) -> dict:
    record = _base_record(index, sample, mode)
    record.update(status="skipped", skip_reason=reason, error=detail, finished_at=utc_now())
    return record


def _print_record(record: dict, result: InferenceResult, total: int, verbose: bool) -> None:
    if not verbose:
        return
    prefix = f"[{record['sample_index'] + 1}/{total}]"
    db_id = record["db_id"]
    status = record["status"]
    if status == "skipped":
        print(f"{prefix} SKIP  db={db_id} ({record['error']})")
        return
    if status in ("no_sql", "internal_error"):
        print(f"{prefix} FAIL   db={db_id} | no SQL: {record['error']}")
        for note in result.notes:
            if note != record["error"]:
                print(f"         [feedback] {note}")
        return
    scoring = record["scoring"]
    em, ex = scoring["em"], scoring["ex"]
    label = "EM+EX" if (em and ex) else ("EM" if em else ("EX" if ex else "FAIL"))
    retry_info = f" (attempts: {record['n_attempts']})" if record["n_attempts"] > 1 else ""
    print(f"{prefix} {label:<6} db={db_id}{retry_info} | Q: {record['question'][:60]}")
    for note in result.notes:
        print(f"         [feedback] {note}")
    if not ex:
        print(f"         reason: {scoring['ex_error']}")
        print(f"         pred:   {record['final_sql'][:200]}")


# ---------------------------------------------------------------------------
# Run description (manifest)
# ---------------------------------------------------------------------------

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _embedding_description(embedding_fn) -> dict:
    if USE_LOCAL_EMBEDDING:
        provider, model = "local", os.path.basename(str(EMBEDDING_MODEL_DIR).rstrip("/\\"))
    else:
        provider, model = "openai", utils.OPENAI_EMBEDDING_MODEL_NAME
    return {"provider": provider, "model": model}


def _run_meta(
    spider_path: str, n_samples: int, *, k: int, use_feedback_loop: bool,
    max_iterations: int, execution_feedback: bool, embedding_fn,
) -> dict:
    llm = asdict(get_llm_settings())
    mode = "feedback" if use_feedback_loop else "single-pass"
    config = {
        "mode": mode,
        "k": k,
        "max_attempts": max_iterations if use_feedback_loop else None,
        "execution_feedback": execution_feedback if use_feedback_loop else False,
    }
    prompts = {
        "system_first": SYSTEM_PROMPT_NL2SQL,
        "system_feedback": SYSTEM_PROMPT_NL2SQL_FEEDBACK,
    }
    # The user prompt is assembled by code, so hash that code too: a run must
    # not be resumed after the prompt builder has changed.
    builder_sha = sha256_text(
        inspect.getsource(NL2SQLChain.build_user_prompt)
        + inspect.getsource(NL2SQLChain.build_schema_context)
    )
    prompts_sha = sha256_text(prompts["system_first"] + "\0" + prompts["system_feedback"])
    dev_json = os.path.join(spider_path, "dev.json")
    dataset = {"dev_json": "dev.json", "sha256": sha256_file(dev_json), "n_samples": n_samples}
    embedding = _embedding_description(embedding_fn)
    return {
        "config": config,
        "llm": {**llm, "stream": True, "api_key_set": bool(env.openai_api_key)},
        "embedding": {**embedding, "function": _safe_name(embedding_fn)},
        "prompts": {**prompts, "system_sha256": prompts_sha, "user_builder_sha256": builder_sha},
        "dataset": dataset,
        "code": git_info(_REPO_DIR),
        "environment": environment_info(),
        "fingerprint": {
            **config,
            "llm": {k_: llm[k_] for k_ in ("provider", "model", "temperature")},
            "embedding": embedding,
            "prompts_sha256": prompts_sha,
            "user_builder_sha256": builder_sha,
            "dataset_sha256": dataset["sha256"],
        },
    }


def _safe_name(embedding_fn) -> Optional[str]:
    try:
        name = embedding_fn.name()
    except Exception:
        return None
    # Local functions name themselves after the model directory: keep the leaf only.
    return os.path.basename(str(name).rstrip("/\\)")) if "/" in str(name) or "\\" in str(name) else str(name)


# ---------------------------------------------------------------------------
# Public evaluation entry point
# ---------------------------------------------------------------------------

async def run_spider_evaluation(
    samples: List[SpiderSample],
    spider_path: str,
    verbose: bool = True,
    max_samples: Optional[int] = None,
    k: int = 15,
    use_feedback_loop: bool = False,
    feedback_max_iterations: int = 4,
    execution_feedback: bool = False,
    run_log: Optional[RunLog] = None,
    resume: bool = False,
    rebuild_index: bool = False,
    out_dir: str = "runs",
    tag: Optional[str] = None,
    argv: Optional[List[str]] = None,
) -> Dict:
    """
    Evaluate a list of Spider samples, log every sample, and return the metrics.

    Args:
        samples: List of SpiderSample objects from spider_loader.
        spider_path: Root path to Spider dataset (contains database/ folder).
        verbose: If True, print per-sample progress to stdout.
        max_samples: Optional cap on the number of samples to evaluate.
        k: Number of schema retrieval units (Top-K) passed to the retriever.
        use_feedback_loop: If True, use the validation + retry loop
                           (SQLFeedbackLoop). If False, single-pass only.
        feedback_max_iterations: Total attempts per question when
                                 use_feedback_loop=True.
        execution_feedback: If True (feedback mode only), an SQLite execution
                            error of the predicted query also triggers a retry.
        run_log: The run directory to write. Created under ``out_dir`` if None.
        resume: ``run_log`` is an existing run: skip the samples it already
                holds and re-run those that failed on infrastructure errors.
        rebuild_index: Re-embed every database's schema units instead of
                       reusing collections left by earlier runs.
        out_dir, tag: Where/how to name a new run directory.
        argv: The command line, recorded in the manifest.

    Returns:
        Dict with keys: total, exact_match, execution_accuracy, mode, k,
        skipped, inference_failures, failure_reasons, llm_calls and, in feedback
        mode, max_attempts, execution_feedback and feedback (loop diagnostics);
        plus run_dir, tokens and status_counts. All of it is recomputed from the
        run log's records, so it matches what ``run_log check`` reports.
    """
    mode = "feedback" if use_feedback_loop else "single-pass"
    owns_log = run_log is None
    if owns_log:
        run_log = RunLog.create(out_dir, mode, get_llm_settings().model, k, tag)

    os.makedirs(_SPIDER_CHROMA_DIR, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=_SPIDER_CHROMA_DIR)
    embedding_fn = _build_embedding_fn()

    eval_samples = samples if max_samples is None else samples[:max_samples]
    n_eval = len(eval_samples)

    status = "failed"
    started = False
    latest: Dict[int, dict] = {}
    try:
        meta = _run_meta(
            spider_path, len(samples), k=k, use_feedback_loop=use_feedback_loop,
            max_iterations=feedback_max_iterations, execution_feedback=execution_feedback,
            embedding_fn=embedding_fn,
        )
        session_meta = {
            "argv": argv, "limit": max_samples,
            "code": meta["code"], "environment": meta["environment"],
        }
        latest = run_log.start(meta, session_meta, resuming=resume)
        started = True
        latest = {i: r for i, r in latest.items() if i < n_eval}
        schema_units = run_log.load_schema_units()

        print(f"run log: {run_log.run_dir}")
        if meta["code"].get("dirty"):
            print("note: the working tree has uncommitted changes; the manifest records commit "
                  f"{meta['code'].get('commit')} + dirty=true")
        if use_feedback_loop:
            signal = "static validation + SQLite execution" if execution_feedback else "static validation"
            print(f"feedback loop ({signal}), max {feedback_max_iterations} attempts, k={k}")
        else:
            print(f"single-pass inference, k={k}")
        llm = meta["llm"]
        print(f"LLM: {llm['provider']} / {llm['model']}  temperature={llm['temperature']}")
        if resume:
            previous = run_log.manifest["sessions"][-2].get("code") or {}
            if previous.get("commit") != meta["code"].get("commit") or previous.get("dirty") != meta["code"].get("dirty"):
                print(f"WARNING: code version changed since the previous session "
                      f"({previous.get('commit')} dirty={previous.get('dirty')} -> "
                      f"{meta['code'].get('commit')} dirty={meta['code'].get('dirty')}); "
                      "each session's version is recorded in the manifest")
            retry = [i for i, r in latest.items() if _needs_rerun(r)]
            print(f"resuming: {len(latest) - len(retry)} of {n_eval} samples already done, "
                  f"{len(retry)} to re-run after infrastructure errors, "
                  f"{n_eval - len(latest)} not started")

        # Cache chain instances per db_id to avoid rebuilding embeddings for
        # every question in the same database.
        _chain_cache: Dict[str, NL2SQLChain] = {}

        for idx, sample in enumerate(eval_samples):
            if idx in latest and not _needs_rerun(latest[idx]):
                continue

            db_id = sample.db_id
            sqlite_path = get_sqlite_path(spider_path, db_id)

            if not os.path.exists(sqlite_path):
                record = _skipped_record(
                    idx, sample, mode, "sqlite_missing",
                    f"SQLite file missing: {sqlite_path}",
                )
                run_log.append(record)
                latest[idx] = record
                _print_record(record, InferenceResult(None), n_eval, verbose)
                continue

            # Build/reuse schema + chain for this db_id
            if db_id not in _chain_cache:
                try:
                    extractor = SQLiteSchemaExtractor(sqlite_path)
                    schema_dict = extractor.extract()

                    collection_name, collection_info = _build_collection(
                        chroma_client, embedding_fn, db_id, schema_dict,
                        rebuild=rebuild_index,
                    )
                    if collection_info["reused"] and not collection_info["docs_match"]:
                        print(f"WARNING: db={db_id}: the existing Chroma collection differs from "
                              "the current schema units (stale index from an earlier run); "
                              "re-run with --rebuild-index")

                    schema_manager = SchemaManager()
                    schema_manager.load_schema_from_dict(schema_dict)

                    chain = NL2SQLChain(
                        schema_manager=schema_manager,
                        collection_name=collection_name,
                    )
                    # Inject the shared chroma client and embedding_fn so we
                    # don't open a second client pointed at the wrong directory.
                    chain.chroma_client = chroma_client
                    chain.embedding_fn = embedding_fn

                    _chain_cache[db_id] = chain
                    schema_units[db_id] = {
                        "db_id": db_id,
                        "summary": schema_manager.get_schema_summary(),
                        "collection": collection_info,
                        "units": _schema_units(schema_dict),
                    }
                    run_log.save_schema_units(schema_units)
                except Exception as exc:
                    record = _skipped_record(
                        idx, sample, mode, "schema_build_failed",
                        f"schema build failed: {describe_exc(exc)}",
                    )
                    run_log.append(record)
                    latest[idx] = record
                    _print_record(record, InferenceResult(None), n_eval, verbose)
                    continue

            chain = _chain_cache[db_id]
            # The executor is bound to this sample's database file (its db_id).
            executor = SpiderSQLiteExecutor(sqlite_path)

            record, result = await _process_sample(
                idx, sample, chain, executor, k=k, use_feedback_loop=use_feedback_loop,
                max_iterations=feedback_max_iterations, execution_feedback=execution_feedback,
            )
            run_log.append(record)
            latest[idx] = record
            _print_record(record, result, n_eval, verbose)

            if (idx + 1) % 25 == 0:
                run_log.save_manifest(progress={
                    "done": len(latest), "of": n_eval, "updated_at": utc_now(),
                })

        status = "complete"
    except BaseException as exc:
        status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) or \
            type(exc).__name__ == "CancelledError" else "failed"
        raise
    finally:
        # Never touch the log if this session never started (e.g. a refused
        # resume): the existing manifest must stay exactly as it was.
        if started:
            metrics = summarize_records(
                latest, mode=mode, k=k,
                max_attempts=feedback_max_iterations if use_feedback_loop else None,
                execution_feedback=execution_feedback if use_feedback_loop else None,
            )
            tokens = token_totals(latest)
            status_counts: Dict[str, int] = {}
            for r in latest.values():
                status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
            run_log.finish(status, results={
                "metrics": metrics, "tokens": tokens, "status_counts": status_counts,
                "n_samples_logged": len(latest), "of": n_eval, "finished_at": utc_now(),
            })
        if owns_log:
            run_log.close()

    metrics["run_dir"] = run_log.run_dir
    metrics["tokens"] = tokens
    metrics["status_counts"] = status_counts
    return metrics


def _needs_rerun(record: dict) -> bool:
    """A sample that failed on infrastructure (not the model) is worth re-running on resume."""
    return (
        record.get("failure_kind") in RETRYABLE_FAILURE_KINDS
        or record.get("skip_reason") in RETRYABLE_FAILURE_KINDS
    )
