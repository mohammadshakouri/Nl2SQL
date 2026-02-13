"""
NL2SQL Chain Module - Schema-RAG Implementation

This module orchestrates the complete NL2SQL pipeline:
1. Natural language question input
2. Schema retrieval via vector similarity
3. Context enrichment with schema elements
4. SQL generation via LLM
5. Validation and feedback loop
"""

import json
from typing import List, Dict, Tuple, Optional
import chromadb
from chromadb import Collection
from chromadb.utils import embedding_functions
from sqlalchemy.ext.asyncio import AsyncSession
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
            embedding_fn = LocalSTEmbeddingFunction(Model_Dir, device="cpu")
        else:
            embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
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
            if dist < 1:  # Adjust threshold as needed
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
        feedback: Optional[str] = None
    ) -> str:
        """
        Build complete user prompt with question and schema context
        
        Args:
            question: User's natural language question
            schema_context: Retrieved schema context
            feedback: Optional feedback from previous SQL error
        
        Returns:
            Complete user prompt string
        """
        if feedback:
            # Feedback iteration prompt
            prompt = f"{feedback}\n\n"
            prompt += f"User Question:\n{question}\n\n"
            prompt += f"{schema_context}\n"
            prompt += "Generate corrected SQL query:\n"
        else:
            # Initial prompt
            prompt = f"User Question:\n{question}\n\n"
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
    
    async def execute_pipeline(
        self,
        question: str,
        validate_execution: bool = False,
        db_session: Optional[AsyncSession] = None,
        max_feedback_iterations: int = 3
    ) -> Dict:
        """
        Execute complete NL2SQL pipeline with feedback loop
        
        Args:
            question: Natural language question
            validate_execution: Whether to execute SQL for validation
            db_session: Database session for execution validation
            max_feedback_iterations: Maximum correction attempts
        
        Returns:
            Dictionary with result containing:
            - sql: Generated SQL query
            - success: Whether SQL was successfully generated
            - iterations: Number of feedback iterations
            - schema_context: Retrieved schema context
            - error: Error message if failed
        """
        # Stage 3: Retrieve relevant schema
        retrieved_elements, distances = self.retrieve_schema_elements(question, n_results=10)
        
        if not retrieved_elements:
            return {
                "success": False,
                "error": "No relevant schema elements found for this question",
                "sql": None,
                "schema_context": None
            }
        
        # Stage 4: Build schema context
        schema_context = self.build_schema_context(retrieved_elements)
        
        # Initialize feedback loop
        feedback_loop = SQLFeedbackLoop(self.validator, max_iterations=max_feedback_iterations)
        
        sql_result = None
        feedback_prompt = None
        
        # Iterative generation with feedback
        while feedback_loop.should_continue():
            # Build prompt
            user_prompt = self.build_user_prompt(question, schema_context, feedback_prompt)
            
            # Prepare messages
            system_prompt = self.get_system_prompt(is_feedback=feedback_prompt is not None)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # Stage 5: Generate SQL
            if USE_LOCAL_LLM:
                response = await self.generate_sql_ollama(messages, stream=False)
                # Extract SQL from response
                sql_output = response.message.content if hasattr(response, "message") else ""
            else:
                response = await self.generate_sql_openai(messages, stream=False)
                # Extract SQL from response (non-streaming)
                sql_output = response.choices[0].message.content
            
            # Clean SQL output
            sql_result = self.validator.clean_sql_output(sql_output)
            
            # Stage 6: Validation
            is_valid, error = self.validator.validate_query(sql_result)
            
            if not is_valid:
                # Record failure
                feedback_loop.add_iteration(sql_result, error, success=False)
                feedback_prompt = feedback_loop.get_feedback_prompt()
                continue
            
            # If execution validation is requested
            if validate_execution and db_session:
                success, exec_error, _ = await self.validator.execute_and_validate(
                    sql_result, db_session, fetch_results=False
                )
                
                if not success:
                    # Record execution failure
                    feedback_loop.add_iteration(sql_result, exec_error, success=False)
                    feedback_prompt = feedback_loop.get_feedback_prompt()
                    continue
            
            # Success
            feedback_loop.add_iteration(sql_result, None, success=True)
            break
        
        # Get final result
        final_result = feedback_loop.get_final_result()
        final_result["schema_context"] = schema_context
        final_result["retrieved_elements"] = len(retrieved_elements)
        
        return final_result


async def LoadNL2SQLChain(
    question: str,
    schema_collection_name: str,
    culture: str = "fa",
    stream: bool = True
) -> ChatResponse:
    """
    Main entry point for NL2SQL streaming pipeline
    
    Args:
        question: Natural language question
        schema_collection_name: ChromaDB collection name for schema
        culture: Language code (fa/en)
        stream: Whether to stream response
    
    Returns:
        Streaming chat response with SQL generation
    """
    # Initialize embedding function
    if USE_LOCAL_EMBEDDING:
        embedding_fn = LocalSTEmbeddingFunction(Model_Dir, device="cpu")
    else:
        embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_API_KEY,
            model_name=utils.OPENAI_EMBEDDING_MODEL_NAME,
        )
    
    # Get ChromaDB collection
    chroma_client = chromadb.PersistentClient(utils.CHROMADB_PERSIST_DIRECTORY)
    collection: Collection = chroma_client.get_collection(
        name=schema_collection_name,
        embedding_function=embedding_fn
    )
    
    # Retrieve schema elements
    results = collection.query(
        query_texts=[question],
        n_results=10
    )
    
    # Build schema context
    schema_context = ""
    if results["documents"] and results["documents"][0]:
        schema_context = "Available Database Schema:\n\n"
        for doc, dist in zip(results["documents"][0], results["distances"][0]):
            # if dist < 0.95:
                schema_context += f"  - {doc}\n"
    
    # Build user prompt
    user_prompt = f"User Question:\n{question}\n\n{schema_context}\n"
    
    if culture == "fa":
        user_prompt += "فقط SQL تولید کنید:\n"
    else:
        user_prompt += "Generate SQL only:\n"
    
    # Get system prompt
    system_prompt = SYSTEM_PROMPT_NL2SQL_FA if culture == "fa" else SYSTEM_PROMPT_NL2SQL_EN
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # Generate SQL
    if USE_LOCAL_LLM:
        ollama_client = AsyncClient(host=OLLAMA_HOST)
        chat_completion = await ollama_client.chat(
            think=False,
            stream=stream,
            messages=messages,
            model=OLLAMA_MODEL_NAME,
            options={"temperature": OLLAMA_TEMPERATURE}
        )
        return chat_completion
    else:
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        chat_completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            stream=stream
        )
        return chat_completion


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