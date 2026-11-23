"""
NL2SQL Chain Module - Schema-RAG Implementation

Core orchestration class for the Schema-RAG NL2SQL pipeline:
1. Natural language question input
2. Schema retrieval via vector similarity
3. Context enrichment with schema elements
4. SQL generation via LLM

This class is consumed by the evaluation harness
(``app.evaluation.runner``; Spider and BIRD), which drives retrieval,
validation and the feedback/retry loop itself.
"""

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import List, Dict, Tuple, Optional
import chromadb
from chromadb import Collection
from chromadb.utils import embedding_functions
from openai import AsyncOpenAI
from ollama import AsyncClient, ChatResponse

import app.dotenv as env
import app.utilities as utils
from app.utilities import LocalSTEmbeddingFunction
from app.schema_manager import SchemaManager
from app.sql_validator import SQLValidator
from app.system_prompt import SYSTEM_PROMPT_NL2SQL, SYSTEM_PROMPT_NL2SQL_FEEDBACK

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

OLLAMA_TEMPERATURE: float = 0.1
OLLAMA_MODEL_NAME: str = "gemma4:12b".strip().lower()
OLLAMA_HOST: str = "http://ai.ig.local:11434".strip().lower()
EMBEDDING_MODEL_DIR = env.embedding_model_dir

# OpenAI path defaults. The model/temperature/reasoning effort can be overridden
# per run with configure_llm() (cli_eval.py --model / --temperature /
# --reasoning-effort), and the effective values are written to the run manifest.
OPENAI_MODEL_NAME: str = "gpt-6-luna"
OPENAI_TEMPERATURE: float = 1
# Sent as ``reasoning_effort``; None omits the parameter (the model's own default).
OPENAI_REASONING_EFFORT: Optional[str] = "low"
# Explicit so the values are recorded rather than inherited from SDK defaults:
# a hung request must not stall a paid run for the SDK's 10-minute default, and
# transient errors (429/5xx/connection) are retried by the SDK before a sample
# is ever scored as an inference failure.
OPENAI_TIMEOUT_SECONDS: float = 120.0
OPENAI_MAX_RETRIES: int = 5

_UNSET = object()


@dataclass
class LLMSettings:
    """The generation settings in effect for this process."""
    provider: str
    model: str
    temperature: Optional[float]
    host: Optional[str]
    timeout_s: Optional[float] = None
    max_retries: Optional[int] = None
    reasoning_effort: Optional[str] = None
    """OpenAI only; Ollama thinking is always off (``think=False``)."""


_model_override: Optional[str] = None
_temperature_override = _UNSET
_reasoning_effort_override = _UNSET


def configure_llm(
    model: Optional[str] = None, temperature=_UNSET, reasoning_effort=_UNSET
) -> None:
    """
    Override the model, temperature and/or reasoning effort for the active provider.

    ``temperature=None`` / ``reasoning_effort=None`` omit the parameter from the
    request entirely, for models that only accept their default.
    """
    global _model_override, _temperature_override, _reasoning_effort_override
    if model:
        _model_override = model
    if temperature is not _UNSET:
        _temperature_override = temperature
    if reasoning_effort is not _UNSET:
        _reasoning_effort_override = reasoning_effort


def get_llm_settings() -> LLMSettings:
    """The effective settings for the provider selected by USE_LOCAL_LLM."""
    if USE_LOCAL_LLM:
        temperature = OLLAMA_TEMPERATURE if _temperature_override is _UNSET else _temperature_override
        return LLMSettings(
            provider="ollama",
            model=_model_override or OLLAMA_MODEL_NAME,
            temperature=temperature,
            host=OLLAMA_HOST,
        )
    temperature = OPENAI_TEMPERATURE if _temperature_override is _UNSET else _temperature_override
    base_url = os.getenv("OPENAI_BASE_URL")
    host = (urlparse(base_url).hostname or base_url) if base_url else "api.openai.com (SDK default)"
    effort = OPENAI_REASONING_EFFORT if _reasoning_effort_override is _UNSET else _reasoning_effort_override
    return LLMSettings(
        provider="openai",
        model=_model_override or OPENAI_MODEL_NAME,
        temperature=temperature,
        host=host,
        timeout_s=OPENAI_TIMEOUT_SECONDS,
        max_retries=OPENAI_MAX_RETRIES,
        reasoning_effort=effort,
    )


_openai_client_cache: Optional[Tuple[object, AsyncOpenAI]] = None


def _openai_client() -> AsyncOpenAI:
    """One AsyncOpenAI client per event loop (not one per call)."""
    global _openai_client_cache
    loop = asyncio.get_running_loop()
    if _openai_client_cache is None or _openai_client_cache[0] is not loop:
        _openai_client_cache = (
            loop,
            AsyncOpenAI(
                api_key=OPENAI_API_KEY,
                timeout=OPENAI_TIMEOUT_SECONDS,
                max_retries=OPENAI_MAX_RETRIES,
            ),
        )
    return _openai_client_cache[1]


