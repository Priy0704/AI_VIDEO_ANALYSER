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
    video_type = Column(String(50), nullable=True, default="knowledge")  # "knowledge" or "observational"
    video_type_label = Column(String(100), nullable=True, default="Learning / Knowledge Content")
    video_type_confidence = Column(Float, nullable=True, default=0.90)
    video_type_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    segments = relationship("VideoSegment", back_populates="video", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="video", cascade="all, delete-orphan")
    hitl_reviews = relationship("HITLReview", back_populates="video", cascade="all, delete-orphan")
    quizzes = relationship("Quiz", back_populates="video", cascade="all, delete-orphan")
    self_test_attempts = relationship("SelfTestAttempt", back_populates="video", cascade="all, delete-orphan")


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


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True, default="Video Knowledge Quiz")
    difficulty = Column(String(20), nullable=False, default="medium")  # easy, medium, hard
    question_type = Column(String(20), nullable=False, default="mixed")  # mcq, true_false, short_answer, mixed
    total_questions = Column(Integer, nullable=False, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    video = relationship("Video", back_populates="quizzes")
    questions = relationship("QuizQuestion", back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.order_num", lazy="selectin")
    attempts = relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan", lazy="selectin")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    quiz_id = Column(String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True)
    order_num = Column(Integer, nullable=False, default=1)
    question = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False, default="mcq")  # mcq, true_false, short_answer
    options = Column(JSON, nullable=True)  # List of strings for MCQ / True-False
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text, nullable=True)
    topic = Column(String(100), nullable=False, default="General")
    relevant_timestamp_start = Column(Float, nullable=False, default=0.0)
    relevant_timestamp_end = Column(Float, nullable=False, default=0.0)
    relevant_timestamp_formatted = Column(String(50), nullable=False, default="00:00–00:10")

    # Relationships
    quiz = relationship("Quiz", back_populates="questions")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    quiz_id = Column(String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True)
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    total_score = Column(Float, nullable=False, default=0.0)
    max_score = Column(Float, nullable=False, default=0.0)
    percentage = Column(Float, nullable=False, default=0.0)
    correct_count = Column(Integer, nullable=False, default=0)
    incorrect_count = Column(Integer, nullable=False, default=0)
    unanswered_count = Column(Integer, nullable=False, default=0)
    answers = Column(JSON, nullable=False)  # {question_id: user_answer}
    evaluation_data = Column(JSON, nullable=False)  # detailed results per question, strong/weak areas
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    quiz = relationship("Quiz", back_populates="attempts")
    video = relationship("Video")


class SelfTestAttempt(Base):
    __tablename__ = "self_test_attempts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    user_question = Column(Text, nullable=False)
    user_answer = Column(Text, nullable=False)
    score = Column(Float, nullable=False, default=0.0)  # 0 to 10
    max_score = Column(Float, nullable=False, default=10.0)
    status = Column(String(50), nullable=False, default="Needs Improvement")  # Mastered, Partially Correct, Needs Improvement
    feedback = Column(Text, nullable=False)
    correct_concept = Column(Text, nullable=False)
    topic = Column(String(100), nullable=False, default="General")
    relevant_timestamp_start = Column(Float, nullable=False, default=0.0)
    relevant_timestamp_end = Column(Float, nullable=False, default=0.0)
    relevant_timestamp_formatted = Column(String(50), nullable=False, default="00:00–00:10")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    video = relationship("Video", back_populates="self_test_attempts")

