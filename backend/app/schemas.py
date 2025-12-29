from typing import Optional
from pydantic import BaseModel


class NL2SQLRequest(BaseModel):
    """Request model for NL2SQL endpoint"""
    threadId: str
    question: str
    schema_name: str  # e.g., 'ecommerce', 'hr', 'inventory'
    culture: str  # 'fa' or 'en'
    validate_execution: bool = False  # Whether to validate SQL by executing it


class HistoryRequest(BaseModel):
    """Request model for history/logging endpoint"""
    run_id: Optional[str] = None
    feedback: Optional[int] = None
    from_time: Optional[str] = None
    to_time: Optional[str] = None


class FeedbackSubmissionRequest(BaseModel):
    """Request model for feedback submission"""
    run_id: str
    feedback: int  # 1 for positive, -1 for negative
    corrected_sql: Optional[str] = None  # Corrected SQL if feedback is negative
    comment: Optional[str] = None  # Optional feedback comment

