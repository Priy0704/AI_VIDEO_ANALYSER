from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from app.db.models import HITLStatus


class HITLReviewResponse(BaseModel):
    id: str
    video_id: str
    query: str
    ai_answer: str
    confidence_score: float
    status: HITLStatus
    reviewer_notes: Optional[str] = None
    corrected_answer: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class HITLReviewUpdateRequest(BaseModel):
    status: HITLStatus = Field(description="approved, corrected, or rejected")
    reviewer_notes: Optional[str] = Field(None, max_length=2000)
    corrected_answer: Optional[str] = Field(None, max_length=4000)
