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


class UserRole(str, enum.Enum):
    ORG_ADMIN = "org_admin"
    MANAGER = "manager"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False, default="active")
    plan = Column(String(50), nullable=False, default="Enterprise")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    workspaces = relationship("Workspace", back_populates="organization", cascade="all, delete-orphan")
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="workspaces")
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.ANALYST)
    status = Column(String(50), nullable=False, default="active")
    onboarding_completed = Column(Integer, nullable=False, default=0) # 0=pending, 1=completed
    use_case = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="users")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(30), nullable=False, default="#38bdf8")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="projects")
    workspace = relationship("Workspace", back_populates="projects")
    videos = relationship("Video", back_populates="project")


class ProcessingCostRecord(Base):
    __tablename__ = "processing_cost_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=True)
    model = Column(String(100), nullable=False, default="gemini-1.5-flash")
    processing_stage = Column(String(100), nullable=False)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    cached_tokens = Column(BigInteger, nullable=False, default=0)
    ai_calls_count = Column(Integer, nullable=False, default=1)
    estimated_cost = Column(Float, nullable=False, default=0.0)
    actual_cost = Column(Float, nullable=False, default=0.0)
    cost_breakdown_json = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    user_email = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False, index=True)  # e.g., "video.upload", "user.role_change"
    resource_type = Column(String(100), nullable=False)  # e.g., "video", "user", "project"
    resource_id = Column(String(100), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True, default="127.0.0.1")
    status = Column(String(20), nullable=False, default="success")  # "success", "failed"
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    metric_name = Column(String(100), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    tags = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


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
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
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
    
    # Cost & Stage Timings
    estimated_cost = Column(Float, nullable=False, default=0.0)
    actual_cost = Column(Float, nullable=False, default=0.0)
    stage_timings_json = Column(JSON, nullable=True)  # {"Upload": 12, "ASR": 42, "Vision": 130}
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="videos")
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

