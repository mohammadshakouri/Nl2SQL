"""
NL2SQL Chain Module - Schema-RAG Implementation

This module orchestrates the complete NL2SQL pipeline:
1. Natural language question input
2. Schema retrieval via vector similarity
3. Context enrichment with schema elements
4. SQL generation via LLM
5. Validation and feedback loop
"""

import os
import json
import uuid
import jdatetime
from typing import List, Dict, Tuple, Optional, AsyncGenerator
import chromadb
from chromadb import Collection
from chromadb.utils import embedding_functions
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from openai import AsyncOpenAI
from ollama import AsyncClient, ChatResponse
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer
from chromadb.api.types import EmbeddingFunction


import app.dotenv as env
import app.utilities as utils
from app.schema_manager import SchemaManager
from app.sql_validator import SQLValidator, SQLFeedbackLoop
from app.system_prompt import (
    SYSTEM_PROMPT_NL2SQL_FA,
    SYSTEM_PROMPT_NL2SQL_EN,
    SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA,
    SYSTEM_PROMPT_NL2SQL_FEEDBACK_EN
)

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

OLLAMA_TEMPERATURE: float = 0.1
OLLAMA_MODEL_NAME: str = "gemma3:4b".strip().lower()
OLLAMA_HOST: str = "http://127.0.0.1:11434".strip().lower()
Model_Dir = r"C:\Users\Mohammad\.cache\huggingface\hub\models--google--embeddinggemma-300m\snapshots\57c266a740f537b4dc058e1b0cda161fd15afa75"

# duplicate a small portion of the database configuration that exists in
# ``main.py``.  This avoids a circular import while still allowing the
# streaming pipeline to persist generated messages back into the same
# database used by the FastAPI application.
#
# Execution validation (when requested) uses a separate session that is
# provided by callers; therefore the two sessions intentionally remain
# independent.

EXECUTION_DATABASE_URL = env.execution_database_url
_engineMssql = create_async_engine(EXECUTION_DATABASE_URL)
ExecutionDB = async_sessionmaker(bind=_engineMssql, class_=AsyncSession, expire_on_commit=False)

MAIN_DATABASE_URL = env.main_database_url
_enginePostgre = create_async_engine(MAIN_DATABASE_URL)
MainDB = async_sessionmaker(bind=_enginePostgre, class_=AsyncSession, expire_on_commit=False)


