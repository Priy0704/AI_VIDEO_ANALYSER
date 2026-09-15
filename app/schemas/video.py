from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.db.models import VideoStatus


class VideoUploadResponse(BaseModel):
    video_id: str
    filename: str
    status: VideoStatus
    message: str = "Video uploaded successfully. Processing started asynchronously."


class VideoStatusResponse(BaseModel):
    video_id: str
    filename: str
    status: VideoStatus
    progress_pct: int = Field(ge=0, le=100)
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class VideoSegmentResponse(BaseModel):
    id: str
    start_time: float
    end_time: float
    transcript_text: Optional[str] = ""
    visual_description: Optional[str] = ""
    combined_text: str


class VideoDetailResponse(BaseModel):
    id: str
    filename: str
    duration_seconds: Optional[float]
    status: VideoStatus
    progress_pct: int
    summary: Optional[str] = None
    created_at: datetime
    segments_count: int = 0
    segments: List[VideoSegmentResponse] = []
