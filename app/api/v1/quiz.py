import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import Video, Quiz, QuizQuestion, QuizAttempt, SelfTestAttempt
from app.core.exceptions import VideoNotFoundError
from app.schemas.quiz import (
    QuizGenerateRequest,
    QuizResponse,
    QuizQuestionResponse,
    QuizSubmitRequest,
    QuizEvaluationResponse,
    SelfTestRequest,
    SelfTestResponse
)
from app.services.quiz_service import QuizService
from app.services.pdf_generator import PdfGenerator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Quiz & Learning Assessment"])
quiz_service = QuizService()


@router.post(
    "/videos/{video_id}/quiz/generate",
    response_model=QuizResponse,
    summary="Generate a grounded assessment quiz for a knowledge video"
)
async def generate_quiz_for_video(
    video_id: str,
    payload: QuizGenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a quiz with questions strictly grounded in the video's actual content.
    Returns 400 if the video is observational/surveillance.
    """
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    quiz = await quiz_service.generate_quiz(
        db=db,
        video=video,
        num_questions=payload.num_questions,
        difficulty=payload.difficulty,
        question_type=payload.question_type
    )

    return QuizResponse(
        id=quiz.id,
        video_id=quiz.video_id,
        title=quiz.title,
        difficulty=quiz.difficulty,
        question_type=quiz.question_type,
        total_questions=quiz.total_questions,
        created_at=quiz.created_at,
        questions=[
            QuizQuestionResponse(
                id=q.id,
                quiz_id=q.quiz_id,
                order_num=q.order_num,
                question=q.question,
                question_type=q.question_type,
                options=q.options,
                topic=q.topic,
                relevant_timestamp_formatted=q.relevant_timestamp_formatted,
                relevant_timestamp_start=q.relevant_timestamp_start,
                relevant_timestamp_end=q.relevant_timestamp_end
            )
            for q in quiz.questions
        ]
    )


@router.get(
    "/videos/{video_id}/quizzes",
    response_model=List[QuizResponse],
    summary="List all generated quizzes for a video"
)
async def list_quizzes_for_video(
    video_id: str,
    db: AsyncSession = Depends(get_db)
):
    """List all quizzes created for a specific video."""
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    stmt = select(Quiz).where(Quiz.video_id == video_id).order_by(Quiz.created_at.desc())
    quizzes = (await db.execute(stmt)).scalars().all()

    results = []
    for q in quizzes:
        results.append(
            QuizResponse(
                id=q.id,
                video_id=q.video_id,
                title=q.title,
                difficulty=q.difficulty,
                question_type=q.question_type,
                total_questions=q.total_questions,
                created_at=q.created_at,
                questions=[
                    QuizQuestionResponse(
                        id=qq.id,
                        quiz_id=qq.quiz_id,
                        order_num=qq.order_num,
                        question=qq.question,
                        question_type=qq.question_type,
                        options=qq.options,
                        topic=qq.topic,
                        relevant_timestamp_formatted=qq.relevant_timestamp_formatted,
                        relevant_timestamp_start=qq.relevant_timestamp_start,
                        relevant_timestamp_end=qq.relevant_timestamp_end
                    )
                    for qq in q.questions
                ]
            )
        )
    return results


@router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizResponse,
    summary="Retrieve quiz definition for taking the quiz"
)
async def get_quiz(
    quiz_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve quiz questions and choices."""
    quiz = await db.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    return QuizResponse(
        id=quiz.id,
        video_id=quiz.video_id,
        title=quiz.title,
        difficulty=quiz.difficulty,
        question_type=quiz.question_type,
        total_questions=quiz.total_questions,
        created_at=quiz.created_at,
        questions=[
            QuizQuestionResponse(
                id=q.id,
                quiz_id=q.quiz_id,
                order_num=q.order_num,
                question=q.question,
                question_type=q.question_type,
                options=q.options,
                topic=q.topic,
                relevant_timestamp_formatted=q.relevant_timestamp_formatted,
                relevant_timestamp_start=q.relevant_timestamp_start,
                relevant_timestamp_end=q.relevant_timestamp_end
            )
            for q in quiz.questions
        ]
    )


@router.post(
    "/quizzes/{quiz_id}/submit",
    response_model=QuizEvaluationResponse,
    summary="Submit quiz answers for evaluation and diagnostic learning breakdown"
)
async def submit_quiz(
    quiz_id: str,
    payload: QuizSubmitRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Evaluates candidate answers, returns diagnostic scores, strong/weak areas,
    and smart relearn timestamps.
    """
    quiz = await db.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    return await quiz_service.evaluate_quiz(
        db=db,
        quiz=quiz,
        answers=payload.answers
    )


@router.get(
    "/quizzes/{quiz_id}/attempts/{attempt_id}",
    response_model=QuizEvaluationResponse,
    summary="Retrieve evaluation report for a past quiz attempt"
)
async def get_quiz_attempt(
    quiz_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Fetch stored evaluation report."""
    attempt = await db.get(QuizAttempt, attempt_id)
    if not attempt or attempt.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")

    eval_data = attempt.evaluation_data or {}
    return QuizEvaluationResponse(
        attempt_id=attempt.id,
        quiz_id=attempt.quiz_id,
        video_id=attempt.video_id,
        total_score=attempt.total_score,
        max_score=attempt.max_score,
        percentage=attempt.percentage,
        correct_count=attempt.correct_count,
        incorrect_count=attempt.incorrect_count,
        unanswered_count=attempt.unanswered_count,
        strong_areas=eval_data.get("strong_areas", []),
        needs_improvement=eval_data.get("needs_improvement", []),
        topic_performance=eval_data.get("topic_performance", []),
        questions=eval_data.get("evaluated_items", []),
        created_at=attempt.created_at
    )


@router.post(
    "/videos/{video_id}/self-test",
    response_model=SelfTestResponse,
    summary="Test My Understanding: user submits question and written explanation for evaluation"
)
async def test_my_understanding(
    video_id: str,
    payload: SelfTestRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Evaluates user's written answer against the video's actual content.
    Returns rubric score (0-10), qualitative status, and recommended video section.
    """
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    return await quiz_service.evaluate_self_test(
        db=db,
        video=video,
        user_question=payload.user_question,
        user_answer=payload.user_answer
    )


@router.get(
    "/quizzes/{quiz_id}/pdf/questions",
    summary="Download Question Paper as PDF (without answers)"
)
async def download_question_paper_pdf(
    quiz_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Download clean question paper PDF."""
    stmt = select(Quiz).where(Quiz.id == quiz_id)
    quiz = (await db.execute(stmt)).scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    video = await db.get(Video, quiz.video_id)
    pdf_buffer = PdfGenerator.generate_question_paper(quiz, video)

    safe_title = "".join(c for c in (quiz.title or "quiz") if c.isalnum() or c in (' ', '_', '-')).strip()
    filename = f"{safe_title}_Question_Paper.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get(
    "/quizzes/{quiz_id}/attempts/{attempt_id}/pdf/report",
    summary="Download Quiz & Evaluation Report as PDF"
)
async def download_evaluation_report_pdf(
    quiz_id: str,
    attempt_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Download full evaluation report PDF with score, topic breakdown, and timestamps."""
    stmt = select(Quiz).where(Quiz.id == quiz_id)
    quiz = (await db.execute(stmt)).scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    attempt = await db.get(QuizAttempt, attempt_id)
    if not attempt or attempt.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")

    video = await db.get(Video, quiz.video_id)
    pdf_buffer = PdfGenerator.generate_evaluation_report(attempt, quiz, video)

    safe_title = "".join(c for c in (quiz.title or "quiz") if c.isalnum() or c in (' ', '_', '-')).strip()
    filename = f"{safe_title}_Evaluation_Report.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
