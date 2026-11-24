"""
Evaluation Runner

Main evaluation loop for the benchmarks of ``app.evaluation.benchmarks``
(Spider 1 and BIRD). The loop is the same for both; what differs between them
(files, evidence, scoring rule) comes from the ``Benchmark``.

Architecture
------------
For each sample the runner:
1. Extracts the SQLite schema → SchemaManager-compatible JSON dict
2. Loads (or reuses) a ChromaDB collection named ``Schema_<benchmark>_<db_id>``
3. Instantiates NL2SQLChain with that collection
4. Retrieves the Top-K schema units and generates SQL, either single-pass or
   with the feedback/retry loop (static validation, optionally plus the
   predicted query's own SQLite execution error and, for BIRD, an empty
   result); a retry caused by a missing column or an empty result also
   widens the schema context with every column of the tables the query named
5. Evaluates Execution Accuracy
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
import app.retrieval as rt
import app.utilities as utils
from app.utilities import LocalSTEmbeddingFunction
from app.schema_manager import Column, Relation, SchemaManager, Table
from app.nl2sql_chain import NL2SQLChain, get_llm_settings
from app.sql_validator import EMPTY_RESULT_ERROR, SQLFeedbackLoop, SQLValidator
from app.system_prompt import SYSTEM_PROMPT_NL2SQL, SYSTEM_PROMPT_NL2SQL_FEEDBACK
from app.evaluation.llm_io import LLMCall, call_llm, describe_exc, token_counts
from app.evaluation.run_log import (
    MAX_RAW_OUTPUT_CHARS,
    RETRYABLE_FAILURE_KINDS,
    RunLog,
    describe_outcome,
    environment_info,
    git_info,
    prompt_sha,
    result_snapshot,
    sha256_text,
    summarize_records,
    token_totals,
    utc_now,
)
from app.evaluation.benchmarks import Benchmark, Sample
from app.evaluation.sqlite_schema_extractor import SQLiteSchemaExtractor
from app.evaluation import executor as executor_module
from app.evaluation.executor import CompareResult, QueryRun, SQLiteExecutor
from chromadb.utils import embedding_functions

USE_LOCAL_EMBEDDING = env.use_local_embedding
OPENAI_API_KEY = env.openai_api_key
EMBEDDING_MODEL_DIR = env.embedding_model_dir


def _chroma_dir(benchmark: Benchmark) -> str:
    """
    ChromaDB directory dedicated to one benchmark's evaluation, so that
    production collections (and the other benchmark's) are never contaminated.
    """
    return os.path.join(utils.CHROMADB_PERSIST_DIRECTORY, benchmark.chroma_dir_name)


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
    collection_name: str,
    schema_dict: dict,
    batch_size: int = 10,
    rebuild: bool = False,
) -> Tuple[str, dict]:
    """
    Create (or retrieve) the Chroma collection ``collection_name`` of one
    database and populate it with schema embeddings if it is empty.

    Args:
        chroma_client: Open ChromaDB persistent client.
        embedding_fn: Embedding function instance.
        collection_name: ``Schema_<benchmark>_<db_id>``.
        schema_dict: Schema dict from SQLiteSchemaExtractor.extract().
        batch_size: Upsert batch size.
        rebuild: Drop an existing collection first, so every unit is embedded
                 afresh with the current embedding model.

    Returns:
        (collection name, info). ``info["reused"]`` is True when the collection
        already held exactly the units the current schema produces (kept from an
        earlier run); ``info["rebuilt_stale"]`` is True when it held different
        units (e.g. an older text template) and was replaced. A reused
        collection keeps the vectors made by whatever embedding model was active
        then, which the collection itself does not record: pass ``rebuild=True``
        after changing the embedding model.
    """
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
    rebuilt_stale = False
    if reused:
        stored = collection.get(ids=ids)
        stored_docs = dict(zip(stored["ids"], stored["documents"]))
        current = stored_count == len(ids) and all(
            stored_docs.get(unit_id) == doc for unit_id, doc in zip(ids, documents)
        )
        if not current:
            # Left over from an older text template or schema: retrieving from
            # it would silently use units this code no longer produces.
            chroma_client.delete_collection(collection_name)
            collection = chroma_client.get_or_create_collection(
                name=collection_name,
                embedding_function=embedding_fn,
            )
            reused, rebuilt_stale = False, True
    if not reused:
        for i in range(0, len(ids), batch_size):
            collection.upsert(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
            )

    info = {
        "name": collection_name,
        "reused": reused,
        "rebuilt_stale": rebuilt_stale,
        "n_units_expected": len(ids),
        "n_units_stored": collection.count(),
    }
    return collection_name, info


def _schema_units(schema_dict: dict) -> List[dict]:
    """
    Every retrieval unit of a schema, with its text and the schema element it
    stands for, so retrieval can be analysed without parsing the text.

    Ids match ``SchemaManager.get_all_embedding_texts`` (``table_i``,
    ``column_i``, ``relation_i``).
    """
    manager = SchemaManager()
    manager.load_schema_from_dict(schema_dict)
    ids, documents = manager.get_all_embedding_texts()
    texts = dict(zip(ids, documents))

    units = []
    for i, table in enumerate(manager.tables):
        units.append({"id": f"table_{i}", "kind": "table", "table": table.name,
                      "key_columns": table.key_columns, "text": texts[f"table_{i}"]})
    for i, column in enumerate(manager.columns):
        units.append({"id": f"column_{i}", "kind": "column", "table": column.table_name,
                      "column": column.column_name, "data_type": column.data_type,
                      "text": texts[f"column_{i}"]})
    for i, relation in enumerate(manager.relations):
        units.append({"id": f"relation_{i}", "kind": "relation",
                      "source_table": relation.source_table, "source_column": relation.source_column,
                      "target_table": relation.target_table, "target_column": relation.target_column,
                      "text": texts[f"relation_{i}"]})
    return units


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
    """The retrieval step (Top-K unit ids, dense distances, reranker scores, stage lists) for the run log."""
    attempt_log: List[dict] = field(default_factory=list)
    """One dict per LLM attempt (prompt, raw output, usage, checks) for the run log."""
    final_attempt: Optional[int] = None
    """Number of the attempt whose SQL was kept (1 also when attempt 1 is the fallback)."""
    final_source: Optional[str] = None
    """``attempt_N`` (passed the checks / single-pass) or ``attempt_1_fallback``."""


def _is_empty_sql(sql: Optional[str]) -> bool:
    # clean_sql_output() turns an empty LLM response into ";"
    return not sql or not sql.strip().strip(";").strip()


def _retrieve_context(chain: NL2SQLChain, question: str, evidence: Optional[str], k: int):
    """
    Return (schema_context, retrieval, None) or (None, retrieval, failed InferenceResult).

    The retrieval query is the question plus its external knowledge, if the
    sample has any (BIRD's hints name the columns the question is about).
    """
    query = f"{question}\n{evidence}" if evidence else question
    try:
        found = chain.retrieve(query, n_results=k)
    except Exception as exc:
        return None, None, InferenceResult(
            None, f"schema retrieval failed: {describe_exc(exc)}", "retrieval_error"
        )
    units = found["units"]
    retrieval = {
        "ids": [u["id"] for u in units],
        # dense distance (None: the unit was not in the dense Top-K), reranker score,
        # and the candidate lists of each stage
        "distances": [None if u["distance"] is None else round(u["distance"], 4) for u in units],
        "scores": [None if u["score"] is None else round(u["score"], 4) for u in units] if chain.rerank else None,
        "stages": found["stages"],
    }
    if not units:
        return None, retrieval, InferenceResult(
            None, "no schema elements retrieved", "no_retrieval", retrieval=retrieval
        )
    return chain.build_schema_context([u["text"] for u in units]), retrieval, None


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _build_messages(
    chain: NL2SQLChain,
    question: str,
    evidence: Optional[str],
    schema_context: str,
    feedback: Optional[str] = None,
) -> list:
    return [
        {"role": "system", "content": chain.get_system_prompt(is_feedback=feedback is not None)},
        {"role": "user", "content": chain.build_user_prompt(question, schema_context, feedback, evidence)},
    ]


def _tokens(usage: Optional[dict]) -> Optional[dict]:
    """Provider usage as {prompt, completion[, reasoning][, cached]}; None if not reported."""
    counts = token_counts(usage)
    if "prompt_tokens" not in counts and "completion_tokens" not in counts:
        return None
    tokens = {"prompt": counts.get("prompt_tokens", 0), "completion": counts.get("completion_tokens", 0)}
    if "reasoning_tokens" in counts:
        tokens["reasoning"] = counts["reasoning_tokens"]
    if "cached_tokens" in counts:
        tokens["cached"] = counts["cached_tokens"]
    return tokens


def _attempt_entry(messages: list, call: LLMCall) -> dict:
    """
    The run-log entry for one LLM attempt. ``sql``, ``rejected`` and ``exec_rows``
    are filled in once the attempt has been checked. The prompt itself is not
    stored: ``prompt_sha`` proves it can be rebuilt exactly (see run_log).
    """
    raw = call.text
    if len(raw) > MAX_RAW_OUTPUT_CHARS:
        raw = raw[:MAX_RAW_OUTPUT_CHARS] + f"…[truncated, {len(call.text) - MAX_RAW_OUTPUT_CHARS} more characters]"
    entry = {
        "sql": None,
        "prompt_sha": prompt_sha(messages[1]["content"]),
        "raw_output": raw,
        "tokens": _tokens(call.usage),
        "ms": round(call.latency_ms),
        "rejected": None,
        "exec_rows": None,
    }
    if call.finish_reason not in (None, "stop"):
        entry["finish"] = call.finish_reason     # e.g. "length": the output was cut off
    if call.error:
        entry["error"] = call.error
    return entry


# ---------------------------------------------------------------------------
# Single-pass inference  (no feedback retries)
# ---------------------------------------------------------------------------

async def _predict_sql(
    chain: NL2SQLChain, question: str, evidence: Optional[str], k: int
) -> InferenceResult:
    """
    Single-pass SQL inference – no feedback loop, no DB logging.

    Args:
        chain: NL2SQLChain bound to the sample's database.
        question: Natural-language question.
        evidence: External knowledge that comes with the question (BIRD), or None.
        k: Number of schema retrieval units to retrieve (Top-K).
    """
    schema_context, retrieval, failed = _retrieve_context(chain, question, evidence, k)
    if failed:
        return failed

    messages = _build_messages(chain, question, evidence, schema_context)
    call = await call_llm(messages)
    attempt = _attempt_entry(messages, call)
    if call.error:
        return InferenceResult(
            None, f"LLM call failed: {call.error}", "llm_error", attempts=1,
            retrieval=retrieval, attempt_log=[attempt],
        )

    sql = chain.validator.clean_sql_output(call.text).strip()
    attempt["sql"] = sql
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

def _carries_no_information(rows: Optional[list]) -> bool:
    """No rows, or nothing but NULLs (an aggregate over no matching row)."""
    return rows is not None and all(cell is None for row in rows for cell in row)


def _check_sql(
    chain: NL2SQLChain, sql: str, executor: Optional[SQLiteExecutor], empty_result_is_error: bool = False
) -> Tuple[bool, Optional[str], Optional[str], Optional[QueryRun]]:
    """
    Static validation, then (when ``executor`` is given) the query's own
    SQLite execution error and, with ``empty_result_is_error``, an empty
    result. Only the predicted query is executed; the gold SQL is never
    consulted, so this is a legitimate inference-time signal.

    Returns:
        (ok, error, stage, execution) where ``stage`` is ``static``,
        ``execution`` or ``semantic`` (the query ran but its result is empty)
        for a rejected query, and ``execution`` is the run of the query when
        it was executed.
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
        if empty_result_is_error and _carries_no_information(rows):
            return False, EMPTY_RESULT_ERROR, "semantic", run
        return True, None, None, run
    return True, None, None, None


def _widens_context(stage: Optional[str], error: Optional[str]) -> bool:
    """Is the rejection one that a fuller schema context can cure: an empty result or a missing column."""
    return stage == "semantic" or (stage == "execution" and "no such column" in (error or "").lower())


async def _predict_sql_with_feedback(
    chain: NL2SQLChain,
    question: str,
    evidence: Optional[str],
    k: int,
    max_iterations: int,
    executor: Optional[SQLiteExecutor] = None,
    empty_result_is_error: bool = False,
) -> InferenceResult:
    """
    SQL inference with the ``SQLFeedbackLoop`` validation + retry loop,
    without SSE streaming or database logging.

    Attempt 1 uses exactly the single-pass prompt. Each rejected attempt is
    fed back (with all earlier failures) and the model regenerates, up to
    ``max_iterations`` attempts in total. If no attempt passes, attempt 1 is
    kept, so the loop can only change the answer by finding a query that
    passes the checks.

    When the rejection is a missing column or an empty result, the schema
    context of the next attempts also gets every column of the tables the
    rejected query named (``NL2SQLChain.expand_context``); the units added
    before an attempt are logged in its ``units_added``.

    Args:
        chain: NL2SQLChain bound to the sample's database.
        question: Natural-language question.
        evidence: External knowledge that comes with the question (BIRD), or None.
        k: Number of schema retrieval units to retrieve (Top-K).
        max_iterations: Total attempts (1 initial + max_iterations-1 retries).
        executor: If given, SQLite execution errors also trigger a retry.
        empty_result_is_error: With ``executor``, a query whose result is empty
            (no rows, or only NULLs) is rejected too (``Benchmark.empty_result_is_error``).
    """
    schema_context, retrieval, failed = _retrieve_context(chain, question, evidence, k)
    if failed:
        return failed

    context_ids = list(retrieval["ids"])
    units_added: List[str] = []          # added after the last attempt, not yet seen by the model
    feedback_loop = SQLFeedbackLoop(chain.validator, max_iterations=max_iterations)
    first_sql: Optional[str] = None
    attempts = 0
    error: Optional[str] = None
    notes: List[str] = []
    attempt_log: List[dict] = []

    while feedback_loop.should_continue():
        attempts += 1
        messages = _build_messages(
            chain, question, evidence, schema_context, feedback_loop.get_feedback_prompt()
        )
        call = await call_llm(messages)
        attempt = _attempt_entry(messages, call)
        if units_added:
            attempt["units_added"] = units_added
            units_added = []
        attempt_log.append(attempt)
        if call.error:
            error = f"LLM call failed on attempt {attempts}: {call.error}"
            notes.append(error)
            break

        sql = chain.validator.clean_sql_output(call.text).strip()
        attempt["sql"] = sql
        if first_sql is None:
            first_sql = sql

        ok, check_error, stage, execution = _check_sql(chain, sql, executor, empty_result_is_error)
        attempt["rejected"] = None if ok else {"stage": stage, "error": check_error}
        if execution is not None and execution.ok and execution.rows is not None:
            attempt["exec_rows"] = len(execution.rows)
        feedback_loop.add_iteration(sql, check_error, success=ok)
        if not ok and feedback_loop.should_continue() and _widens_context(stage, check_error):
            units_added = chain.expand_context(context_ids, sql)
            if units_added:
                context_ids += units_added
                schema_context = chain.context_of(context_ids)
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

def _compare(executor: SQLiteExecutor, pred_sql: str, gold_sql: str) -> CompareResult:
    """executor.compare_detailed, turning an unexpected exception into a failed comparison."""
    try:
        return executor.compare_detailed(pred_sql, gold_sql)
    except Exception as exc:
        failed = QueryRun(False, describe_exc(exc), None, 0.0)
        return CompareResult(False, describe_exc(exc), "scoring_error", failed, failed)


def _score(executor: SQLiteExecutor, result: InferenceResult, gold_sql: str):
    """
    Score the final SQL (and, for the feedback diagnostics, attempt 1).

    Returns:
        (scoring dict, results dict) for the run record.
    """
    pred_sql = result.sql
    final = _compare(executor, pred_sql, gold_sql)

    if result.first_sql == pred_sql:
        first, first_run = final, final.pred
    elif _is_empty_sql(result.first_sql):
        first, first_run = None, None
    else:
        first = _compare(executor, result.first_sql, gold_sql)
        first_run = first.pred

    scoring = {
        "ex": final.match,
        "kind": final.kind,
        "first_ex": bool(first and first.match),
        "permuted": final.permuted,
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

def _base_record(index: int, sample: Sample) -> dict:
    record = {
        "sample_index": index,
        "db_id": sample.db_id,
        "question": sample.question,
        "gold_sql": sample.gold_sql,
        "status": None,
        "failure_kind": None,
        "skip_reason": None,
        "error": None,
        "retrieved": None,
        "distances": None,
        "rerank_scores": None,
        "retrieval_stages": None,
        "attempts": [],
        "final_sql": None,
        "final_attempt": None,
        "fallback": False,
        "recovered": False,
        "scoring": None,
        "results": None,
        "ms": None,
    }
    # Only what the dataset provides: the evidence is what was sent to the model
    # (the prompt is rebuilt from it), the difficulty only labels the sample.
    if sample.evidence:
        record["evidence"] = sample.evidence
    if sample.difficulty:
        record["difficulty"] = sample.difficulty
    return record


async def _process_sample(
    index: int,
    sample: Sample,
    chain: NL2SQLChain,
    executor: SQLiteExecutor,
    *,
    k: int,
    use_feedback_loop: bool,
    max_iterations: int,
    execution_feedback: bool,
    empty_result_is_error: bool = False,
) -> Tuple[dict, InferenceResult]:
    """Infer and score one sample. Never raises for ordinary failures: they are the record."""
    record = _base_record(index, sample)
    started = time.perf_counter()
    result = InferenceResult(None, None, "internal_error")
    try:
        if use_feedback_loop:
            result = await _predict_sql_with_feedback(
                chain, sample.question, sample.evidence, k=k, max_iterations=max_iterations,
                executor=executor if execution_feedback else None,
                empty_result_is_error=empty_result_is_error,
            )
        else:
            result = await _predict_sql(chain, sample.question, sample.evidence, k=k)

        record.update(
            retrieved=(result.retrieval or {}).get("ids"),
            distances=(result.retrieval or {}).get("distances"),
            rerank_scores=(result.retrieval or {}).get("scores"),
            retrieval_stages=(result.retrieval or {}).get("stages"),
            attempts=result.attempt_log,
            final_sql=result.sql,
            final_attempt=result.final_attempt,
            fallback=result.final_source == "attempt_1_fallback",
            recovered=result.recovered,
            error=result.error,
        )
        if not result.sql:
            record.update(status="no_sql", failure_kind=result.failure_kind)
        else:
            scoring, results = _score(executor, result, sample.gold_sql)
            record.update(status="scored", scoring=scoring, results=results)
    except Exception as exc:
        record.update(
            status="internal_error",
            failure_kind="internal_error",
            error=f"{describe_exc(exc)}\n{traceback.format_exc()}",
            attempts=result.attempt_log,
        )

    record["ms"] = _ms(started)
    return record, result


def _skipped_record(index: int, sample: Sample, reason: str, detail: str) -> dict:
    record = _base_record(index, sample)
    record.update(status="skipped", skip_reason=reason, error=detail)
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
    label = "EX" if scoring["ex"] else "FAIL"
    n_attempts = len(record["attempts"])
    retry_info = f" (attempts: {n_attempts})" if n_attempts > 1 else ""
    print(f"{prefix} {label:<6} db={db_id}{retry_info} | Q: {record['question'][:60]}")
    for note in result.notes:
        print(f"         [feedback] {note}")
    if not scoring["ex"]:
        print(f"         reason: {describe_outcome(record)}")
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
    benchmark: Benchmark, n_samples: int, *, k: int, rerank: bool, use_feedback_loop: bool,
    max_iterations: int, execution_feedback: bool, embedding_fn, out_dir: str,
) -> dict:
    llm = asdict(get_llm_settings())
    mode = "feedback" if use_feedback_loop else "single-pass"
    config = {
        "dataset": benchmark.name,
        "dataset_options": benchmark.options,
        "mode": mode,
        "k": k,
        "rerank": rerank,
        "max_attempts": max_iterations if use_feedback_loop else None,
        "execution_feedback": execution_feedback if use_feedback_loop else False,
        # a retry on an empty result needs the execution signal, and only some benchmarks have it
        "empty_result_retry": bool(use_feedback_loop and execution_feedback and benchmark.empty_result_is_error),
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
        + inspect.getsource(SQLValidator.extract_error_feedback)
        + inspect.getsource(SQLFeedbackLoop.get_feedback_prompt)
    )
    prompts_sha = sha256_text(prompts["system_first"] + "\0" + prompts["system_feedback"])
    # The text of every retrieval unit comes from these templates.
    units_sha = sha256_text(
        "".join(inspect.getsource(c.to_embedding_text) for c in (Table, Column, Relation))
    )
    # The retrieval pipeline decides which units the model sees: same rule.
    retrieval_info = {
        **rt.describe(rerank),
        "code_sha256": sha256_text("".join(
            inspect.getsource(part)
            for part in (NL2SQLChain.retrieve, NL2SQLChain._retrieve_dense, NL2SQLChain.expand_context, rt)
        )),
    }
    # The scorer decides EX: a run must not be resumed after it has changed.
    scorer_sha = sha256_text(executor_module.scorer_source(benchmark.scoring))
    dataset = {
        "name": benchmark.name,
        "n_samples": n_samples,
        "scoring": benchmark.scoring,
        "options": benchmark.options,
        "files": benchmark.data_files(),
    }
    embedding = _embedding_description(embedding_fn)
    return {
        "config": config,
        "llm": {**llm, "stream": True, "api_key_set": bool(env.openai_api_key)},
        "embedding": {**embedding, "function": _safe_name(embedding_fn)},
        "retrieval": retrieval_info,
        "prompts": {**prompts, "system_sha256": prompts_sha, "user_builder_sha256": builder_sha},
        "retrieval_units": {"templates_sha256": units_sha},
        "scorer": {"sha256": scorer_sha},
        "dataset": dataset,
        "code": git_info(_REPO_DIR, exclude_dir=out_dir),
        "environment": environment_info(),
        "fingerprint": {
            **config,
            "llm": {k_: llm[k_] for k_ in ("provider", "model", "temperature", "reasoning_effort")},
            "embedding": embedding,
            "retrieval_pipeline": retrieval_info,
            "prompts_sha256": prompts_sha,
            "user_builder_sha256": builder_sha,
            "unit_templates_sha256": units_sha,
            "scorer_sha256": scorer_sha,
            "dataset_files": dataset["files"],
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

async def run_evaluation(
    benchmark: Benchmark,
    samples: List[Sample],
    verbose: bool = True,
    max_samples: Optional[int] = None,
    k: int = 15,
    rerank: bool = False,
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
    Evaluate a benchmark's samples, log every sample, and return the metrics.

    Args:
        benchmark: The dataset (Spider or BIRD) with the options of this run.
        samples: ``benchmark.load_samples()``.
        verbose: If True, print per-sample progress to stdout.
        max_samples: Optional cap on the number of samples to evaluate.
        k: K of the hybrid retrieval: dense Top-K + BM25 Top-K, merged by RRF
           (K to 1.5 K units, or exactly K with ``rerank``).
        rerank: Rerank the merged list with the cross-encoder and keep the best K.
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
        Dict with keys: total, execution_accuracy, mode, k,
        skipped, inference_failures, failure_reasons, llm_calls and, in feedback
        mode, max_attempts, execution_feedback and feedback (loop diagnostics);
        plus run_dir, tokens and status_counts. All of it is recomputed from the
        run log's records, so it matches what ``run_log check`` reports.
    """
    mode = "feedback" if use_feedback_loop else "single-pass"
    owns_log = run_log is None
    if owns_log:
        run_log = RunLog.create(out_dir, benchmark.name, mode, get_llm_settings().model, k, tag)

    chroma_dir = _chroma_dir(benchmark)
    os.makedirs(chroma_dir, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=chroma_dir)
    embedding_fn = _build_embedding_fn()

    eval_samples = samples if max_samples is None else samples[:max_samples]
    n_eval = len(eval_samples)

    status = "failed"
    started = False
    latest: Dict[int, dict] = {}
    try:
        meta = _run_meta(
            benchmark, len(samples), k=k, rerank=rerank, use_feedback_loop=use_feedback_loop,
            max_iterations=feedback_max_iterations, execution_feedback=execution_feedback,
            embedding_fn=embedding_fn, out_dir=os.path.dirname(os.path.abspath(run_log.run_dir)),
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
        options = ", ".join(f"{name}={'on' if on else 'off'}" for name, on in benchmark.options.items())
        print(f"benchmark: {benchmark.title}" + (f" ({options})" if options else "")
              + f", {len(samples)} samples, EX rule: {benchmark.scoring}")
        if meta["code"].get("dirty"):
            print("note: the working tree has uncommitted changes; the manifest records commit "
                  f"{meta['code'].get('commit')} + dirty=true")
        if use_feedback_loop:
            signal = "static validation + SQLite execution" if execution_feedback else "static validation"
            if meta["config"]["empty_result_retry"]:
                signal += " + empty result"
            print(f"feedback loop ({signal}), max {feedback_max_iterations} attempts, k={k}")
        else:
            print(f"single-pass inference, k={k}")
        print("retrieval: hybrid (dense + BM25 -> RRF"
              + (f" -> reranker {meta['retrieval']['reranker']}" if rerank else "") + ") + completion")
        llm = meta["llm"]
        print(f"LLM: {llm['provider']} / {llm['model']}  temperature={llm['temperature']}"
              + (f"  reasoning_effort={llm['reasoning_effort']}" if llm["provider"] == "openai" else ""))
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
            sqlite_path = benchmark.sqlite_path(db_id)

            if not os.path.exists(sqlite_path):
                record = _skipped_record(
                    idx, sample, "sqlite_missing", f"SQLite file missing: {sqlite_path}",
                )
                run_log.append(record)
                latest[idx] = record
                _print_record(record, InferenceResult(None), n_eval, verbose)
                continue

            # Build/reuse schema + chain for this db_id
            if db_id not in _chain_cache:
                try:
                    extractor = SQLiteSchemaExtractor(
                        sqlite_path, meanings=benchmark.column_meanings(db_id)
                    )
                    schema_dict = extractor.extract()

                    collection_name, collection_info = _build_collection(
                        chroma_client, embedding_fn,
                        f"Schema_{benchmark.collection_prefix}_{db_id}", schema_dict,
                        rebuild=rebuild_index,
                    )
                    if collection_info["rebuilt_stale"]:
                        print(f"note: db={db_id}: the existing Chroma collection held outdated "
                              "schema units (from an earlier run); it was rebuilt")

                    schema_manager = SchemaManager()
                    schema_manager.load_schema_from_dict(schema_dict)

                    chain = NL2SQLChain(
                        schema_manager=schema_manager,
                        collection_name=collection_name,
                        rerank=rerank,
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
                        idx, sample, "schema_build_failed",
                        f"schema build failed: {describe_exc(exc)}",
                    )
                    run_log.append(record)
                    latest[idx] = record
                    _print_record(record, InferenceResult(None), n_eval, verbose)
                    continue

            chain = _chain_cache[db_id]
            # The executor is bound to this sample's database file (its db_id).
            executor = SQLiteExecutor(sqlite_path, scoring=benchmark.scoring)

            record, result = await _process_sample(
                idx, sample, chain, executor, k=k, use_feedback_loop=use_feedback_loop,
                max_iterations=feedback_max_iterations, execution_feedback=execution_feedback,
                empty_result_is_error=benchmark.empty_result_is_error,
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
