import os
import json
import logging
import time
import uuid
import jdatetime
import app.dotenv as env
import app.utilities as utils
import initialize_nl2sql
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from app.nl2sql_chain import LoadNL2SQLChain
from app.models import Base, Message
from app.schemas import HistoryRequest, NL2SQLRequest


USE_LOCAL_LLM = env.use_local_llm
DOCUMENTATION = env.documentation
SIMAC_API_KEY = env.simac_api_key
SQL_DATABASE_URL = env.sql_database_url


logger = logging.getLogger('uvicorn.info')
engine = create_async_engine(SQL_DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def initialize(app: FastAPI):
    # Create database tables
    async with engine.begin() as conn:
        start = time.time()
        await conn.run_sync(Base.metadata.create_all)
        end = time.time()
        logger.info(f'Database loaded in {end - start:.3f}s')

    yield

app = FastAPI(
    title='NL2SQL API - Schema-RAG',
    version='2.0.0',
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

initialize_nl2sql.main()

async def check_api_key(api_key: str = Header(...)):
    if api_key != SIMAC_API_KEY:
        raise HTTPException(status_code=401, detail='Invalid API Key')


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


# ============================================================================
# NL2SQL Endpoints - Schema-RAG
# ============================================================================

async def generate_nl2sql_ollama_stream(threadId: str, question: str, schema_name: str, culture: str):
    """Generate SQL using Ollama with streaming"""
    async with AsyncSessionLocal() as db:
        start_time = jdatetime.datetime.now()
        
        run_id = str(uuid.uuid4())
        if threadId.strip() == "":
            threadId = str(uuid.uuid4())
        
        # Send start event
        data = {
            "event": "on_start",
            "run_id": run_id,
            "thread_id": threadId,
            "type": "nl2sql"
        }
        yield f"data: {json.dumps(data)}\n\n"
        
        # Validate question length
        if len(question) > 250:
            data = {
                "event": "on_error",
                "data": "Question is too long. Maximum 250 characters allowed."
            }
            yield f"data: {json.dumps(data)}\n\n"
            return
        
        try:
            # Get schema collection name
            collection_name = utils.get_schema_collection_name(schema_name)
            
            # Generate SQL stream
            chatResponse = await LoadNL2SQLChain(
                question=question,
                schema_collection_name=collection_name,
                culture=culture,
                stream=True
            )
            
            full_sql = ""
            async for chunk in chatResponse:
                if hasattr(chunk, "message") and chunk.message and chunk.message.content:
                    token = chunk.message.content
                    full_sql += token
                    
                    # Stream SQL token by token
                    data = {
                        "event": "on_stream",
                        "data": token,
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                
                if getattr(chunk, "done", False):
                    end_time = jdatetime.datetime.now()
                    
                    data = {
                        "event": "on_end",
                        "sql": full_sql,
                        "latency": (end_time - start_time).total_seconds()
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    break
                    
        except Exception as e:
            data = {
                "event": "on_error",
                "data": f"Error generating SQL: {str(e)}"
            }
            yield f"data: {json.dumps(data)}\n\n"


async def generate_nl2sql_openai_stream(threadId: str, question: str, schema_name: str, culture: str):
    """Generate SQL using OpenAI with streaming"""
    async with AsyncSessionLocal() as db:
        start_time = jdatetime.datetime.now()
        
        run_id = str(uuid.uuid4())
        if threadId.strip() == "":
            threadId = str(uuid.uuid4())
        
        # Send start event
        data = {
            "event": "on_start",
            "run_id": run_id,
            "thread_id": threadId,
            "type": "nl2sql"
        }
        yield f"data: {json.dumps(data)}\n\n"
        
        # Validate question length
        if len(question) > 250:
            data = {
                "event": "on_error",
                "data": "Question is too long. Maximum 250 characters allowed."
            }
            yield f"data: {json.dumps(data)}\n\n"
            return
        
        try:
            # Get schema collection name
            collection_name = utils.get_schema_collection_name(schema_name)
            
            # Generate SQL stream
            chatResponse = await LoadNL2SQLChain(
                question=question,
                schema_collection_name=collection_name,
                culture=culture,
                stream=True
            )
            
            full_sql = ""
            async for chunk in chatResponse:
                choice = chunk.choices[0]
                delta = choice.delta
                
                if delta and delta.content:
                    token = delta.content
                    full_sql += token
                    
                    # Stream SQL token by token
                    data = {
                        "event": "on_stream",
                        "data": token,
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                
                if choice.finish_reason is not None:
                    end_time = jdatetime.datetime.now()
                    
                    data = {
                        "event": "on_end",
                        "sql": full_sql,
                        "latency": (end_time - start_time).total_seconds()
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    break
                    
        except Exception as e:
            data = {
                "event": "on_error",
                "data": f"Error generating SQL: {str(e)}"
            }
            yield f"data: {json.dumps(data)}\n\n"


@app.post('/nl2sql', dependencies=[Depends(check_api_key)])
async def nl2sql_stream(request: NL2SQLRequest):
    """
    NL2SQL endpoint - Schema-RAG pipeline
    
    Converts natural language questions to SQL queries using schema retrieval.
    Returns streaming response with generated SQL.
    """
    if USE_LOCAL_LLM:
        return StreamingResponse(
            generate_nl2sql_ollama_stream(
                request.threadId,
                request.question,
                request.schema_name,
                request.culture
            ),
            media_type='text/event-stream'
        )
    else:
        return StreamingResponse(
            generate_nl2sql_openai_stream(
                request.threadId,
                request.question,
                request.schema_name,
                request.culture
            ),
            media_type='text/event-stream'
        )


@app.post('/nl2sql/validate', dependencies=[Depends(check_api_key)])
async def validate_schema_setup(schema_name: str):
    """
    Validate that NL2SQL is properly configured for a schema
    
    Returns validation results including whether schema JSON and 
    ChromaDB collection exist.
    """
    results = utils.validate_nl2sql_setup(schema_name)
    return JSONResponse(content=results)


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='localhost', port=80) 
