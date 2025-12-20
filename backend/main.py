import os
import json
import logging
import time
import uuid
import jdatetime
import app.dotenv as env
import app.utilities as utils
import chromadb
from chromadb.utils import embedding_functions

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from app.dt_chain import LoadChain
from app.models import Base, Message
from app.schemas import ChatMessageRequest, FeedbackRequest, HistoryRequest, SimilarQuestionsRequest


USE_LOCAL_LLM = env.use_local_llm
DOCUMENTATION = env.documentation
SIMAC_API_KEY = env.simac_api_key
SQL_DATABASE_URL = env.sql_database_url


logger = logging.getLogger('uvicorn.info')
engine = create_async_engine(SQL_DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def initialize(app: FastAPI):

    collection_name_path: list[tuple] = [
        ("PostLoginFa", "./data_fa/afterlogin.txt"),
        ("PreLoginFa", "./data_fa/beforelogin.txt"),
        ("PreLoginEn", "./data_en/beforelogin.txt"),
        ("PostLoginEn", "./data_en/afterlogin.txt"),
        ("Yaraneh", "./data_fa/yaraneh.txt"),
        ("Documents", "./data_fa/documents.txt"),
    ]
    if not os.path.exists(utils.CHROMADB_PERSIST_DIRECTORY):
        utils.create_vector_store(collection_name_path)

    async with engine.begin() as conn:
        start = time.time()
        await conn.run_sync(Base.metadata.create_all)
        end = time.time()
        logger.info(f'Database loaded in {end - start:.3f}s')

    yield

app = FastAPI(
    title='SIMAC AI Assistant',
    version='1.0.0',
    lifespan=initialize,
    docs_url='/docs' if DOCUMENTATION else None,
    redoc_url='/redoc' if DOCUMENTATION else None,
)

app.add_middleware(CORSMiddleware,
                   allow_origins=['*'],
                   allow_credentials=True,
                   allow_methods=['*'],
                   allow_headers=['*'],
                   expose_headers=['*'],
                   )


async def check_api_key(api_key: str = Header(...)):
    if api_key != SIMAC_API_KEY:
        raise HTTPException(status_code=401, detail='Invalid API Key')


async def generate_Ollama_chat_events(threadId:str, message: str, is_authenticated: bool, culture:str, provinceName:str, siteCode:int):
    async with AsyncSessionLocal() as db:
        start_time = jdatetime.datetime.now()
        db_message = Message(
            input=message,
            start_time=start_time.isoformat(),
            is_user_authenticated=str(is_authenticated),
            provinceName="هدفمندی یارانه " if siteCode == 99 else provinceName,
            culture=culture,
            feedback=0
        )

        run_id = str(uuid.uuid4())

        if threadId.strip() == "":
            threadId = str(uuid.uuid4())

        db_message.thread_id = threadId

        data = {
            "event": "on_start",
            "run_id": run_id,
            "thread_id": threadId,
        }
        yield f"data: {json.dumps(data)}\n\n"

        if (len(message) > 250):
            data = {
            "event": "on_error",
            "data": "طول پیام بیش از حد مجاز است. حداکثر طول پیام 250 کاراکتر می‌باشد.",
            }
            yield f"data: {json.dumps(data)}\n\n"
            return
        
        thread_questions, _ = await utils.get_thread_messages(db, threadId)
        if (len(thread_questions) > 5):
            data = {
            "event": "on_error",
            "data": "تعداد سوالات در این گفتگو بیش از حد مجاز است. لطفا یک گفتگو جدید آغاز کنید.",
            }
            yield f"data: {json.dumps(data)}\n\n"
            return

        chatResponse = await LoadChain(db, threadId, message, is_authenticated, culture, siteCode)
        full_answer = ""
        async for chunk in chatResponse:
            if hasattr(chunk, "message") and chunk.message and chunk.message.content:
                token = chunk.message.content
                full_answer += token
                chunk_html = token.replace("\n", "<br>")

                data = {
                    "event": "on_stream",
                    "data": chunk_html,
                }
                yield f"data: {json.dumps(data)}\n\n"
                        
            if getattr(chunk, "done", False):
                end_time = jdatetime.datetime.now()
                db_message.latency = (end_time - start_time).total_seconds()
                db_message.output = full_answer
                db_message.status = "success"
                db_message.run_id = run_id

                data = {
                    "event": "on_end",
                }
                yield f"data: {json.dumps(data)}\n\n"

                db.add(db_message)
                try:
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail=f"Error adding record: {e}"
                    )
                break
            else:
                pass


async def generate_OpenAI_chat_events(threadId:str, message: str, is_authenticated: bool, culture:str, provinceName:str, siteCode:int):
    async with AsyncSessionLocal() as db:
        start_time = jdatetime.datetime.now()
        db_message = Message(
            input=message,
            start_time=start_time.isoformat(),
            is_user_authenticated=str(is_authenticated),
            provinceName="هدفمندی یارانه" if siteCode == 99 else provinceName,
            culture=culture,
            feedback=0
        )
        
        run_id = str(uuid.uuid4())

        if threadId.strip() == "":
            threadId = str(uuid.uuid4())

        db_message.thread_id = threadId

        data = {
            "event": "on_start",
            "run_id": run_id,
            "thread_id": threadId,
        }
        yield f"data: {json.dumps(data)}\n\n"

        if (len(message) > 250):
            data = {
            "event": "on_error",
            "data": "طول پیام بیش از حد مجاز است. حداکثر طول پیام 250 کاراکتر می‌باشد.",
            }
            yield f"data: {json.dumps(data)}\n\n"
            return
        
        thread_questions, _ = await utils.get_thread_messages(db, threadId)
        if (len(thread_questions) > 10):
            data = {
            "event": "on_error",
            "data": "تعداد سوالات در این گفتگو بیش از حد مجاز است. لطفا یک گفتگو جدید آغاز کنید.",
            }
            yield f"data: {json.dumps(data)}\n\n"
            return
        

        chatResponse = await LoadChain(db, threadId, message, is_authenticated, culture, siteCode)
        full_answer = ""
        async for chunk in chatResponse:
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                token = delta.content
                full_answer += token
                chunk_html = token.replace("\n", "<br>")

                data = {
                    "event": "on_stream",
                    "data": chunk_html,
                }
                yield f"data: {json.dumps(data)}\n\n"

            # پایان پاسخ
            if choice.finish_reason is not None:
                end_time = jdatetime.datetime.now()
                db_message.latency = (end_time - start_time).total_seconds()
                db_message.output = full_answer
                db_message.status = "success"
                db_message.run_id = run_id

                data = {
                    "event": "on_end",
                }
                yield f"data: {json.dumps(data)}\n\n"

                db.add(db_message)
                try:
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail=f"Error adding record: {e}"
                    )
                break
            else:
                pass