class NL2SQLChain:
    """
    Orchestrates the Schema-RAG pipeline for NL2SQL generation.

    Architecture:
    User Question → Schema Retrieval → Context Assembly → SQL Generation → Validation
    """

    def __init__(self, schema_manager: SchemaManager, collection_name: str):
        """
        Initialize NL2SQL chain

        Args:
            schema_manager: SchemaManager instance with loaded schema
            collection_name: Name of ChromaDB collection for schema embeddings
        """
        self.schema_manager = schema_manager
        self.collection_name = collection_name
        self.validator = SQLValidator(schema_manager)

        # Initialize embedding function
        if USE_LOCAL_EMBEDDING:
            self.embedding_fn = LocalSTEmbeddingFunction(
                EMBEDDING_MODEL_DIR, device="cpu"
            )
        else:
            self.embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=OPENAI_API_KEY,
                model_name=utils.OPENAI_EMBEDDING_MODEL_NAME,
            )

        # Initialize ChromaDB client
        self.chroma_client = chromadb.PersistentClient(utils.CHROMADB_PERSIST_DIRECTORY)

    def get_system_prompt(self, is_feedback: bool = False) -> str:
        """Get the system prompt for a first attempt or a feedback retry"""
        return SYSTEM_PROMPT_NL2SQL_FEEDBACK if is_feedback else SYSTEM_PROMPT_NL2SQL

    def retrieve_schema_units(self, question: str, n_results: int) -> List[Dict]:
        """
        Stage 3: Schema Linking via Vector Retrieval

        Retrieves the Top-K schema units (tables, columns, relations) for the
        question, keeping each unit's collection id and distance so the
        retrieval can be analysed afterwards (e.g. Recall@K).

        Args:
            question: User's natural language question
            n_results: Number of schema units to retrieve

        Returns:
            List of {"rank", "id", "text", "distance"} dicts, best first.
        """
        collection: Collection = self.chroma_client.get_collection(
            name=self.collection_name, embedding_function=self.embedding_fn
        )

        results = collection.query(query_texts=[question], n_results=n_results)

        if not results["documents"] or not results["documents"][0]:
            return []

        documents = list(results["documents"][0])
        distances = list(results["distances"][0])
        ids = list(results["ids"][0])

        return [
            {"rank": rank, "id": unit_id, "text": text, "distance": float(distance)}
            for rank, (unit_id, text, distance) in enumerate(
                zip(ids, documents, distances), start=1
            )
        ]

    def retrieve_schema_elements(
        self, question: str, n_results: int
    ) -> Tuple[List[str], List[float]]:
        """
        Same retrieval as :meth:`retrieve_schema_units`, as parallel lists.

        Returns:
            Tuple of (retrieved_documents, distances)
        """
        units = self.retrieve_schema_units(question, n_results)
        return [u["text"] for u in units], [u["distance"] for u in units]

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
        evidence: Optional[str] = None,
    ) -> str:
        """
        Build complete user prompt with question and schema context

        Args:
            question: User's natural language question
            schema_context: Retrieved schema context
            feedback: Optional description of previous failed attempts
                      (from ``SQLFeedbackLoop.get_feedback_prompt``)
            evidence: Optional external knowledge that comes with the question
                      (BIRD); without it the prompt has no such section

        Returns:
            Complete user prompt string
        """
        prompt = f"User Question:\n{question}\n\n"
        if evidence:
            prompt += f"External Knowledge:\n{evidence}\n\n"
        prompt += f"{schema_context}\n"

        if feedback:
            prompt += f"{feedback.rstrip()}\n\n"

        prompt += "Rules:\n"
        prompt += "- Use only provided schema\n"
        prompt += "- Do not invent tables or columns\n"
        prompt += "- Output SQL only\n\n"
        prompt += "Corrected SQL Query:\n" if feedback else "SQL Query:\n"

        return prompt

    @staticmethod
    async def generate_sql_ollama(
        messages: List[Dict[str, str]], stream: bool = True
    ) -> ChatResponse:
        """
        Generate SQL using local Ollama LLM

        Args:
            messages: List of message dicts
            stream: Whether to stream response

        Returns:
            ChatResponse from Ollama
        """
        settings = get_llm_settings()
        ollama_client = AsyncClient(host=OLLAMA_HOST)

        options = {}
        if settings.temperature is not None:
            options["temperature"] = settings.temperature

        chat_completion = await ollama_client.chat(
            think=False,
            stream=stream,
            messages=messages,
            model=settings.model,
            options=options,
        )

        return chat_completion

    @staticmethod
    async def generate_sql_openai(
        messages: List[Dict[str, str]],
        stream: bool = True,
        include_usage: bool = True,
    ):
        """
        Generate SQL using the OpenAI chat completions API

        Args:
            messages: List of message dicts
            stream: Whether to stream response
            include_usage: Ask the API to send token usage in a final stream
                           chunk (needed to tally the cost of a run)

        Returns:
            OpenAI chat completion stream
        """
        settings = get_llm_settings()
        request = {"model": settings.model, "messages": messages, "stream": stream}
        if settings.temperature is not None:
            request["temperature"] = settings.temperature
        if settings.reasoning_effort is not None:
            request["reasoning_effort"] = settings.reasoning_effort
        if stream and include_usage:
            request["stream_options"] = {"include_usage": True}

        return await _openai_client().chat.completions.create(**request)
