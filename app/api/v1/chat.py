from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import Video, VideoStatus, ChatSession, ChatMessage
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatMessageResponse,
    ChatSessionHistoryResponse
)
from app.core.exceptions import VideoNotFoundError, VideoNotReadyError
from app.services.chat_service import ChatService

router = APIRouter(prefix="/videos", tags=["Chat"])
chat_service = ChatService()


@router.post(
    "/{video_id}/chat",
    response_model=ChatResponse,
    summary="Ask questions about a processed video"
)
async def chat_with_video(
    video_id: str,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a free-form question about the video.
    Retrieves grounded multimodal segments, performs anti-hallucination checks,
    returns exact timestamp citations, and logs low-confidence items for HITL review.
    """
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    if video.status != VideoStatus.COMPLETED:
        raise VideoNotReadyError(video_id, video.status)

    response = await chat_service.chat(
        db=db,
        video=video,
        query=payload.query,
        session_id=payload.session_id
    )
    return response


@router.get(
    "/{video_id}/chat/{session_id}/history",
    response_model=ChatSessionHistoryResponse,
    summary="Get multi-turn conversation history"
)
async def get_chat_history(
    video_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve full message history for a specific chat session."""
    session = await db.get(ChatSession, session_id)
    if not session or session.video_id != video_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat session '{session_id}' not found for video '{video_id}'."
        )

    stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return ChatSessionHistoryResponse(
        session_id=session_id,
        video_id=video_id,
        messages=[
            ChatMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                citations=m.citations,
                confidence_score=m.confidence_score,
                created_at=m.created_at
            )
            for m in messages
        ]
    )
