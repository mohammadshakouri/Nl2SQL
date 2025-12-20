from typing import Literal, Optional
from pydantic import BaseModel


class ChatMessageRequest(BaseModel):
    threadId: str
    message: str
    is_authenticated: bool
    culture: str
    provinceName: str
    siteCode:int

class SimilarQuestionsRequest(BaseModel):
    message: str
    is_authenticated: bool
    culture: str
    siteCode:int

class FeedbackRequest(BaseModel):
    run_id: str
    feedback: Literal["none", "like", "dislike"]


class HistoryRequest(BaseModel):
    run_id: Optional[str] = None
    feedback: Optional[int] = None
    from_time: Optional[str] = None
    to_time: Optional[str] = None
