from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import HITLReview, HITLStatus
from app.schemas.hitl import HITLReviewResponse, HITLReviewUpdateRequest

router = APIRouter(prefix="/hitl", tags=["Human-in-the-Loop"])


@router.get(
    "/reviews",
    response_model=List[HITLReviewResponse],
    summary="List queries flagged for human review"
)
async def list_hitl_reviews(
    status_filter: Optional[HITLStatus] = Query(None, description="Filter by status (pending, approved, corrected)"),
    video_id: Optional[str] = Query(None, description="Filter by video ID"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns items flagged for human verification due to low AI confidence (< threshold)
    or ambiguous query context.
    """
    stmt = select(HITLReview).order_by(HITLReview.created_at.desc())
    if status_filter:
        stmt = stmt.where(HITLReview.status == status_filter)
    if video_id:
        stmt = stmt.where(HITLReview.video_id == video_id)
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    reviews = result.scalars().all()

    return [
        HITLReviewResponse(
            id=r.id,
            video_id=r.video_id,
            query=r.query,
            ai_answer=r.ai_answer,
            confidence_score=r.confidence_score,
            status=r.status,
            reviewer_notes=r.reviewer_notes,
            corrected_answer=r.corrected_answer,
            created_at=r.created_at,
            reviewed_at=r.reviewed_at
        )
        for r in reviews
    ]


@router.post(
    "/reviews/{review_id}",
    response_model=HITLReviewResponse,
    summary="Submit human review decision"
)
async def submit_hitl_review(
    review_id: str,
    payload: HITLReviewUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Submit human feedback, approval, or correction for a flagged query.
    Closes the loop between AI perception and human oversight.
    """
    review = await db.get(HITLReview, review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"HITL review with id '{review_id}' not found."
        )

    review.status = payload.status
    if payload.reviewer_notes is not None:
        review.reviewer_notes = payload.reviewer_notes
    if payload.corrected_answer is not None:
        review.corrected_answer = payload.corrected_answer
    review.reviewed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(review)

    return HITLReviewResponse(
        id=review.id,
        video_id=review.video_id,
        query=review.query,
        ai_answer=review.ai_answer,
        confidence_score=review.confidence_score,
        status=review.status,
        reviewer_notes=review.reviewer_notes,
        corrected_answer=review.corrected_answer,
        created_at=review.created_at,
        reviewed_at=review.reviewed_at
    )
