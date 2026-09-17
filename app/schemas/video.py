from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.db.models import VideoStatus


class VideoUrlRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=2048, description="YouTube or web video URL")


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
    video_type: Optional[str] = "knowledge"
    video_type_label: Optional[str] = "Learning / Knowledge Content"
    video_type_confidence: Optional[float] = 0.90
    video_type_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class VideoSegmentResponse(BaseModel):
    id: str
    start_time: float
    end_time: float
    transcript_text: Optional[str] = ""
    visual_description: Optional[str] = ""
    combined_text: str


class TranscriptUtterance(BaseModel):
    start: float
    end: float
    text: str


class VideoDetailResponse(BaseModel):
    id: str
    filename: str
    duration_seconds: Optional[float]
    status: VideoStatus
    progress_pct: int
    summary: Optional[str] = None
    video_type: Optional[str] = "knowledge"
    video_type_label: Optional[str] = "Learning / Knowledge Content"
    video_type_confidence: Optional[float] = 0.90
    video_type_reason: Optional[str] = None
    raw_transcripts: Optional[List[TranscriptUtterance]] = []
    created_at: datetime
    segments_count: int = 0
    segments: List[VideoSegmentResponse] = []

