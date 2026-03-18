import os
import json
import logging
import time
import jdatetime
import app.dotenv as env
import app.utilities as utils
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from app.nl2sql_chain import LoadNL2SQLChain
from app.models import Base, Message
from app.schemas import HistoryRequest, NL2SQLRequest, FeedbackSubmissionRequest


USE_LOCAL_LLM = env.use_local_llm
DOCUMENTATION = env.documentation
SIMAC_API_KEY = env.simac_api_key
MAIN_DATABASE_URL = env.main_database_url


logger = logging.getLogger('uvicorn.info')
engine = create_async_engine(MAIN_DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def initialize(app: FastAPI):
    if not os.path.exists(utils.CHROMADB_PERSIST_DIRECTORY):
        utils.initialize_schema_vector_stores()
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


async def check_api_key(api_key: str = Header(...)):
    if api_key != SIMAC_API_KEY:
        raise HTTPException(status_code=401, detail='Invalid API Key')

@app.post('/nl2sql', dependencies=[Depends(check_api_key)])
async def nl2sql_stream(request: NL2SQLRequest):
    """
    NL2SQL endpoint - Schema-RAG pipeline
    
    Unified pipeline handler.  Forwards the request to
    ``LoadNL2SQLChain`` which performs retrieval, validation, feedback loop and
    streaming of SQL tokens.  The caller receives a Server-Sent Events stream
    identical to the behaviour of the previous implementation.
    """
    collection_name = f"Schema_{request.schema_name}"
    return StreamingResponse(
        LoadNL2SQLChain(
            request.threadId,
            request.question,
            collection_name,
            request.culture,
            # validate_execution=request.validate_execution,
        ),
        media_type='text/event-stream'
    )


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


@app.post('/feedback', dependencies=[Depends(check_api_key)])
async def submit_feedback(request: FeedbackSubmissionRequest):
    """
    Submit feedback for a generated SQL query
    
    Allows users to mark queries as correct (feedback=1) or incorrect (feedback=-1).
    For incorrect queries, users can provide a corrected SQL and optional comment.
    
    Args:
        request: FeedbackSubmissionRequest with run_id, feedback, corrected_sql, comment
    
    Returns:
        JSON response with success status and message
    """
    async with AsyncSessionLocal() as db:
        try:
            # Find the message by run_id
            query = select(Message).where(Message.run_id == request.run_id)
            result = await db.execute(query)
            message = result.scalar_one_or_none()
            
            if not message:
                raise HTTPException(status_code=404, detail=f"Message with run_id {request.run_id} not found")
            
            # Update feedback
            message.feedback = request.feedback
            
            # If negative feedback and corrected SQL provided, store it
            if request.feedback == -1 and request.corrected_sql:
                message.corrected_sql = request.corrected_sql
                message.status = 'corrected'
            elif request.feedback == 1:
                message.status = 'success'
            
            # Store optional comment
            if request.comment:
                message.feedback_comment = request.comment
            
            # Commit changes
            await db.commit()
            
            return JSONResponse(
                content={
                    "success": True,
                    "message": "Feedback submitted successfully",
                    "run_id": request.run_id,
                    "feedback": request.feedback
                },
                headers={'Content-Type': 'application/json; charset=utf-8'}
            )
            
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Error submitting feedback: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='localhost', port=80)