@app.post('/chat', dependencies=[Depends(check_api_key)])
async def message_stream(request: ChatMessageRequest):
    if(USE_LOCAL_LLM):
        return StreamingResponse(generate_Ollama_chat_events(request.threadId, request.message, request.is_authenticated, request.culture, request.provinceName, request.siteCode), media_type='text/event-stream')
    else:
        return StreamingResponse(generate_OpenAI_chat_events(request.threadId, request.message, request.is_authenticated, request.culture, request.provinceName, request.siteCode), media_type='text/event-stream')


@app.post('/feedback', dependencies=[Depends(check_api_key)])
async def message_feedback(request: FeedbackRequest):
    run_id = request.run_id
    feedback = request.feedback

    async with AsyncSessionLocal() as db:
        query = select(Message).where(Message.run_id == run_id)
        result = await db.execute(query)
        db_message = result.scalars().first()

        if db_message:
            db_message.feedback = 1 if feedback == 'like' else -1 if feedback == 'dislike' else 0
            await db.commit()
            return True

        return False

@app.post("/search", dependencies=[Depends(check_api_key)])
async def search(request: SimilarQuestionsRequest):
    if not request.message or request.message.strip() == "":
        return {"results": []}
    if (len(request.message) > 250):
        return {"results": []}

    if utils.USE_LOCAL_EMBEDDING:
        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=utils.OLLAMA_EMBEDDING_MODEL_NAME,
        )
    else:
        embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=utils.OPENAI_API_KEY,
            model_name=utils.OPENAI_EMBEDDING_MODEL_NAME,
        )
    
    chroma_client = chromadb.PersistentClient(path=utils.CHROMADB_PERSIST_DIRECTORY)
    collection_name = utils.get_colloection_name(request.is_authenticated, request.culture, request.siteCode)
    collection = chroma_client.get_collection(
        name=collection_name,
        embedding_function=embedding_fn
    )

    # Get embeddings and perform similarity search
    results = collection.query(
        query_texts=[request.message],
        n_results=4
    )

    res:list[dict] = []

    json_path = utils.get_collection_answer_json_file_path(request.is_authenticated, request.culture, request.siteCode)
    # Return the top 5 most similar questions

    if results and results["documents"]:
        distances = results["distances"][0]
        normalized_distances = utils.normalize_distances_to_range(distances)
        for doc, norm_dist  in zip(results["documents"][0], normalized_distances):
            with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        if item["question"].strip() == doc.strip():
                            res.append({
                                    "question":item['question'].replace("\n", "<br>"),
                                    "answer": item['answer'].replace("\n", "<br>"),
                                    "distance": norm_dist
                                })
        return {"results": res}
    return {"results": []}


@app.post('/history', dependencies=[Depends(check_api_key)])
async def message_history(request: HistoryRequest):
    run_id = request.run_id
    feedback = request.feedback
    from_time_str = request.from_time
    to_time_str = request.to_time

    async with AsyncSessionLocal() as db:  # Create an async database session
        query = select(Message)

        # Apply filters if search parameters are provided
        if run_id:
            query = query.where(Message.run_id == run_id)

        if feedback is not None:
            query = query.where(Message.feedback == feedback)

        if from_time_str:
            # Convert ISO format string to jdatetime and then back to ISO string
            from_time_jalali = jdatetime.datetime.fromisoformat(from_time_str)
            # Get ISO string representation
            from_time_iso = from_time_jalali.isoformat()
            # Filter records where start_time is between from_time and to_time
            query = query.where(Message.start_time >= from_time_iso)

        if to_time_str:
            # Convert ISO format string to jdatetime and then back to ISO string
            to_time_jalali = jdatetime.datetime.fromisoformat(to_time_str)
            # Get ISO string representation
            to_time_iso = to_time_jalali.isoformat()
            # Filter records where start_time is between from_time and to_time
            query = query.where(Message.start_time <= to_time_iso)

        result = await db.execute(query)
        records = result.scalars().all()

        # Convert to list of dictionaries for JSON response
        data = [record.__dict__ for record in records]

        # Remove SQLAlchemy internal state before returning
        for record in data:
            record.pop('_sa_instance_state', None)

        key_order = ['start_time', 'provinceName', 'input', 'output', 'culture', 'is_user_authenticated', 'feedback']
        data = [{key: entry[key] for key in key_order if key in entry} for entry in data]
        data = sorted(data, key=lambda x: x['start_time'], reverse=True)

        return JSONResponse(content=data, headers={'Content-Type': 'application/json; charset=utf-8'})


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='localhost', port=80) 
