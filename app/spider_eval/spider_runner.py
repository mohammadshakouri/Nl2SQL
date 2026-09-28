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
6. Returns aggregated metrics plus inference-failure and feedback diagnostics
"""

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import chromadb

import app.dotenv as env
import app.utilities as utils
from app.utilities import LocalSTEmbeddingFunction
from app.schema_manager import SchemaManager
from app.nl2sql_chain import NL2SQLChain
from app.sql_validator import SQLFeedbackLoop
from app.spider_eval.spider_loader import SpiderSample, get_sqlite_path
from app.spider_eval.sqlite_schema_extractor import SQLiteSchemaExtractor
from app.spider_eval.spider_sqlite_executor import SpiderSQLiteExecutor
from app.spider_eval.spider_evaluator import exact_match, compute_metrics
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
) -> str:
    """
    Create (or retrieve) a Chroma collection for the given Spider db_id and
    populate it with schema embeddings if it is empty.

    Args:
        chroma_client: Open ChromaDB persistent client.
        embedding_fn: Embedding function instance.
        db_id: Spider database identifier.
        schema_dict: Schema dict from SQLiteSchemaExtractor.extract().
        batch_size: Upsert batch size.

    Returns:
        The Chroma collection name.
    """
    collection_name = f"Schema_spider_{db_id}"

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
    )

    # Only populate if the collection is empty to avoid re-embedding on
    # repeated runs of the same db_id (possible within a single dev pass
    # because multiple questions share one database).
    if collection.count() == 0:
        manager = SchemaManager()
        manager.load_schema_from_dict(schema_dict)
        ids, documents = manager.get_all_embedding_texts()

        for i in range(0, len(ids), batch_size):
            collection.upsert(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
            )

    return collection_name


# ---------------------------------------------------------------------------
# Streaming helper – collects all tokens from the LLM into a single string.
# Using streaming mode because it's the proven code path for both Ollama and
# OpenAI and avoids silent failures that occur with stream=False.
# ---------------------------------------------------------------------------

async def _stream_llm(chain: NL2SQLChain, messages: list) -> str:
    """Call the configured LLM in streaming mode and return the full output."""
    full_sql = ""
    if env.use_local_llm:
        chat_resp = await chain.generate_sql_ollama(messages, stream=True)
        async for chunk in chat_resp:
            if (
                hasattr(chunk, "message")
                and chunk.message
                and chunk.message.content
            ):
                full_sql += chunk.message.content
            if getattr(chunk, "done", False):
                break
    else:
        chat_resp = await chain.generate_sql_openai(messages, stream=True)
        async for chunk in chat_resp:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta and choice.delta.content:
                full_sql += choice.delta.content
            if choice.finish_reason is not None:
                break
    return full_sql


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


def _describe_exc(exc: BaseException) -> str:
    """Exception type + message; some (e.g. httpx timeouts) have an empty str()."""
    message = str(exc).strip() or repr(exc)
    return f"{type(exc).__name__}: {message}"


def _is_empty_sql(sql: Optional[str]) -> bool:
    # clean_sql_output() turns an empty LLM response into ";"
    return not sql or not sql.strip().strip(";").strip()


def _retrieve_context(chain: NL2SQLChain, question: str, k: int):
    """Return (schema_context, None) or (None, failed InferenceResult)."""
    try:
        retrieved_elements, _ = chain.retrieve_schema_elements(question, n_results=k)
    except Exception as exc:
        return None, InferenceResult(
            None, f"schema retrieval failed: {_describe_exc(exc)}", "retrieval_error"
        )
    if not retrieved_elements:
        return None, InferenceResult(None, "no schema elements retrieved", "no_retrieval")
    return chain.build_schema_context(retrieved_elements), None


def _build_messages(
    chain: NL2SQLChain, question: str, schema_context: str, feedback: Optional[str] = None
) -> list:
    return [
        {"role": "system", "content": chain.get_system_prompt(is_feedback=feedback is not None)},
        {"role": "user", "content": chain.build_user_prompt(question, schema_context, feedback)},
    ]


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
    schema_context, failed = _retrieve_context(chain, question, k)
    if failed:
        return failed

    messages = _build_messages(chain, question, schema_context)
    try:
        full_sql = await _stream_llm(chain, messages)
    except Exception as exc:
        return InferenceResult(
            None, f"LLM call failed: {_describe_exc(exc)}", "llm_error", attempts=1
        )

    sql = chain.validator.clean_sql_output(full_sql).strip()
    if _is_empty_sql(sql):
        return InferenceResult(
            None, "LLM returned an empty response", "empty_response", attempts=1
        )
    return InferenceResult(sql, first_sql=sql, attempts=1)


# ---------------------------------------------------------------------------
# Inference WITH feedback/retry loop
# ---------------------------------------------------------------------------

def _check_sql(
    chain: NL2SQLChain, sql: str, executor: Optional[SpiderSQLiteExecutor]
) -> Tuple[bool, Optional[str]]:
    """
    Static validation, then (when ``executor`` is given) the query's own
    SQLite execution error. Only the predicted query is executed; the gold
    SQL is never consulted, so this is a legitimate inference-time signal.
    """
    is_valid, error = chain.validator.validate_query(sql)
    if not is_valid:
        return False, error
    if executor is not None:
        ok, exec_error, _rows = executor.execute(sql)
        if not ok:
            return False, f"SQLite execution error: {exec_error}"
    return True, None


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
    schema_context, failed = _retrieve_context(chain, question, k)
    if failed:
        return failed

    feedback_loop = SQLFeedbackLoop(chain.validator, max_iterations=max_iterations)
    first_sql: Optional[str] = None
    attempts = 0
    error: Optional[str] = None
    notes: List[str] = []

    while feedback_loop.should_continue():
        attempts += 1
        messages = _build_messages(
            chain, question, schema_context, feedback_loop.get_feedback_prompt()
        )
        try:
            full_sql = await _stream_llm(chain, messages)
        except Exception as exc:
            error = f"LLM call failed on attempt {attempts}: {_describe_exc(exc)}"
            notes.append(error)
            break

        sql = chain.validator.clean_sql_output(full_sql).strip()
        if first_sql is None:
            first_sql = sql

        ok, check_error = _check_sql(chain, sql, executor)
        feedback_loop.add_iteration(sql, check_error, success=ok)
        if ok:
            if attempts > 1:
                notes.append(f"attempt {attempts} passed")
            return InferenceResult(
                sql, first_sql=first_sql, attempts=attempts,
                recovered=attempts > 1, notes=notes,
            )
        error = f"attempt {attempts} rejected: {check_error}"
        notes.append(error)

    # No attempt passed the checks: keep attempt 1 (the single-pass answer).
    if _is_empty_sql(first_sql):
        kind = "llm_error" if first_sql is None else "empty_response"
        return InferenceResult(None, error, kind, attempts=attempts, notes=notes)
    return InferenceResult(
        first_sql,
        f"no attempt passed the checks, kept attempt 1 (last: {error})",
        first_sql=first_sql, attempts=attempts, notes=notes,
    )


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
) -> Dict:
    """
    Evaluate a list of Spider samples and return aggregated metrics.

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

    Returns:
        Dict with keys: total, exact_match, execution_accuracy, mode, k,
        skipped, inference_failures, failure_reasons and, in feedback mode,
        max_attempts, execution_feedback and feedback (loop diagnostics).
    """
    os.makedirs(_SPIDER_CHROMA_DIR, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=_SPIDER_CHROMA_DIR)
    embedding_fn = _build_embedding_fn()

    total = 0
    exact_correct = 0
    exec_correct = 0
    skipped = 0
    failure_reasons: Counter = Counter()

    # Feedback-loop diagnostics. "first_*" score attempt 1 of the same run,
    # i.e. what single-pass would have answered, so final - first is the
    # effect of feedback without sampling noise between two separate runs.
    first_exact_correct = 0
    first_exec_correct = 0
    retried = 0
    recovered = 0
    llm_calls = 0

    # Cache schema managers and chain instances per db_id to avoid
    # rebuilding embeddings for every question in the same database.
    _schema_cache: Dict[str, dict] = {}
    _chain_cache: Dict[str, NL2SQLChain] = {}

    eval_samples = samples if max_samples is None else samples[:max_samples]
    if use_feedback_loop:
        signal = "static validation + SQLite execution" if execution_feedback else "static validation"
        print(f"feedback loop ({signal}), max {feedback_max_iterations} attempts, k={k}")
    else:
        print(f"single-pass inference, k={k}")
    for idx, sample in enumerate(eval_samples):
        db_id = sample.db_id
        sqlite_path = get_sqlite_path(spider_path, db_id)
        prefix = f"[{idx+1}/{len(eval_samples)}]"

        if not os.path.exists(sqlite_path):
            skipped += 1
            if verbose:
                print(f"{prefix} SKIP  db={db_id} (SQLite file missing: {sqlite_path})")
            continue

        # Build/reuse schema + chain for this db_id
        if db_id not in _chain_cache:
            try:
                extractor = SQLiteSchemaExtractor(sqlite_path)
                schema_dict = extractor.extract()
                _schema_cache[db_id] = schema_dict

                collection_name = _build_collection(
                    chroma_client, embedding_fn, db_id, schema_dict
                )

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
            except Exception as exc:
                skipped += 1
                if verbose:
                    print(f"{prefix} ERROR db={db_id} schema build failed: {_describe_exc(exc)}")
                continue

        chain = _chain_cache[db_id]
        # The executor is bound to this sample's database file (its db_id).
        executor = SpiderSQLiteExecutor(sqlite_path)

        # Run inference — single-pass or with feedback/retry loop
        if use_feedback_loop:
            result = await _predict_sql_with_feedback(
                chain, sample.question, k=k,
                max_iterations=feedback_max_iterations,
                executor=executor if execution_feedback else None,
            )
            llm_calls += result.attempts
            retried += result.attempts > 1
            recovered += result.recovered
        else:
            result = await _predict_sql(chain, sample.question, k=k)
            llm_calls += result.attempts

        total += 1
        pred_sql = result.sql

        if not pred_sql:
            failure_reasons[result.failure_kind] += 1
            if verbose:
                print(f"{prefix} FAIL   db={db_id} | no SQL: {result.error}")
                for note in result.notes:
                    if note != result.error:
                        print(f"         [feedback] {note}")
            continue

        # Exact Match
        em = exact_match(pred_sql, sample.gold_sql)

        # Execution Accuracy
        try:
            ex, ex_error = executor.compare(pred_sql, sample.gold_sql)
        except Exception as exc:
            ex, ex_error = False, _describe_exc(exc)

        if em:
            exact_correct += 1
        if ex:
            exec_correct += 1

        if use_feedback_loop:
            if result.first_sql == pred_sql:
                first_em, first_ex = em, ex
            elif _is_empty_sql(result.first_sql):
                first_em, first_ex = False, False
            else:
                first_em = exact_match(result.first_sql, sample.gold_sql)
                first_ex, _ = executor.compare(result.first_sql, sample.gold_sql)
            first_exact_correct += first_em
            first_exec_correct += first_ex

        if verbose:
            status = "EM+EX" if (em and ex) else ("EM" if em else ("EX" if ex else "FAIL"))
            retry_info = f" (attempts: {result.attempts})" if result.attempts > 1 else ""
            print(
                f"{prefix} {status:<6} db={db_id}{retry_info} "
                f"| Q: {sample.question[:60]}"
            )
            for note in result.notes:
                print(f"         [feedback] {note}")
            if not ex:
                print(f"         reason: {ex_error}")
                print(f"         pred:   {pred_sql[:200]}")

    metrics = compute_metrics(total, exact_correct, exec_correct)
    metrics["mode"] = "feedback" if use_feedback_loop else "single-pass"
    metrics["k"] = k
    metrics["skipped"] = skipped
    metrics["inference_failures"] = sum(failure_reasons.values())
    metrics["failure_reasons"] = dict(failure_reasons)
    metrics["llm_calls"] = llm_calls
    if use_feedback_loop:
        metrics["max_attempts"] = feedback_max_iterations
        metrics["execution_feedback"] = execution_feedback
        first = compute_metrics(total, first_exact_correct, first_exec_correct)
        metrics["feedback"] = {
            "retried": retried,
            "recovered": recovered,
            "exhausted": retried - recovered,
            "first_attempt_exact_match": first["exact_match"],
            "first_attempt_execution_accuracy": first["execution_accuracy"],
        }
    return metrics
