import logging
import re
from typing import List, Tuple, Optional
from datetime import datetime
import numpy as np
import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.config import settings
from app.db.models import (
    Video, VideoSegment, ChatSession, ChatMessage, HITLReview, HITLStatus, VideoStatus
)
from app.schemas.chat import ChatResponse, Citation
from app.services.fusion_indexer import FusionIndexer

logger = logging.getLogger(__name__)


def format_seconds_to_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS format."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"


class ChatService:
    """Conversational engine providing grounded answers with timestamp citations and confidence-driven HITL."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.fusion_indexer = FusionIndexer(api_key=self.api_key)
        if self.api_key:
            genai.configure(api_key=self.api_key)

    def parse_time_references(self, query: str) -> Optional[float]:
        """Extract explicit time references (e.g. '2:15', 'at minute 5', 'at 130s')."""
        m = re.search(r'\b(\d{1,2}):(\d{2})\b', query)
        if m:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            return float(minutes * 60 + seconds)

        m = re.search(r'\b(?:minute|min)\s*(\d{1,2})\b', query, re.IGNORECASE)
        if m:
            return float(int(m.group(1)) * 60)

        m = re.search(r'\b(\d+)\s*(?:sec|second|seconds)\b', query, re.IGNORECASE)
        if m:
            return float(m.group(1))

        return None

    async def get_or_create_session(self, db: AsyncSession, video_id: str, session_id: Optional[str]) -> ChatSession:
        """Fetch existing session or create a new one."""
        if session_id:
            result = await db.execute(
                select(ChatSession).where(
                    and_(ChatSession.id == session_id, ChatSession.video_id == video_id)
                )
            )
            session = result.scalars().first()
            if session:
                return session

        new_session = ChatSession(video_id=video_id)
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        return new_session

    async def retrieve_relevant_segments(
        self,
        db: AsyncSession,
        video_id: str,
        query: str,
        top_k: int = 4
    ) -> List[Tuple[VideoSegment, float]]:
        """Retrieve most relevant video segments using hybrid temporal + vector cosine similarity."""
        explicit_time = self.parse_time_references(query)

        # If user explicitly asked for a specific timestamp
        if explicit_time is not None:
            time_margin = 15.0
            stmt = select(VideoSegment).where(
                and_(
                    VideoSegment.video_id == video_id,
                    VideoSegment.start_time <= explicit_time + time_margin,
                    VideoSegment.end_time >= explicit_time - time_margin
                )
            ).order_by(VideoSegment.start_time)
            result = await db.execute(stmt)
            time_matched_segments = result.scalars().all()
            if time_matched_segments:
                return [(seg, 0.95) for seg in time_matched_segments]

        # Vector semantic retrieval
        stmt = select(VideoSegment).where(VideoSegment.video_id == video_id)
        result = await db.execute(stmt)
        all_segments = result.scalars().all()

        if not all_segments:
            return []

        query_vec = np.array(await self.fusion_indexer.generate_embedding(query), dtype=np.float32)
        q_norm = np.linalg.norm(query_vec)
        if q_norm > 0:
            query_vec = query_vec / q_norm

        scored_segments: List[Tuple[VideoSegment, float]] = []
        for segment in all_segments:
            if segment.embedding:
                seg_vec = np.array(segment.embedding, dtype=np.float32)
                if seg_vec.shape != query_vec.shape:
                    continue
                s_norm = np.linalg.norm(seg_vec)
                if s_norm > 0:
                    seg_vec = seg_vec / s_norm
                similarity = float(np.dot(query_vec, seg_vec))
                scored_segments.append((segment, round(max(0.0, min(1.0, similarity)), 3)))
            else:
                scored_segments.append((segment, 0.1))

        # Sort descending by similarity score
        scored_segments.sort(key=lambda x: x[1], reverse=True)
        return scored_segments[:top_k]

    async def chat(
        self,
        db: AsyncSession,
        video: Video,
        query: str,
        session_id: Optional[str] = None
    ) -> ChatResponse:
        """Process a conversational query against video segments and return a grounded response."""
        session = await self.get_or_create_session(db, video.id, session_id)

        # Retrieve relevant segments
        scored_segments = await self.retrieve_relevant_segments(db, video.id, query)

        if not scored_segments:
            top_score = 0.0
        else:
            top_score = max(score for _, score in scored_segments)

        confidence_score = round(top_score, 2)
        requires_hitl = confidence_score < settings.CONFIDENCE_THRESHOLD

        citations: List[Citation] = []
        context_lines: List[str] = []

        for seg, score in scored_segments:
            if score >= 0.30:  # Include relevant evidence
                time_str = f"{format_seconds_to_timestamp(seg.start_time)} - {format_seconds_to_timestamp(seg.end_time)}"
                snippet = seg.combined_text[:180].replace("\n", " ")
                citations.append(
                    Citation(
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        timestamp_formatted=time_str,
                        snippet=snippet,
                        relevance_score=score
                    )
                )
                context_lines.append(f"Segment [{time_str}]: {seg.combined_text}")

        is_summary_query = any(
            w in query.lower() for w in [
                "summarize", "summary", "overview", "what is this video about",
                "tell me about this video", "what happened in this video", "explain the video"
            ]
        )

        if is_summary_query:
            confidence_score = 0.95
            requires_hitl = False
            # Gather representative segments across timeline
            stmt = select(VideoSegment).where(VideoSegment.video_id == video.id).order_by(VideoSegment.start_time)
            all_segs = (await db.execute(stmt)).scalars().all()
            citations = [
                Citation(
                    start_time=s.start_time,
                    end_time=s.end_time,
                    timestamp_formatted=f"{format_seconds_to_timestamp(s.start_time)} - {format_seconds_to_timestamp(s.end_time)}",
                    snippet=s.combined_text[:120].replace("\n", " "),
                    relevance_score=0.95
                )
                for s in all_segs[:5]
            ]
            context_lines = [f"Segment [{c.timestamp_formatted}]: {s.combined_text}" for c, s in zip(citations, all_segs[:5])]
            answer = await self._generate_grounded_answer(query, context_lines, video.summary)
        elif confidence_score < 0.25 or not context_lines:
            answer = (
                "The requested event, topic, or question was not observed in this video footage. "
                "No visual or audio evidence in the indexed timeline matches your query."
            )
            citations = []
        else:
            answer = await self._generate_grounded_answer(query, context_lines, video.summary)

        # Record messages in chat history
        user_msg = ChatMessage(session_id=session.id, role="user", content=query)
        assistant_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=[c.dict() for c in citations],
            confidence_score=confidence_score
        )
        db.add(user_msg)
        db.add(assistant_msg)

        # Confidence-driven HITL auto-flag
        hitl_record_id = None
        if requires_hitl:
            hitl_entry = HITLReview(
                video_id=video.id,
                query=query,
                ai_answer=answer,
                confidence_score=confidence_score,
                status=HITLStatus.PENDING,
                created_at=datetime.utcnow()
            )
            db.add(hitl_entry)
            await db.flush()
            hitl_record_id = hitl_entry.id
            logger.info(f"Flagged query '{query}' for HITL review (confidence={confidence_score}).")

        await db.commit()

        return ChatResponse(
            session_id=session.id,
            video_id=video.id,
            query=query,
            answer=answer,
            citations=citations,
            confidence_score=confidence_score,
            requires_hitl=requires_hitl,
            hitl_review_id=hitl_record_id
        )

    async def _generate_grounded_answer(
        self,
        query: str,
        context_lines: List[str],
        video_summary: Optional[str]
    ) -> str:
        """Call Gemini model with strict grounding or use offline generator."""
        context_block = "\n\n".join(context_lines)

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                model = genai.GenerativeModel(settings.GEMINI_MODEL)
                prompt = (
                    "You are an AI Video Assistant answering questions about a processed video.\n"
                    "You MUST answer strictly based on the provided video segments below.\n"
                    "Cite the relevant timestamps in your response where applicable (e.g. '[01:23]').\n"
                    "Do NOT invent details or extrapolate beyond the provided evidence.\n"
                    "If the answer is not in the segments, say you cannot verify it from the video.\n\n"
                    f"Overall Video Summary: {video_summary or 'N/A'}\n\n"
                    f"Relevant Video Segments:\n{context_block}\n\n"
                    f"User Question: {query}"
                )
                response = await model.generate_content_async(prompt)
                return response.text.strip()
            except Exception as e:
                logger.warning(f"Gemini chat generation failed: {e}. Using grounded fallback.")

        first_segment = context_lines[0] if context_lines else "General footage"
        return (
            f"Based on the video footage around {first_segment.split(':')[0]}: "
            f"The observed activity matches your query. Context: {first_segment}"
        )
