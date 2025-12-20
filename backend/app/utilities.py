import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import chromadb
from app.models import Message
import app.dotenv as env
from chromadb.utils import embedding_functions
from tqdm import tqdm
from app.system_prompt import SYSTEM_PROMPT_AFTER_LOGIN_EN, SYSTEM_PROMPT_BEFORE_LOGIN_EN, SYSTEM_PROMPT_BEFORE_LOGIN_FA, SYSTEM_PROMPT_AFTER_LOGIN_FA, SYSTEM_PROMPT_Yaraneh
# import torch

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

OLLAMA_EMBEDDING_MODEL_NAME: str = (
    "google/embeddinggemma-300m"
    # "Qwen/Qwen3-Embedding-0.6B"
)
OPENAI_EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
CHROMADB_PERSIST_DIRECTORY: str = "./chroma_db"


async def get_thread_messages(db: AsyncSession, thread_id: str):
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
        # Append user message
        conversation.append({
            "role": "user",
            "content": msg.input.strip() if msg.input else ""
        })
        # Append assistant response (if any)
        if msg.output:
            conversation.append({
                "role": "assistant",
                "content": msg.output.strip()
            })
    return input_messages, conversation

def read_and_split_file(file_path, seperator="|"):

    ids: list[str] = []
    documents: list[str] = []
    with open(file=file_path, mode="rt", encoding="utf-8") as file:
        data = file.read()
        data_list: list[str] = data.split(sep=seperator)
        index: int = 0

        for item in data_list:
            index += 1
            id: str = f"id{index}"
            ids.append(id)
            documents.append(item)

        filtered_ids = []
        filtered_docs = []
        for i, doc in enumerate(documents):
            if doc and doc.strip():
                filtered_ids.append(ids[i])
                filtered_docs.append(doc)

        if not filtered_docs:
            raise ValueError("No valid documents to add to the collection.")
    return filtered_ids, filtered_docs

def get_colloection_name(is_authenticated:bool, culture:str, siteCode:int):
    
    if siteCode == 99:
        return "Yaraneh"

    if is_authenticated:      
            return "PostLoginFa" if culture.lower() == "fa" else "PostLoginEn"
    else:      
            return "PreLoginFa" if culture.lower() == "fa" else "PreLoginEn" 


def get_collection_answer_json_file_path(is_authenticated: bool, culture:str, siteCode:int):  
    
    if siteCode == 99:
        return ("./data_fa/yaraneh.json")

    if culture.lower() == "fa":
        return ("./data_fa/afterlogin.json" if is_authenticated else "./data_fa/beforelogin.json")
    else:
        return ("./data_en/afterlogin.json" if is_authenticated else "./data_en/beforelogin.json")
        

def create_vector_store(collection_path_list: list[tuple], chroma_path:str = CHROMADB_PERSIST_DIRECTORY):
    # device: str = "cuda" if torch.cuda.is_available() else "cpu"
    device: str = "cpu"
    batch_size = 6
    
    print("device: ",device)
    
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

    chroma_client = chromadb.PersistentClient(path=chroma_path)

    for collection_name, doc_path in collection_path_list:

        ids, documents = read_and_split_file(file_path=doc_path, seperator="|")

        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=sentence_transformer_ef,
        )

        for i in tqdm(range(0, len(ids), batch_size), desc=f"Embedding {collection_name}"):
            chunk_ids = ids[i:i+batch_size]
            chunk_docs = documents[i:i+batch_size]

            collection.upsert(
                ids=chunk_ids,
                documents=chunk_docs,
            )


def get_system_prompt(is_authenticated: bool, culture: str, siteCode:int) -> str:
        
        if siteCode == 99:
            return SYSTEM_PROMPT_Yaraneh

        if is_authenticated:
            return SYSTEM_PROMPT_AFTER_LOGIN_FA if culture.lower().strip() == "fa" else SYSTEM_PROMPT_AFTER_LOGIN_EN
        else:
            return SYSTEM_PROMPT_BEFORE_LOGIN_FA if culture.lower().strip() == "fa" else SYSTEM_PROMPT_BEFORE_LOGIN_EN
        

def build_weighted_query_embedding(messages, embedding_function, base: float = 7.0, max_messages: int = 4):
    # Slice the last `max_messages`
    recent_messages = messages[-max_messages:]
    n = len(recent_messages)

    # Compute embeddings
    embeddings = np.array(embedding_function(recent_messages))  # shape: (n, d)

    weights = np.array([base ** i for i in range(n)])
    # Normalize weights
    weights = weights / weights.sum()

    # Weighted average embedding
    weighted_embedding = np.average(embeddings, axis=0, weights=weights)

    return weighted_embedding

def normalize_distances_to_range(values, new_min=20, new_max=80):
    old_min = min(values)
    old_max = max(values)

    # اگر همه مقادیر یکسان بودند
    if old_min == old_max:
        return [new_min for _ in values]

    normalized = []
    for v in values:
        # نرمالایز به 0 تا 1
        norm01 = (v - old_min) / (old_max - old_min)
        # تبدیل به بازه جدید
        scaled = new_min + norm01 * (new_max - new_min)
        normalized.append(scaled)
    return normalized

