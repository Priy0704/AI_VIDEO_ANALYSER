from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any


class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(5, ge=1, le=25, description="Number of questions to generate (e.g. 5, 10, 15)")
    difficulty: str = Field("medium", description="Quiz difficulty: easy, medium, hard")
    question_type: str = Field("mixed", description="Question types: mcq, true_false, short_answer, or mixed")


class QuizQuestionResponse(BaseModel):
    id: str
    quiz_id: str
    order_num: int
    question: str
    question_type: str  # mcq, true_false, short_answer
    options: Optional[List[str]] = None
    topic: str = "General"
    relevant_timestamp_formatted: str = "00:00–00:10"
    relevant_timestamp_start: float = 0.0
    relevant_timestamp_end: float = 0.0
    # Omitted or empty when taking quiz, visible in evaluation / review
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None


class QuizResponse(BaseModel):
    id: str
    video_id: str
    title: str
    difficulty: str
    question_type: str
    total_questions: int
    created_at: datetime
    questions: List[QuizQuestionResponse] = []


class QuizSubmitRequest(BaseModel):
    answers: Dict[str, str] = Field(..., description="Mapping of question_id to user's answer string")


class QuestionEvaluationItem(BaseModel):
    question_id: str
    order_num: int
    question: str
    question_type: str
    options: Optional[List[str]] = None
    user_answer: str
    correct_answer: str
    is_correct: bool
    is_unanswered: bool
    score: float
    topic: str
    explanation: str
    relevant_timestamp_formatted: str
    relevant_timestamp_start: float
    relevant_timestamp_end: float


class TopicPerformance(BaseModel):
    topic: str
    correct_count: int
    total_count: int
    percentage: float
    status: str  # "Strong Area" or "Needs Improvement"


class QuizEvaluationResponse(BaseModel):
    attempt_id: str
    quiz_id: str
    video_id: str
    total_score: float
    max_score: float
    percentage: float
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    strong_areas: List[str] = []
    needs_improvement: List[str] = []
    topic_performance: List[TopicPerformance] = []
    questions: List[QuestionEvaluationItem] = []
    created_at: datetime


class SelfTestRequest(BaseModel):
    user_question: str = Field(..., min_length=3, description="User's test question or topic, e.g. 'What is RAG?'")
    user_answer: str = Field(..., min_length=2, description="User's written answer to test")


class SelfTestResponse(BaseModel):
    id: str
    video_id: str
    user_question: str
    user_answer: str
    score: float
    max_score: float = 10.0
    status: str  # "Mastered", "Partially Correct", "Needs Improvement"
    feedback: str
    correct_concept: str
    topic: str
    relevant_timestamp_formatted: str
    relevant_timestamp_start: float
    relevant_timestamp_end: float
    created_at: datetime
