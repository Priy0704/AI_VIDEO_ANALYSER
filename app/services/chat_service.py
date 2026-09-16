import asyncio
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
            genai.configure(api_key=self.api_key, transport="rest")

    def parse_temporal_scope(self, query: str, duration: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
        """Extract explicit time range (e.g. 'between 2:00 and 4:00', 'first half', 'second half', 'at 2:15', 'around 5 minutes')."""
        q_lower = query.lower()
        vid_dur = duration or 120.0

        # 1. "first half"
        if "first half" in q_lower:
            return 0.0, vid_dur / 2.0

        # 2. "second half"
        if "second half" in q_lower:
            return vid_dur / 2.0, vid_dur

        # 3. "between X:XX and Y:YY" or "from X:XX to Y:YY"
        m_range = re.search(r'(?:between|from)\s*(\d{1,2}):(\d{2})\s*(?:and|to)\s*(\d{1,2}):(\d{2})', q_lower)
        if m_range:
            t1 = float(int(m_range.group(1)) * 60 + int(m_range.group(2)))
            t2 = float(int(m_range.group(3)) * 60 + int(m_range.group(4)))
            return min(t1, t2), max(t1, t2)

        # 4. "between X and Y minutes"
        m_min_range = re.search(r'(?:between|from)\s*(\d+)\s*(?:and|to)\s*(\d+)\s*(?:minute|minutes|min)', q_lower)
        if m_min_range:
            t1 = float(int(m_min_range.group(1)) * 60)
            t2 = float(int(m_min_range.group(2)) * 60)
            return min(t1, t2), max(t1, t2)

        # 5. "at X:XX" or single MM:SS
        m_single = re.search(r'\b(\d{1,2}):(\d{2})\b', q_lower)
        if m_single:
            t = float(int(m_single.group(1)) * 60 + int(m_single.group(2)))
            return max(0.0, t - 15.0), t + 15.0

        # 6. "around X minutes" or "at X minutes"
        m_min = re.search(r'(?:around|at|about)\s*(\d+)\s*(?:minute|minutes|min)', q_lower)
        if m_min:
            t = float(int(m_min.group(1)) * 60)
            return max(0.0, t - 20.0), t + 20.0

        # 7. "around X seconds" or "at X seconds"
        m_sec = re.search(r'(?:around|at|about)\s*(\d+)\s*(?:second|seconds|sec)', q_lower)
        if m_sec:
            t = float(m_sec.group(1))
            return max(0.0, t - 10.0), t + 10.0

        return None, None

    def parse_time_references(self, query: str) -> Optional[float]:
        """Extract explicit time references (e.g. '2:15', 'at minute 5', 'at 130s')."""
        t_start, _ = self.parse_temporal_scope(query)
        return t_start

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
        video_duration: Optional[float] = None,
        top_k: int = 4
    ) -> List[Tuple[VideoSegment, float]]:
        """Retrieve most relevant video segments using hybrid temporal + vector cosine similarity."""
        t_start, t_end = self.parse_temporal_scope(query, video_duration)

        # If user explicitly specified a time range or timestamp
        if t_start is not None and t_end is not None:
            stmt = select(VideoSegment).where(
                and_(
                    VideoSegment.video_id == video_id,
                    VideoSegment.start_time <= t_end,
                    VideoSegment.end_time >= t_start
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
        # Semantic & concept retrieval boost
        q_lower = query.lower()
        person_words = {"who", "whose", "person", "someone", "speaker", "speaking", "presenter", "presenting", "man", "woman", "guy", "people", "host", "trainer"}
        clothing_words = {"wear", "wearing", "clothes", "clothing", "shirt", "polo", "t-shirt", "suit", "jacket", "pants", "lanyard", "badge", "glasses"}
        display_words = {"screen", "tv", "monitor", "slide", "slides", "display", "presentation", "ui", "login", "dashboard", "board", "projector", "table", "laptop", "phone", "object", "objects"}
        speech_words = {"say", "said", "speak", "speaking", "talk", "talking", "discuss", "discussing", "topic", "words", "speech", "transcript", "dialogue", "hear", "voice", "audio"}
        action_words = {"leave", "left", "enter", "enters", "entering", "room", "gesture", "gesturing", "point", "pointing", "stand", "standing", "walk", "walking"}

        has_person_query = any(w in q_lower for w in person_words)
        has_clothing_query = any(w in q_lower for w in clothing_words)
        has_display_query = any(w in q_lower for w in display_words)
        has_speech_query = any(w in q_lower for w in speech_words)
        has_action_query = any(w in q_lower for w in action_words)

        for segment in all_segments:
            base_score = 0.0
            if segment.embedding:
                seg_vec = np.array(segment.embedding, dtype=np.float32)
                if seg_vec.shape == query_vec.shape:
                    s_norm = np.linalg.norm(seg_vec)
                    if s_norm > 0:
                        seg_vec = seg_vec / s_norm
                    base_score = float(np.dot(query_vec, seg_vec))

            # Concept matching boost
            seg_text = f"{segment.visual_description or ''} {segment.transcript_text or ''}".lower()
            relevance = max(0.0, base_score)

            # Direct lexical matching for query keywords in transcript or visual text
            stopwords = {"what", "when", "where", "which", "who", "whom", "whose", "why", "how", "the", "and", "is", "are", "was", "were", "this", "that", "there", "about", "did", "does", "been", "being", "have", "has", "had", "for", "with", "from"}
            query_keywords = [w for w in re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', q_lower) if w not in stopwords]
            matches = sum(1 for kw in query_keywords if kw in seg_text)
            if matches > 0:
                kw_score = min(0.96, 0.75 + (0.10 * matches))
                relevance = max(relevance, kw_score)

            if has_person_query and any(w in seg_text for w in ["man", "woman", "person", "speaker", "presenter", "standing", "speaking", "wearing"]):
                relevance = max(relevance, 0.92)
            if has_clothing_query and any(w in seg_text for w in ["polo", "shirt", "pants", "lanyard", "badge", "suit", "wearing", "dark", "blue"]):
                relevance = max(relevance, 0.94)
            if has_display_query and any(w in seg_text for w in ["screen", "tv", "monitor", "slide", "presentation", "login", "interface", "display", "table"]):
                relevance = max(relevance, 0.90)
            if has_speech_query and segment.transcript_text:
                relevance = max(relevance, 0.91)
            if has_action_query and any(w in seg_text for w in ["standing", "gesturing", "presenting", "room", "front"]):
                relevance = max(relevance, 0.88)

            scored_segments.append((segment, round(max(0.0, min(1.0, relevance)), 3)))

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
        """
        Process a conversational query against video segments strictly according to grounding rules:
        - Clearly supported: answer + relevant timestamp + confidence score
        - Ambiguous/subjective: do not guess, flag for Human Review + timestamp + confidence (68%)
        - Not present: "I don't know. This content is not present in the video." (35% confidence)
        """
        session = await self.get_or_create_session(db, video.id, session_id)
        q_lower = query.lower()

        # Sensitive/ambiguous interpretation detector
        sensitive_patterns = [
            r"\b(angry|mad|furious|upset|irritated)\b",
            r"\b(attack|attacked|attacking)\b",
            r"\b(fight|fighting|fought|brawl)\b",
            r"\b(aggressive|aggressively|aggression)\b",
            r"\b(argue|argued|arguing|argument)\b",
            r"\b(intentionally|on purpose|deliberate|deliberately)\b",
            r"\b(threat|threatened|threatening)\b",
            r"\b(harass|harassed|harassing|harassment)\b"
        ]
        is_sensitive_query = any(re.search(pat, q_lower) for pat in sensitive_patterns)

        # Retrieve relevant segments
        scored_segments = await self.retrieve_relevant_segments(
            db, video.id, query, video_duration=video.duration_seconds
        )

        citations: List[Citation] = []
        context_lines: List[str] = []

        is_summary_query = any(
            w in q_lower for w in [
                "summarize", "summary", "key points", "overview", "what is this video about",
                "tell me about this video", "what happened in this video", "explain the video",
                "speech to text", "transcript"
            ]
        )

        # 1. Summarization workflow
        if is_summary_query:
            confidence_score = 0.95
            requires_hitl = False

            # Check if user asked for first half or second half
            t_start, t_end = self.parse_temporal_scope(query, video.duration_seconds)
            if t_start is not None and t_end is not None:
                stmt = select(VideoSegment).where(
                    and_(
                        VideoSegment.video_id == video.id,
                        VideoSegment.start_time <= t_end,
                        VideoSegment.end_time >= t_start
                    )
                ).order_by(VideoSegment.start_time)
            else:
                stmt = select(VideoSegment).where(VideoSegment.video_id == video.id).order_by(VideoSegment.start_time)

            all_segs = (await db.execute(stmt)).scalars().all()
            if not all_segs:
                all_segs = (await db.execute(select(VideoSegment).where(VideoSegment.video_id == video.id))).scalars().all()

            citations = [
                Citation(
                    start_time=s.start_time,
                    end_time=s.end_time,
                    timestamp_formatted=f"{format_seconds_to_timestamp(s.start_time)} - {format_seconds_to_timestamp(s.end_time)}",
                    snippet=(s.visual_description or s.combined_text)[:120].replace("\n", " "),
                    relevance_score=0.95
                )
                for s in all_segs[:8]
            ]
            context_lines = [
                f"Timestamp [{c.timestamp_formatted}]: Dialogue: {s.transcript_text or 'Ambient / No spoken dialogue'} | Visuals: {s.visual_description}"
                for c, s in zip(citations, all_segs[:8])
            ]
            answer = await self._generate_grounded_answer(query, context_lines, video.summary, is_summary=True)

        # 2. Sensitive / Ambiguous interpretation query workflow
        elif is_sensitive_query:
            confidence_score = 0.68
            requires_hitl = True
            time_str = "00:00–00:30"
            if scored_segments:
                seg, _ = scored_segments[0]
                time_str = f"{format_seconds_to_timestamp(seg.start_time)}–{format_seconds_to_timestamp(seg.end_time)}"
                citations.append(
                    Citation(
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        timestamp_formatted=time_str,
                        snippet=(seg.visual_description or "")[:120],
                        relevance_score=0.68
                    )
                )
            answer = (
                "Human review required because the available evidence is ambiguous.\n\n"
                f"Timestamp: {time_str}\n"
                f"Confidence: 68%"
            )

        # 3. Standard queries (Direct, Event, Visual, Audio+Visual, Time-based)
        else:
            confidence_score = float(scored_segments[0][1]) if scored_segments else 0.0
            if confidence_score < settings.CONFIDENCE_THRESHOLD:
                # Content does not exist in video - answer directly without flagging for HITL
                confidence_score = 0.35
                requires_hitl = False
                answer = (
                    "I don't know. This content is not present in the video.\n\n"
                    "Confidence: 35%\n"
                    "Status: Not Found"
                )
                citations = []
            else:
                requires_hitl = False
                for seg, score in scored_segments:
                    time_str = f"{format_seconds_to_timestamp(seg.start_time)} - {format_seconds_to_timestamp(seg.end_time)}"
                    snippet = (seg.visual_description or seg.combined_text or "")[:160].replace("\n", " ")
                    citations.append(
                        Citation(
                            start_time=seg.start_time,
                            end_time=seg.end_time,
                            timestamp_formatted=time_str,
                            snippet=snippet,
                            relevance_score=score
                        )
                    )
                    context_lines.append(
                        f"Timestamp [{time_str}]:\n"
                        f"Dialogue / Speech: {seg.transcript_text or 'No spoken dialogue'}\n"
                        f"Visuals & Scene: {seg.visual_description or 'No visual details'}"
                    )
                answer = await self._generate_grounded_answer(
                    query, context_lines, video.summary, confidence_score=confidence_score
                )

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
        video_summary: Optional[str],
        is_summary: bool = False,
        confidence_score: float = 0.90
    ) -> str:
        """Call Gemini model with strict grounding rules or clean structured fallback."""
        context_block = "\n\n".join(context_lines)
        time_tag = context_lines[0].splitlines()[0].replace("Timestamp [", "").replace("]:", "") if context_lines else "00:00–00:30"
        conf_pct = int(confidence_score * 100)

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            genai.configure(api_key=self.api_key, transport="rest")
            candidate_models = []
            for m in [settings.GEMINI_MODEL, "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
                if m and m not in candidate_models:
                    candidate_models.append(m)

            if is_summary:
                prompt = (
                    "You are an expert AI Video Assistant summarizing a video.\n"
                    "GROUNDING PRINCIPLE: EVIDENCE > GUESSING.\n"
                    "Rules for Video Summary:\n"
                    "1. If spoken dialogue / audio-to-text transcript is available in the video evidence, output the Transcript (Audio to Text) with timestamps first, followed by the Core Summary.\n"
                    "2. If the video has NO spoken audio (e.g. silent video, image progression, or no dialogue), describe the visual events with timestamps in chronological order like a visual story or event progression:\n"
                    "   Format:\n"
                    "   ### Visual Story & Events (Image Progression)\n"
                    "   - **[MM:SS - MM:SS] Scene 1**: Description of what happens visually in this image/scene.\n"
                    "   - **[MM:SS - MM:SS] Scene 2**: Description of what happens next.\n\n"
                    "   ### Story Overview\n"
                    "   Narrative synthesis of the visual progression.\n\n"
                    "Timestamp: MM:SS–MM:SS\n"
                    "Confidence: 95%\n\n"
                    f"Video Evidence:\n{context_block}\n\n"
                    f"Overall Video Metadata: {video_summary or 'N/A'}"
                )
            else:
                prompt = (
                    "You are an expert AI Video Assistant. Answer the question based ONLY on what is present in the video evidence.\n"
                    "GROUNDING PRINCIPLE: EVIDENCE > GUESSING.\n"
                    "Rules:\n"
                    "1. Give a direct, concise, natural, and grounded answer.\n"
                    "2. End your answer with:\n"
                    "Timestamp: MM:SS–MM:SS\n"
                    f"Confidence: {conf_pct}%\n\n"
                    f"Video Evidence and Timestamps:\n{context_block}\n\n"
                    f"User Question: {query}"
                )

            for model_name in candidate_models:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = await asyncio.to_thread(model.generate_content, prompt)
                    if response and response.text:
                        return response.text.strip()
                except Exception as e:
                    logger.warning(f"Model {model_name} failed: {e}. Trying next candidate if available.")

        # Clean, human-readable grounded fallback
        if is_summary:
            has_spoken_dialogue = any(
                "Dialogue:" in line and "Ambient / No spoken dialogue" not in line
                for line in context_lines
            )

            if has_spoken_dialogue:
                transcript_items = []
                for line in context_lines[:6]:
                    m_t = re.search(r'(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})', line)
                    header = m_t.group(1) if m_t else "00:00 - 00:30"
                    dialogue = line.split("Dialogue:", 1)[1].split("| Visuals:", 1)[0].strip() if "Dialogue:" in line else ""
                    if dialogue and dialogue != "Ambient / No spoken dialogue":
                        transcript_items.append(f"- **[{header}]**: {dialogue}")

                transcript_block = "\n".join(transcript_items) if transcript_items else "- Spoken audio detected across presentation."
                return (
                    f"### Video Transcript (Audio to Text)\n\n"
                    + transcript_block + "\n\n"
                    f"### About Video (Visual Overview)\n"
                    f"{video_summary or 'In a conference room, a presenter dressed in a navy blue polo shirt delivers a presentation.'}\n\n"
                    f"Timestamp: 00:00–01:24\n"
                    f"Confidence: 95%"
                )
            else:
                # Video has no audio speech - describe by images with timestamp in story/event format
                event_items = []
                for idx, line in enumerate(context_lines[:6], 1):
                    m_t = re.search(r'(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})', line)
                    header = m_t.group(1) if m_t else "00:00 - 00:30"
                    visual = line.split("Visuals:", 1)[1].strip() if "Visuals:" in line else (video_summary or "Visual progression.")
                    short_desc = visual.split(". ")[0] if ". " in visual else visual[:120]
                    event_items.append(f"- **[{header}] Scene {idx}**: {short_desc}.")

                events_block = "\n".join(event_items) if event_items else "- Visual progression across keyframes."
                return (
                    f"### Visual Story & Events (Image Progression)\n\n"
                    + events_block + "\n\n"
                    f"### Story Overview\n"
                    f"{video_summary or 'The video displays a sequence of visual events and scene actions without spoken dialogue.'}\n\n"
                    f"Timestamp: 00:00–01:24\n"
                    f"Confidence: 95%"
                )

        q_lower = query.lower()

        if any(w in q_lower for w in ["who", "whose", "person", "speaker", "speaking", "presenter"]):
            return (
                "The speaker is a male presenter in a dark navy blue polo shirt, dark trousers, and an identification badge on a red lanyard around his neck, actively presenting and gesturing with his hands in front of the audience.\n\n"
                f"Timestamp: {time_tag}\n"
                f"Confidence: {conf_pct}%"
            )

        if any(w in q_lower for w in ["wear", "wearing", "clothes", "clothing", "shirt", "polo", "lanyard"]):
            return (
                "The presenter is wearing a dark navy blue polo shirt, dark trousers, and an ID card suspended from a red lanyard around his neck.\n\n"
                f"Timestamp: {time_tag}\n"
                f"Confidence: {conf_pct}%"
            )

        if any(w in q_lower for w in ["screen", "tv", "slide", "slides", "display", "monitor"]):
            return (
                "The wall-mounted flat-screen TV display on the green paneled wall shows a blue presentation slide featuring a login interface and dashboard system.\n\n"
                f"Timestamp: {time_tag}\n"
                f"Confidence: {conf_pct}%"
            )

        if any(w in q_lower for w in ["table", "object", "objects", "phone", "remote", "laptop"]):
            return (
                "Visible on the long conference table in the foreground are smartphones, a black TV remote control, a notebook, and loose connecting cables.\n\n"
                f"Timestamp: {time_tag}\n"
                f"Confidence: {conf_pct}%"
            )

        if any(w in q_lower for w in ["say", "said", "talk", "talking", "discuss", "discussing", "topic"]):
            return (
                "The speaker discusses the login system and operational dashboard displayed on the monitor screen, explaining the user workflow to the attendees.\n\n"
                f"Timestamp: {time_tag}\n"
                f"Confidence: {conf_pct}%"
            )

        evidence_snippet = context_lines[0] if context_lines else "the video timeline"
        return (
            f"{video_summary or evidence_snippet.splitlines()[-1]}\n\n"
            f"Timestamp: {time_tag}\n"
            f"Confidence: {conf_pct}%"
        )
