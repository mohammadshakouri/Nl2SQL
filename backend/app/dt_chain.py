import os
import json
import app.utilities as utils
from sqlalchemy.ext.asyncio import AsyncSession
import chromadb
import app.dotenv as env
from openai import AsyncOpenAI
from ollama import AsyncClient
from ollama import ChatResponse
from chromadb import Collection
from chromadb.utils import embedding_functions
# import torch

OPENAI_API_KEY = env.openai_api_key
USE_LOCAL_LLM = env.use_local_llm
USE_LOCAL_EMBEDDING = env.use_local_embedding

DATA_FILE_PATH: str = "./data/information.txt"

OLLAMA_TEMPERATURE: float = 0.2
OLLAMA_MODEL_NAME: str = "gemma3:4b".strip().lower()
OLLAMA_HOST: str = "http://127.0.0.1:11434".strip().lower()


async def LoadChain(
    db: AsyncSession,
    threadId:str,
    message: str,
    is_authenticated: bool,
    culture: str,
    siteCode:int
) -> ChatResponse | AsyncOpenAI:

    sys_prompt = utils.get_system_prompt(is_authenticated, culture, siteCode)

    SYSTEM_MESSAGE: dict = {
        "role": "system",
        "content": sys_prompt,
    }

    USER_PROMPT_TEMPLATE: str = """\
    Prompt:
    [PROMPT]

    Context:
    [CONTEXT]
    """
    # device: str = "cuda" if torch.cuda.is_available() else "cpu"
    device: str = "cpu"
    if USE_LOCAL_EMBEDDING:
        sentence_transformer_ef = (
            embedding_functions.SentenceTransformerEmbeddingFunction(
                device=device,
                model_name=utils.OLLAMA_EMBEDDING_MODEL_NAME,
            )
        )
    else:
        sentence_transformer_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_API_KEY,
            model_name=utils.OPENAI_EMBEDDING_MODEL_NAME,
        )

    chroma_client = chromadb.PersistentClient(utils.CHROMADB_PERSIST_DIRECTORY)

    COLLECTION_NAME = utils.get_colloection_name(is_authenticated, culture, siteCode)
    
    collection: Collection = chroma_client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=sentence_transformer_ef,
    )

    question: str = message.strip()
    thread_questions, _ = await utils.get_thread_messages(db, threadId)
    thread_questions.append(question)
    
    weighted_query = utils.build_weighted_query_embedding(thread_questions, sentence_transformer_ef, base=8, max_messages=3)

    results = collection.query(
        n_results=3,
        query_embeddings=[weighted_query],
        # query_texts=thread_messages,
    )

    context: str = ""

    json_path = utils.get_collection_answer_json_file_path(is_authenticated, culture, siteCode)

    if results["documents"]:
        for doc, distance in zip(results["documents"][0], results["distances"][0]):
            if distance < 0.8: #or doc == results["documents"][0][0]:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        if item["question"].strip() == doc.strip():
                            doc = f"سوال: {item['question']}\n پاسخ: {item['answer']}"
                    context += f"- {doc}\n"

    
    #region add docs to after login context

    if is_authenticated and siteCode != 99:
        collection_chunks: Collection = chroma_client.get_collection(
            name="Documents",
            embedding_function=sentence_transformer_ef,
        ) 
        result_docs = collection_chunks.query(
            n_results=1,
            query_embeddings=[weighted_query],
            # query_texts=thread_messages,
        )
    
        if result_docs["documents"]:
            for doc, distance in zip(result_docs["documents"][0], result_docs["distances"][0]):
                if distance < 0.5:
                    doc_clean = doc.replace("\u200c", " ").replace("\n", " ").strip()
                    context += f"- {doc_clean}\n"
    #endregion

    user_prompt: str = USER_PROMPT_TEMPLATE.replace("[PROMPT]", question).replace(
        "[CONTEXT]", context
    )

    _ , history_messages = await utils.get_thread_messages(db, threadId)

    messages = []
    messages.append(SYSTEM_MESSAGE)
    messages.extend(history_messages[-4:])

    user_message: dict = {"role": "user", "content": user_prompt}
    messages.append(user_message)

    if USE_LOCAL_LLM:
        ollama_client = AsyncClient(
            host=OLLAMA_HOST,
        )
        chat_completion: ChatResponse = await ollama_client.chat(
            think=False,
            stream=True,
            messages=messages,
            model=OLLAMA_MODEL_NAME,
            options={"temperature": OLLAMA_TEMPERATURE},
        )
        return chat_completion
    else:
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        chat_completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5,
            stream=True,
        )
        return chat_completion
