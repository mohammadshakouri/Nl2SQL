"""
Embedding + vector-store utilities for the Schema-RAG NL2SQL research project.

This module builds a Chroma collection of schema retrieval units (tables,
columns, foreign-key relations) from a schema JSON file, using either a
local SentenceTransformer model or the OpenAI embedding API.
"""

import chromadb
import app.dotenv as env
from app.schema_manager import SchemaManager
from chromadb.utils import embedding_functions
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from chromadb.api.types import EmbeddingFunction

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

OLLAMA_EMBEDDING_MODEL_NAME: str = "google/embeddinggemma-300m"
OPENAI_EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
CHROMADB_PERSIST_DIRECTORY: str = "./chroma_db"
EMBEDDING_MODEL_DIR = env.embedding_model_dir


def create_schema_vector_store(
    schema_json_path: str,
    schema_name: str,
    chroma_path: str = CHROMADB_PERSIST_DIRECTORY
) -> dict:
    """
    Create vector store for database schema elements

    Args:
        schema_json_path: Path to schema JSON file
        schema_name: Name identifier for the schema
        chroma_path: Path to ChromaDB persistence directory

    Returns:
        Dictionary with statistics about the created schema
    """

    batch_size = 10

    print(f"Creating schema vector store for: {schema_name}")

    if USE_LOCAL_EMBEDDING:
        print("Embedding using local model...")
        print("Embedding model:", OLLAMA_EMBEDDING_MODEL_NAME)
        sentence_transformer_ef = LocalSTEmbeddingFunction(EMBEDDING_MODEL_DIR, device="cpu")
    else:
        print("Embedding using OpenAI model...")
        print("Embedding model:", OPENAI_EMBEDDING_MODEL_NAME)
        sentence_transformer_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_API_KEY,
            model_name=OPENAI_EMBEDDING_MODEL_NAME,
        )

    # Load schema
    manager = SchemaManager()
    manager.load_schema_from_json(schema_json_path)

    # Get embedding texts
    ids, documents = manager.get_all_embedding_texts()

    # Create collection
    chroma_client = chromadb.PersistentClient(path=chroma_path)
    collection_name = f"Schema_{schema_name}"

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=sentence_transformer_ef,
    )

    # Add documents in batches
    for i in tqdm(range(0, len(ids), batch_size), desc=f"Embedding {collection_name}"):
        chunk_ids = ids[i:i+batch_size]
        chunk_docs = documents[i:i+batch_size]

        collection.upsert(
            ids=chunk_ids,
            documents=chunk_docs,
        )

    stats = manager.get_schema_summary()
    stats["collection_name"] = collection_name

    print(f"Schema vector store created: {stats}")

    return stats


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
            show_progress_bar=True,
        ).tolist()
