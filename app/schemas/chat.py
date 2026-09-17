from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class Citation(BaseModel):
    start_time: float
    end_time: float
    timestamp_formatted: str  # e.g. "02:15 - 02:30"
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    video_id: Optional[str] = None
    video_filename: Optional[str] = None
    modality: Optional[str] = "Multimodal"  # "Transcript", "Visual", "OCR", "Event", "Multimodal"


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="Question or prompt about the video or videos")
    session_id: Optional[str] = Field(None, description="Optional existing session ID for multi-turn chat")
    scope: Optional[str] = Field("all", description="Query scope: 'all' for cross-video library search, or 'single' for focused video")
    video_id: Optional[str] = Field(None, description="Optional target video ID when scope is single")


class ChatResponse(BaseModel):
    session_id: str
    video_id: Optional[str] = None
    query: str
    answer: str
    citations: List[Citation] = []
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_level: Optional[str] = "High"  # "High", "Medium", "Low"
    requires_hitl: bool = False
    hitl_review_id: Optional[str] = None
    scope: str = "all"
    videos_analyzed: List[str] = []


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
