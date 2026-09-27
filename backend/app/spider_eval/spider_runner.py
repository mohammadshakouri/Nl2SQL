"""
Spider Runner

Main evaluation loop for the Spider 1 benchmark.

Architecture
------------
For each Spider sample the runner:
1. Extracts the SQLite schema → SchemaManager-compatible JSON dict
2. Loads (or reuses) a temporary ChromaDB collection
   named ``Schema_spider_<db_id>``
3. Instantiates NL2SQLChain with that collection
4. Runs a single-pass inference (no feedback retries, no DB logging)
5. Captures the generated SQL
6. Evaluates Exact Match and Execution Accuracy
7. Returns aggregated metrics

The existing FastAPI endpoint, PostgreSQL logger, and production
vector-store initialisation logic are never touched.
"""

import asyncio
import os
from typing import Dict, List, Optional

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
from app.spider_eval.spider_evaluator import exact_match, execution_match, compute_metrics
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
            choice = chunk.choices[0]
            if choice.delta and choice.delta.content:
                full_sql += choice.delta.content
            if choice.finish_reason is not None:
                break
    return full_sql


# ---------------------------------------------------------------------------
# Single-pass inference  (no feedback retries)
# ---------------------------------------------------------------------------

async def _infer_sql(
    chain: NL2SQLChain,
    question: str,
    n_results: int = 15,
    verbose: bool = False,
) -> Optional[str]:
    """
    Single-pass SQL inference – no feedback loop, no DB logging.

    Returns the generated SQL string, or None on failure.
    """
    retrieved_elements, _ = chain.retrieve_schema_elements(question, n_results=n_results)
    if not retrieved_elements:
        if verbose:
            print("      [debug] no schema elements retrieved")
        return None

    schema_context = chain.build_schema_context(retrieved_elements)
    user_prompt = chain.build_user_prompt(question, schema_context)
    system_prompt = chain.get_system_prompt(is_feedback=False)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        full_sql = await _stream_llm(chain, messages)
    except Exception as exc:
        if verbose:
            print(f"      [debug] LLM call failed: {exc}")
        return None

    if hasattr(chain.validator, "clean_sql_output"):
        full_sql = chain.validator.clean_sql_output(full_sql)

    return full_sql.strip() if full_sql.strip() else None


# ---------------------------------------------------------------------------
# Inference WITH feedback/retry loop (validation-only; see SQLFeedbackLoop)
# ---------------------------------------------------------------------------

async def _infer_sql_with_feedback(
    chain: NL2SQLChain,
    question: str,
    n_results: int = 15,
    max_iterations: int = 4,
    verbose: bool = False,
) -> Optional[str]:
    """
    SQL inference with the same ``SQLFeedbackLoop`` validation + retry loop
    used elsewhere in this project, without SSE streaming or database logging.

    Returns the final (valid) SQL string, or None if all iterations fail.
    """
    retrieved_elements, _ = chain.retrieve_schema_elements(question, n_results=n_results)
    if not retrieved_elements:
        if verbose:
            print("      [debug] no schema elements retrieved")
        return None

    schema_context = chain.build_schema_context(retrieved_elements)
    feedback_loop = SQLFeedbackLoop(chain.validator, max_iterations=max_iterations)
    full_sql = ""

    while feedback_loop.should_continue():
        feedback_prompt = feedback_loop.get_feedback_prompt()
        user_prompt = chain.build_user_prompt(question, schema_context, feedback_prompt)
        system_prompt = chain.get_system_prompt(is_feedback=feedback_prompt is not None)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            full_sql = await _stream_llm(chain, messages)
        except Exception as exc:
            if verbose:
                print(f"      [debug] LLM call failed: {exc}")
            return None

        clean_sql = (
            chain.validator.clean_sql_output(full_sql)
            if hasattr(chain.validator, "clean_sql_output")
            else full_sql
        )

        is_valid, error = chain.validator.validate_query(clean_sql)
        if not is_valid:
            if verbose:
                print(f"      [debug] validation failed (retry): {error}")
            feedback_loop.add_iteration(clean_sql, error, success=False)
            full_sql = ""
            continue

        feedback_loop.add_iteration(clean_sql, None, success=True)
        return clean_sql.strip() if clean_sql.strip() else None

    # All iterations exhausted without a valid result
    return None