class NL2SQLChain:
    """
    Orchestrates the Schema-RAG pipeline for NL2SQL generation.
    
    Architecture:
    User Question → Schema Retrieval → Context Assembly → SQL Generation → Validation
    """
    
    def __init__(
        self,
        schema_manager: SchemaManager,
        collection_name: str,
        culture: str = "fa"
    ):
        """
        Initialize NL2SQL chain
        
        Args:
            schema_manager: SchemaManager instance with loaded schema
            collection_name: Name of ChromaDB collection for schema embeddings
            culture: Language/culture code (fa or en)
        """
        self.schema_manager = schema_manager
        self.collection_name = collection_name
        self.culture = culture
        self.validator = SQLValidator(schema_manager)
        
        # Initialize embedding function
        if USE_LOCAL_EMBEDDING:
            self.embedding_fn = LocalSTEmbeddingFunction(Model_Dir, device="cpu")
        else:
            self.embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=OPENAI_API_KEY,
                model_name=utils.OPENAI_EMBEDDING_MODEL_NAME,
        )
        
        # Initialize ChromaDB client
        self.chroma_client = chromadb.PersistentClient(utils.CHROMADB_PERSIST_DIRECTORY)
    
    def get_system_prompt(self, is_feedback: bool = False) -> str:
        """Get appropriate system prompt based on culture and context"""
        if is_feedback:
            return SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA if self.culture == "fa" else SYSTEM_PROMPT_NL2SQL_FEEDBACK_EN
        else:
            return SYSTEM_PROMPT_NL2SQL_FA if self.culture == "fa" else SYSTEM_PROMPT_NL2SQL_EN
    
    def retrieve_schema_elements(
        self, 
        question: str, 
        n_results: int = 10
    ) -> Tuple[List[str], List[float]]:
        """
        Stage 3: Schema Linking via Vector Retrieval
        
        Retrieves relevant schema elements (tables, columns, relations) based on question.
        
        Args:
            question: User's natural language question
            n_results: Number of schema elements to retrieve
        
        Returns:
            Tuple of (retrieved_documents, distances)
        """
        # Get collection
        collection: Collection = self.chroma_client.get_collection(
            name=self.collection_name,
            embedding_function=self.embedding_fn
        )
        
        # Query for relevant schema elements
        results = collection.query(
            query_texts=[question],
            n_results=n_results
        )
        
        if not results["documents"] or not results["documents"][0]:
            return [], []
        
        # Filter by relevance threshold
        documents = []
        distances = []
        
        for doc, dist in zip(results["documents"][0], results["distances"][0]):
            # Only include highly relevant schema elements
            # if dist < 1:  # Adjust threshold as needed
                documents.append(doc)
                distances.append(dist)
        
        return documents, distances
    
    def build_schema_context(self, retrieved_elements: List[str]) -> str:
        """
        Stage 4: Context Enrichment (Prompt Assembly)
        
        Constructs structured schema context from retrieved elements.
        
        Args:
            retrieved_elements: List of retrieved schema element descriptions
        
        Returns:
            Formatted schema context string
        """
        if not retrieved_elements:
            return "No relevant schema found."
        
        # Organize by type
        tables = []
        columns = []
        relations = []
        
        for element in retrieved_elements:
            if " Table:" in element:
                tables.append(element)
            elif " Column:" in element:
                columns.append(element)
            elif "Relation:" in element:
                relations.append(element)
        
        # Build context
        context = "Available Database Schema:\n\n"
        
        if tables:
            context += "Tables:\n"
            for table in tables:
                context += f"  - {table}\n"
            context += "\n"
        
        if columns:
            context += "Columns:\n"
            for column in columns:
                context += f"  - {column}\n"
            context += "\n"
        
        if relations:
            context += "Relations:\n"
            for relation in relations:
                context += f"  - {relation}\n"
            context += "\n"
        
        return context
    
    def build_user_prompt(
        self, 
        question: str, 
        schema_context: str,
        feedback: Optional[str] = None,
        user_semantic_feedback: Optional[str] = None,
    ) -> str:
        """
        Build complete user prompt with question and schema context
        
        Args:
            question: User's natural language question
            schema_context: Retrieved schema context
            feedback: Optional feedback from previous SQL error (validation loop)
            user_semantic_feedback: Optional end-user comment describing a semantic error
        
        Returns:
            Complete user prompt string
        """
        if feedback:
            # Feedback iteration prompt (validation / syntax error)
            prompt = f"Syntax error you should fix: {feedback}\n\n"
            if user_semantic_feedback:
                prompt += f"User feedback that you should fix it: {user_semantic_feedback}\n\n"
            prompt += f"User Question:\n{question}\n\n"
            prompt += f"{schema_context}\n"
            prompt += "Generate corrected SQL query:\n"
        else:
            prompt = ""
            if user_semantic_feedback:
                prompt += f"User feedback that you should fix it: {user_semantic_feedback}\n\n"
            prompt += f"User Question:\n{question}\n\n"
            prompt += f"{schema_context}\n"
            
            if self.culture == "fa":
                prompt += "قوانین:\n"
                prompt += "- فقط از Schema ارائه شده استفاده کنید\n"
                prompt += "- جدول یا ستون جدید اختراع نکنید\n"
                prompt += "- فقط SQL خروجی دهید\n\n"
                prompt += "SQL Query:\n"
            else:
                prompt += "Rules:\n"
                prompt += "- Use only provided schema\n"
                prompt += "- Do not invent tables or columns\n"
                prompt += "- Output SQL only\n\n"
                prompt += "SQL Query:\n"
        
        return prompt
    
    async def generate_sql_ollama(
        self,
        messages: List[Dict[str, str]],
        stream: bool = True
    ) -> ChatResponse:
        """
        Generate SQL using local Ollama LLM
        
        Args:
            messages: List of message dicts
            stream: Whether to stream response
        
        Returns:
            ChatResponse from Ollama
        """
        ollama_client = AsyncClient(host=OLLAMA_HOST)
        
        chat_completion = await ollama_client.chat(
            think=False,
            stream=stream,
            messages=messages,
            model=OLLAMA_MODEL_NAME,
            options={"temperature": OLLAMA_TEMPERATURE}
        )
        
        return chat_completion
    
    async def generate_sql_openai(
        self,
        messages: List[Dict[str, str]],
        stream: bool = True
    ):
        """
        Generate SQL using OpenAI LLM
        
        Args:
            messages: List of message dicts
            stream: Whether to stream response
        
        Returns:
            OpenAI chat completion stream
        """
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        chat_completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            stream=stream
        )
        
        return chat_completion



def _load_schema_manager_for_collection(collection_name: str) -> SchemaManager:
    """Helper to create a SchemaManager and load the JSON file corresponding to a
    Chroma collection name.

    The schema files live under ``data_schema`` and are named
    ``<schema_name>_schema.json``.  The Chroma collection names are of the form
    ``Schema_<schema_name>`` so we strip the prefix and try to load the
    matching file.  If the file is missing we return an empty manager (the
    validator will simply skip schema checks).
    """
    manager = SchemaManager()
    schema_name = collection_name.replace("Schema_", "")
    schema_path = os.path.join("data_schema", f"{schema_name}_schema.json")
    if os.path.exists(schema_path):
        manager.load_schema_from_json(schema_path)
    return manager


