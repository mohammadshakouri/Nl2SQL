
import chromadb
from app.models import Message
from app.schema_manager import SchemaManager
import app.dotenv as env
from chromadb.utils import embedding_functions
from tqdm import tqdm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

OLLAMA_EMBEDDING_MODEL_NAME: str = "google/embeddinggemma-300m"
OPENAI_EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
CHROMADB_PERSIST_DIRECTORY: str = "./chroma_db"


async def get_thread_messages(db: AsyncSession, thread_id: str):
    """Get all messages from a thread for SQL generation history"""
    stmt = (
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.start_time.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    input_messages = [msg.input for msg in messages if msg.input and msg.input.strip()]
    conversation: list[dict] = []
    for msg in messages:
        conversation.append({
            "role": "user",
            "content": msg.input.strip() if msg.input else ""
        })
        if msg.output:
            conversation.append({
                "role": "assistant",
                "content": msg.output.strip()
            })
    return input_messages, conversation


def get_schema_collection_name(schema_name: str) -> str:
    return f"Schema_{schema_name}"


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
    
    device: str = "cpu"
    batch_size = 10
    
    print(f"Creating schema vector store for: {schema_name}")
    
    if USE_LOCAL_EMBEDDING:
        print("Embedding using local model...")
        print("Embedding model:", OLLAMA_EMBEDDING_MODEL_NAME)
        sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            device=device,
            model_name=OLLAMA_EMBEDDING_MODEL_NAME,
        )
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
    collection_name = get_schema_collection_name(schema_name)
    
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


def validate_nl2sql_setup(schema_name: str) -> dict:
    """
    Validate that NL2SQL system is properly set up for a schema
    
    Args:
        schema_name: Name of the schema to validate
    
    Returns:
        Dictionary with validation results
    """
    import os
    
    results = {
        "schema_name": schema_name,
        "schema_json_exists": False,
        "collection_exists": False,
        "errors": []
    }
    
    # Check schema JSON file
    schema_path = f"./data_schema/{schema_name}_schema.json"
    if os.path.exists(schema_path):
        results["schema_json_exists"] = True
    else:
        results["errors"].append(f"Schema JSON not found: {schema_path}")
    
    # Check ChromaDB collection
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMADB_PERSIST_DIRECTORY)
        collection_name = get_schema_collection_name(schema_name)
        collection = chroma_client.get_collection(name=collection_name)
        results["collection_exists"] = True
        results["collection_count"] = collection.count()
    except Exception as e:
        results["errors"].append(f"Collection not found or error: {str(e)}")
    
    results["is_valid"] = results["schema_json_exists"] and results["collection_exists"]
    
    return results