# ---------------------------------------------------------------------------
# Public evaluation entry point
# ---------------------------------------------------------------------------

async def run_spider_evaluation(
    samples: List[SpiderSample],
    spider_path: str,
    verbose: bool = True,
    max_samples: Optional[int] = None,
    use_feedback_loop: bool = False,
    feedback_max_iterations: int = 3,
) -> Dict:
    """
    Evaluate a list of Spider samples and return aggregated metrics.

    Args:
        samples: List of SpiderSample objects from spider_loader.
        spider_path: Root path to Spider dataset (contains database/ folder).
        verbose: If True, print per-sample progress to stdout.
        max_samples: Optional cap on the number of samples to evaluate.
        use_feedback_loop: If True, use the validation + retry loop
                           (SQLFeedbackLoop). If False, single-pass only.
        feedback_max_iterations: Max retry iterations when use_feedback_loop=True.

    Returns:
        Dict with keys: total, exact_match, execution_accuracy, mode
    """
    os.makedirs(_SPIDER_CHROMA_DIR, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=_SPIDER_CHROMA_DIR)
    embedding_fn = _build_embedding_fn()

    total = 0
    exact_correct = 0
    exec_correct = 0

    # Cache schema managers and chain instances per db_id to avoid
    # rebuilding embeddings for every question in the same database.
    _schema_cache: Dict[str, dict] = {}
    _chain_cache: Dict[str, NL2SQLChain] = {}

    eval_samples = samples if max_samples is None else samples[:max_samples]
    print("using feedback loop" if use_feedback_loop else "single-pass inference")
    for idx, sample in enumerate(eval_samples):
        db_id = sample.db_id
        sqlite_path = get_sqlite_path(spider_path, db_id)

        if not os.path.exists(sqlite_path):
            if verbose:
                print(
                    f"[{idx+1}/{len(eval_samples)}] SKIP  db={db_id} "
                    f"(SQLite file missing: {sqlite_path})"
                )
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
                    culture="en",
                )
                # Inject the shared chroma client and embedding_fn so we
                # don't open a second client pointed at the wrong directory.
                chain.chroma_client = chroma_client
                chain.embedding_fn = embedding_fn

                _chain_cache[db_id] = chain
            except Exception as exc:
                if verbose:
                    print(
                        f"[{idx+1}/{len(eval_samples)}] ERROR db={db_id} "
                        f"schema build failed: {exc}"
                    )
                continue

        chain = _chain_cache[db_id]

        # Run inference — single-pass or with feedback/retry loop
        if use_feedback_loop:
            pred_sql = await _infer_sql_with_feedback(
                chain, sample.question,
                max_iterations=feedback_max_iterations,
                verbose=verbose,
            )
        else:
            pred_sql = await _infer_sql(chain, sample.question, verbose=verbose)

        if not pred_sql:
            total += 1
            if verbose:
                print(
                    f"[{idx+1}/{len(eval_samples)}] FAIL  db={db_id} "
                    f"| inference returned nothing"
                )
            continue

        # Exact Match
        em = exact_match(pred_sql, sample.gold_sql)

        # Execution Accuracy
        try:
            executor = SpiderSQLiteExecutor(sqlite_path)
            ex = execution_match(pred_sql, sample.gold_sql, executor)
        except Exception:
            ex = False

        total += 1
        if em:
            exact_correct += 1
        if ex:
            exec_correct += 1

        if verbose:
            status = "EM+EX" if (em and ex) else ("EM" if em else ("EX" if ex else "FAIL"))
            print(
                f"[{idx+1}/{len(eval_samples)}] {status:<6} db={db_id} "
                f"| Q: {sample.question[:60]}"
            )

    metrics = compute_metrics(total, exact_correct, exec_correct)
    metrics["mode"] = "feedback" if use_feedback_loop else "single-pass"
    return metrics
