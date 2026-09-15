from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class Citation(BaseModel):
    start_time: float
    end_time: float
    timestamp_formatted: str  # e.g. "02:15 - 02:30"
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="Question or prompt about the video")
    session_id: Optional[str] = Field(None, description="Optional existing session ID for multi-turn chat")


class ChatResponse(BaseModel):
    session_id: str
    video_id: str
    query: str
    answer: str
    citations: List[Citation] = []
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_hitl: bool = False
    hitl_review_id: Optional[str] = None


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    citations: Optional[List[dict]] = None
    confidence_score: Optional[float] = None
    created_at: datetime


class ChatSessionHistoryResponse(BaseModel):
    session_id: str
    video_id: str
    messages: List[ChatMessageResponse] = []