async def LoadNL2SQLChain(
    thread_id: str,
    question: str,
    schema_collection_name: str,
    culture: str = "fa",
    validate_execution: bool = True,
    user_semantic_feedback: Optional[str] = None,
) -> "AsyncGenerator[str, None]":
    """
    Extra keyword arg ``user_semantic_feedback`` carries the end-user's natural-
    language comment explaining a semantic error in the previously generated SQL.
    When provided it is injected into every prompt so the LLM can fix the
    semantic mistake the automated validation loop cannot detect.
    """
    """
    1. Vector retrieval of relevant schema elements
    2. Construction of a schema context string
    3. A feedback/validation loop (syntax + schema checks and optional
       execution validation)
    4. Streaming of generated SQL tokens as Server‑Sent Events
    5. Logging of the request into the database when the pipeline completes

    Yields
    ------
    str
        Server‑sent‑event formatted strings (``data: {...}\n\n``).  The first
        event is ``on_start`` and the last is ``on_end`` (or ``on_error`` on
        failure).
    """
    # ------------------------------------------------------------------
    # Event utilities
    # ------------------------------------------------------------------
    def sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    # generate run/thread identifiers
    run_id = str(uuid.uuid4())
    if not thread_id or not thread_id.strip():
        thread_id = str(uuid.uuid4())

    start_time = jdatetime.datetime.now()

    # send start event
    yield sse({
        "event": "on_start",
        "run_id": run_id,
        "thread_id": thread_id,
        "type": "nl2sql",
    })

    # sanity check
    if len(question) > 250:
        yield sse({
            "event": "on_error",
            "data": "Question is too long. Maximum 250 characters allowed.",
        })
        return

    # prepare chain with schema manager
    schema_manager = _load_schema_manager_for_collection(schema_collection_name)
    chain = NL2SQLChain(schema_manager, schema_collection_name, culture)

    # retrieval + context
    retrieved_elements, distances = chain.retrieve_schema_elements(question, n_results=10)
    if not retrieved_elements:
        yield sse({
            "event": "on_error",
            "data": "No relevant schema elements found for this question",
        })
        return
    schema_context = chain.build_schema_context(retrieved_elements)

    # feedback loop set up
    feedback_loop = SQLFeedbackLoop(chain.validator, max_iterations=3)
    full_sql = ""

    # iterate until validation succeeds or iterations are exhausted
    while feedback_loop.should_continue():
        feedback_prompt = feedback_loop.get_feedback_prompt()
        user_prompt = chain.build_user_prompt(question, schema_context, feedback_prompt, user_semantic_feedback)
        system_prompt = chain.get_system_prompt(is_feedback=feedback_prompt is not None)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # call the appropriate LLM in streaming mode
        if USE_LOCAL_LLM:
            chat_resp = await chain.generate_sql_ollama(messages, stream=True)
            async for chunk in chat_resp:
                if hasattr(chunk, "message") and chunk.message and chunk.message.content:
                    token = chunk.message.content
                    full_sql += token
                    yield sse({"event": "on_stream", "data": token})
                if getattr(chunk, "done", False):
                    break
        else:
            chat_resp = await chain.generate_sql_openai(messages, stream=True)
            async for chunk in chat_resp:
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    token = delta.content
                    full_sql += token
                    yield sse({"event": "on_stream", "data": token})
                if choice.finish_reason is not None:
                    break

        # validation of the attempt
        clean_sql = chain.validator.clean_sql_output(full_sql) if hasattr(chain.validator, "clean_sql_output") else full_sql
        is_valid, error = chain.validator.validate_query(clean_sql)
        if not is_valid:
            # inform client about the validation failure before retrying
            yield sse({
                "event": "on_retry",
                "data": f"Validation failed: {error}. Retrying with feedback...",
            })
            feedback_loop.add_iteration(clean_sql, error, success=False)
            # prepare for next iteration (clear prior output)
            full_sql = ""
            continue

        # optionally execute the query to double-check results
        if validate_execution:
            async with ExecutionDB() as db:
                success, exec_error, _ = await chain.validator.execute_and_validate(
                    clean_sql, db, fetch_results=False
                )
            if not success:
                yield sse({
                    "event": "on_retry",
                    "data": f"Execution validation failed: {exec_error}. Retrying...",
                })
                feedback_loop.add_iteration(clean_sql, exec_error, success=False)
                full_sql = ""
                continue

        feedback_loop.add_iteration(clean_sql, None, success=True)
        break

    end_time = jdatetime.datetime.now()
    latency = (end_time - start_time).total_seconds()

    # persist message to database
    from app.models import Message

    async with MainDB() as db:
        message = Message(
            run_id=run_id,
            thread_id=thread_id,
            start_time=start_time.isoformat(),
            latency=latency,
            input=question,
            output=full_sql,
            culture=culture,
            schema_collection_name=schema_collection_name.replace("Schema_", ""),
            is_user_authenticated="yes",
            status="generated",
            feedback=0,
        )
        db.add(message)
        await db.commit()

    # final event
    yield sse({
        "event": "on_end",
        "sql": full_sql,
        "latency": latency,
    })




class LocalSTEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_dir: str, device: str = "cpu"):
        self._model_dir = model_dir
        self._device = device
        self._model = SentenceTransformer(
            model_dir,
            local_files_only=True,
            device=device,
        )
        # warm-up forces any lazy loads now (still offline)
        _ = self._model.encode(["warmup"], normalize_embeddings=True)

    def name(self) -> str:
        # Must be a METHOD for your Chroma version
        return f"SentenceTransformer({self._model_dir})"

    def __call__(self, texts):
        return self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()