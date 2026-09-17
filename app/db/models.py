import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    BigInteger,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Enum as SQLEnum
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class VideoStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class HITLStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class Video(Base):
    __tablename__ = "videos"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)
    file_path = Column(String(1024), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False, default=0)
    duration_seconds = Column(Float, nullable=True, default=0.0)
    status = Column(SQLEnum(VideoStatus), nullable=False, default=VideoStatus.QUEUED)
    progress_pct = Column(Integer, nullable=False, default=0)
    current_stage = Column(String(100), nullable=True, default="Queued")
    error_message = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    raw_transcripts = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    segments = relationship("VideoSegment", back_populates="video", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="video", cascade="all, delete-orphan")
    hitl_reviews = relationship("HITLReview", back_populates="video", cascade="all, delete-orphan")


class VideoSegment(Base):
    __tablename__ = "video_segments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time = Column(Float, nullable=False, index=True)
    end_time = Column(Float, nullable=False, index=True)
    transcript_text = Column(Text, nullable=True, default="")
    visual_description = Column(Text, nullable=True, default="")
    ocr_text = Column(Text, nullable=True, default="")
    combined_text = Column(Text, nullable=False)
    
    # 768-dimensional normalized embedding stored as JSON array
    embedding = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    video = relationship("Video", back_populates="segments")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    video = relationship("Video", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)  # List of cited timestamps & snippets
    confidence_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")


class HITLReview(Base):
    __tablename__ = "hitl_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True)
    query = Column(Text, nullable=False)
    ai_answer = Column(Text, nullable=False)
    confidence_score = Column(Float, nullable=False)
    status = Column(SQLEnum(HITLStatus), nullable=False, default=HITLStatus.PENDING, index=True)
    reviewer_notes = Column(Text, nullable=True)
    corrected_answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    # Relationships
    video = relationship("Video", back_populates="hitl_reviews")
