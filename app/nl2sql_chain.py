"""
NL2SQL Chain Module - Schema-RAG Implementation

Core orchestration class for the Schema-RAG NL2SQL pipeline:
1. Natural language question input
2. Schema retrieval via vector similarity
3. Context enrichment with schema elements
4. SQL generation via LLM

This class is consumed by the Spider evaluation harness
(``app.spider_eval.spider_runner``), which drives retrieval, validation and
the feedback/retry loop itself.
"""

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
from app.system_prompt import (
    SYSTEM_PROMPT_NL2SQL_FA,
    SYSTEM_PROMPT_NL2SQL_EN,
    SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA,
    SYSTEM_PROMPT_NL2SQL_FEEDBACK_EN,
)

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

OLLAMA_TEMPERATURE: float = 0.1
OLLAMA_MODEL_NAME: str = "gemma4:12b".strip().lower()
OLLAMA_HOST: str = "http://127.0.0.1:11434".strip().lower()
EMBEDDING_MODEL_DIR = env.embedding_model_dir


class NL2SQLChain:
    """
    Orchestrates the Schema-RAG pipeline for NL2SQL generation.

    Architecture:
    User Question → Schema Retrieval → Context Assembly → SQL Generation → Validation
    """

    def __init__(
        self, schema_manager: SchemaManager, collection_name: str, culture: str = "en"
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
        """Get appropriate system prompt based on culture and context"""
        if is_feedback:
            return (
                SYSTEM_PROMPT_NL2SQL_FEEDBACK_FA
                if self.culture == "fa"
                else SYSTEM_PROMPT_NL2SQL_FEEDBACK_EN
            )
        else:
            return (
                SYSTEM_PROMPT_NL2SQL_FA
                if self.culture == "fa"
                else SYSTEM_PROMPT_NL2SQL_EN
            )

    def retrieve_schema_elements(
        self, question: str, n_results: int = 10
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
            name=self.collection_name, embedding_function=self.embedding_fn
        )

        # Query for relevant schema elements
        results = collection.query(query_texts=[question], n_results=n_results)

        if not results["documents"] or not results["documents"][0]:
            return [], []

        documents = list(results["documents"][0])
        distances = list(results["distances"][0])

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
        self, messages: List[Dict[str, str]], stream: bool = True
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
            options={"temperature": OLLAMA_TEMPERATURE},
        )

        return chat_completion

    async def generate_sql_openai(
        self, messages: List[Dict[str, str]], stream: bool = True
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
            model="gpt-4o-mini", messages=messages, temperature=0.1, stream=stream
        )

        return chat_completion
