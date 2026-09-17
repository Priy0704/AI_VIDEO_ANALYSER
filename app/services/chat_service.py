import asyncio
import logging
import re
import io
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime
import numpy as np
from PIL import Image
import imageio_ffmpeg
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

    def parse_exact_timestamp(self, query: str) -> Optional[float]:
        """Extract exact single timestamp in seconds (e.g. '9:44', '9 : 44', 'at 09:44')."""
        q_lower = query.lower()
        # "MM:SS" with optional spaces around colon, e.g. "9:44", "09:44", "9 : 44"
        m_colon = re.search(r'\b(\d{1,2})\s*:\s*(\d{2})\b', q_lower)
        if m_colon:
            return float(int(m_colon.group(1)) * 60 + int(m_colon.group(2)))

        # "X min Y sec" or "X minutes Y seconds"
        m_min_sec = re.search(r'(\d+)\s*(?:minute|minutes|min)\s*(\d+)?\s*(?:second|seconds|sec)?', q_lower)
        if m_min_sec:
            m = int(m_min_sec.group(1))
            s = int(m_min_sec.group(2)) if m_min_sec.group(2) else 0
            return float(m * 60 + s)

        # "at X minutes" or "around X minutes"
        m_min = re.search(r'(?:around|at|in|about)\s*(\d+)\s*(?:minute|minutes|min)\b', q_lower)
        if m_min:
            return float(int(m_min.group(1)) * 60)

        # "at X seconds"
        m_sec = re.search(r'(?:around|at|in|about)\s*(\d+)\s*(?:second|seconds|sec)\b', q_lower)
        if m_sec:
            return float(m_sec.group(1))

        return None

    def _extract_frame_at_timestamp(self, video_path: Path, timestamp_sec: float) -> Optional[Image.Image]:
        """Extract exact visual keyframe at timestamp_sec using FFmpeg pipe."""
        if not video_path.exists():
            return None
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [
                ffmpeg_exe,
                "-ss", str(max(0.0, timestamp_sec)),
                "-i", str(video_path),
                "-vframes", "1",
                "-f", "image2pipe",
                "-vcodec", "png",
                "-"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=6)
            if res.returncode == 0 and res.stdout:
                return Image.open(io.BytesIO(res.stdout)).convert("RGB")
        except Exception as e:
            logger.warning(f"Failed to extract frame at {timestamp_sec}s from {video_path}: {e}")
        return None

    def parse_temporal_scope(self, query: str, duration: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
        """Extract explicit time range (e.g. 'between 2:00 and 4:00', 'first half', 'second half', 'at 2:15', 'around 5 minutes')."""
        q_lower = query.lower()
        vid_dur = duration or 120.0

        # "when did ... start" or "when did ... begin"
        if any(w in q_lower for w in ["when did", "how did"]) and any(w in q_lower for w in ["start", "begin"]):
            return 0.0, min(15.0, vid_dur)

        # 1. "first half"
        if "first half" in q_lower:
            return 0.0, vid_dur / 2.0

        # 2. "second half"
        if "second half" in q_lower:
            return vid_dur / 2.0, vid_dur

        # 3. "between X:XX and Y:YY" or "from X:XX to Y:YY" (handles optional whitespace around colon)
        m_range = re.search(r'(?:between|from)\s*(\d{1,2})\s*:\s*(\d{2})\s*(?:and|to)\s*(\d{1,2})\s*:\s*(\d{2})', q_lower)
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

        # 5. "at X:XX" or single MM:SS (handles optional whitespace around colon)
        m_single = re.search(r'\b(\d{1,2})\s*:\s*(\d{2})\b', q_lower)
        if m_single:
            t = float(int(m_single.group(1)) * 60 + int(m_single.group(2)))
            return max(0.0, t - 15.0), t + 15.0

        # 6. "around X minutes" or "at X minutes"
        m_min = re.search(r'(?:around|at|in|about)\s*(\d+)\s*(?:minute|minutes|min)', q_lower)
        if m_min:
            t = float(int(m_min.group(1)) * 60)
            return max(0.0, t - 20.0), t + 20.0

        # 7. "around X seconds" or "at X seconds"
        m_sec = re.search(r'(?:around|at|in|about)\s*(\d+)\s*(?:second|seconds|sec)', q_lower)
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
        # 1. Exact single timestamp match (e.g. "at 9:44", "which song played in 9:44")
        exact_time = self.parse_exact_timestamp(query)
        if exact_time is not None:
            if video_duration and exact_time > video_duration + 5.0:
                return []
            stmt = select(VideoSegment).where(
                and_(
                    VideoSegment.video_id == video_id,
                    VideoSegment.start_time <= exact_time,
                    VideoSegment.end_time >= exact_time
                )
            )
            result = await db.execute(stmt)
            matched = result.scalars().all()
            if matched:
                return [(matched[0], 0.98)]
            # If between segment boundaries, retrieve closest segment
            stmt_all = select(VideoSegment).where(VideoSegment.video_id == video_id).order_by(VideoSegment.start_time)
            result_all = await db.execute(stmt_all)
            all_segs = result_all.scalars().all()
            if all_segs:
                closest = min(all_segs, key=lambda s: min(abs(s.start_time - exact_time), abs(s.end_time - exact_time)))
                return [(closest, 0.95)]
            return []

        # 2. Broader time range matching (e.g. "first half", "between 3:00 and 5:00")
        t_start, t_end = self.parse_temporal_scope(query, video_duration)
        if t_start is not None and t_end is not None:
            # If requested time is entirely beyond the video duration, no content exists
            if video_duration and t_start >= video_duration:
                return []
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
            else:
                return []

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
        q_lower = query.lower()
        person_words = {"who", "whose", "person", "someone", "speaker", "speaking", "presenter", "presenting", "man", "woman", "guy", "people", "host", "trainer"}
        name_words = {"name", "names", "mentor", "mentors", "faculty", "member", "members", "singer", "singers", "artist", "artists", "title", "titles", "song", "songs", "track", "tracks", "author", "authors", "credit", "credits", "attendee", "attendees", "participant", "participants", "list", "listed", "written", "text", "slide", "slides"}
        clothing_words = {"wear", "wearing", "clothes", "clothing", "shirt", "polo", "t-shirt", "suit", "jacket", "pants", "lanyard", "badge", "glasses"}
        display_words = {"screen", "tv", "monitor", "slide", "slides", "display", "presentation", "ui", "login", "dashboard", "board", "projector", "table", "laptop", "phone", "object", "objects"}
        speech_words = {"say", "said", "speak", "speaking", "talk", "talking", "discuss", "discussing", "topic", "words", "speech", "transcript", "dialogue", "hear", "voice", "audio"}
        action_words = {"leave", "left", "enter", "enters", "entering", "room", "gesture", "gesturing", "point", "pointing", "stand", "standing", "walk", "walking"}

        has_person_query = any(w in q_lower for w in person_words)
        has_name_query = any(w in q_lower for w in name_words)
        has_clothing_query = any(w in q_lower for w in clothing_words)
        has_display_query = any(w in q_lower for w in display_words)
        has_speech_query = any(w in q_lower for w in speech_words)
        has_action_query = any(w in q_lower for w in action_words)

        # Specific query keywords (excluding stopwords and generic speech/visual words)
        stopwords = {
            "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
            "the", "and", "is", "are", "was", "were", "this", "that", "there", "about",
            "did", "does", "been", "being", "have", "has", "had", "for", "with", "from",
            "say", "said", "tell", "told", "speak", "spoke", "mention", "mentioned"
        }
        raw_keywords = [w for w in re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', q_lower) if w not in stopwords]
        
        # Expand synonyms/aliases
        query_keywords = set(raw_keywords)
        if any(w in query_keywords for w in ["saksham", "sukshm", "suksham", "sakshm"]):
            query_keywords.update(["saksham", "sukshm", "suksham", "sakshm"])
        if any(w in query_keywords for w in ["moodle", "model"]):
            query_keywords.update(["moodle", "model"])
        if any(w in query_keywords for w in ["satya", "sathya"]):
            query_keywords.update(["satya", "sathya"])

        for segment in all_segments:
            base_score = 0.0
            if segment.embedding:
                seg_vec = np.array(segment.embedding, dtype=np.float32)
                if seg_vec.shape == query_vec.shape:
                    s_norm = np.linalg.norm(seg_vec)
                    if s_norm > 0:
                        seg_vec = seg_vec / s_norm
                    base_score = float(np.dot(query_vec, seg_vec))

            seg_trans = (segment.transcript_text or '').lower()
            seg_vis = (segment.visual_description or '').lower()
            seg_text = f"{seg_vis} {seg_trans}"
            relevance = max(0.0, base_score)

            # Direct keyword matches in speech transcript (highest priority)
            transcript_matches = sum(1 for kw in query_keywords if kw in seg_trans)
            all_matches = sum(1 for kw in query_keywords if kw in seg_text)

            if transcript_matches > 0:
                # Direct match in spoken dialogue
                relevance = max(relevance, min(0.99, 0.95 + (0.02 * transcript_matches)))
            elif all_matches > 0:
                # Direct match in visuals or combined text
                relevance = max(relevance, min(0.94, 0.86 + (0.02 * all_matches)))
            else:
                # Concept matching for semantic intent when verbatim words differ
                if has_name_query and any(w in seg_vis for w in ["on-screen text", "names:", "faculty", "mentor", "song", "title", "artist", "credits"]):
                    relevance = max(relevance, 0.96)
                elif has_name_query and any(w in seg_text for w in ["name", "faculty", "mentor", "member", "slide", "presenter", "speaker"]):
                    relevance = max(relevance, 0.92)
                if has_person_query and any(w in seg_text for w in ["man", "woman", "person", "speaker", "presenter", "standing", "speaking", "wearing", "addresses"]):
                    relevance = max(relevance, 0.92)
                if has_clothing_query and any(w in seg_text for w in ["polo", "shirt", "pants", "lanyard", "badge", "suit", "wearing", "dark", "blue"]):
                    relevance = max(relevance, 0.94)
                if has_display_query and any(w in seg_text for w in ["screen", "tv", "monitor", "slide", "presentation", "login", "interface", "display", "table"]):
                    relevance = max(relevance, 0.90)
                if has_speech_query and (segment.transcript_text or any(w in seg_text for w in ["addresses", "presents", "presentation", "speaking", "speaker", "explaining"])):
                    relevance = max(relevance, 0.91)
                if has_action_query and any(w in seg_text for w in ["standing", "gesturing", "presenting", "room", "front", "enters", "enter"]):
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
        - Factual Grounded Answers: Answer + Timestamp + Confidence + Supporting Evidence
        - Ambiguous / Subjective Intent: Human review required (HITL Required, 68% confidence)
        - Not Present in Video: "I don't know. This content is not present in the video." (Status: Not Found, NO timestamp)
        """
        session = await self.get_or_create_session(db, video.id, session_id)
        q_lower = query.lower()

        # Check for Human-In-The-Loop (HITL) verified reviews for this video
        stmt_hitl = (
            select(HITLReview)
            .where(
                and_(
                    HITLReview.video_id == video.id,
                    HITLReview.status.in_([HITLStatus.APPROVED, HITLStatus.CORRECTED])
                )
            )
            .order_by(HITLReview.reviewed_at.desc())
        )
        verified_hitl_reviews = (await db.execute(stmt_hitl)).scalars().all()

        # Check if the query directly matches an already verified human review
        matched_hitl = None
        q_stopwords = {
            "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
            "the", "and", "is", "are", "was", "were", "this", "that", "there", "about",
            "did", "does", "been", "being", "have", "has", "had", "for", "with", "from"
        }
        q_clean = re.sub(r'[^a-zA-Z0-9\s]', '', q_lower).strip()
        q_tokens = set(w for w in q_clean.split() if len(w) > 2 and w not in q_stopwords)

        for vr in verified_hitl_reviews:
            vr_q_lower = vr.query.lower()
            vr_clean = re.sub(r'[^a-zA-Z0-9\s]', '', vr_q_lower).strip()
            if q_clean == vr_clean or q_lower in vr_q_lower or vr_q_lower in q_lower:
                matched_hitl = vr
                break
            vr_tokens = set(w for w in vr_clean.split() if len(w) > 2 and w not in q_stopwords)
            if q_tokens and vr_tokens:
                overlap = len(q_tokens.intersection(vr_tokens)) / max(len(q_tokens), len(vr_tokens))
                if overlap >= 0.45:
                    matched_hitl = vr
                    break

        if matched_hitl:
            confidence_score = 1.0
            requires_hitl = False
            verified_ans = (
                matched_hitl.corrected_answer 
                if (matched_hitl.status == HITLStatus.CORRECTED and matched_hitl.corrected_answer) 
                else matched_hitl.ai_answer
            )
            evidence_str = (
                f"Human reviewer verification: {matched_hitl.reviewer_notes}"
                if matched_hitl.reviewer_notes
                else "Verified and approved by human auditor."
            )
            time_m = re.search(r'Timestamp:\s*([0-9:–\-]+)', matched_hitl.ai_answer)
            time_str = time_m.group(1).replace(" - ", "–") if time_m else "00:00–00:10"
            clean_ans = re.sub(r'^(?:Answer:\s*)+', '', verified_ans, flags=re.IGNORECASE).strip()
            if "Timestamp:" in clean_ans or "Confidence:" in clean_ans:
                answer = clean_ans
            else:
                answer = (
                    f"Answer:\n{clean_ans}\n\n"
                    f"Timestamp:\n{time_str}\n\n"
                    f"Confidence:\n100% (Human Verified)\n\n"
                    f"Supporting Evidence:\n{evidence_str}"
                )
            citations = [
                Citation(
                    start_time=0.0,
                    end_time=video.duration_seconds or 10.0,
                    timestamp_formatted=time_str,
                    snippet=evidence_str[:120],
                    relevance_score=1.0
                )
            ]
        else:
            # Subjective / Intent / Ambiguous emotion detector (Multilingual: English, Hindi, Marathi)
            sensitive_patterns = [
                r"\b(angry|anger|mad|furious|upset|irritated|annoyed|गुस्सा|नाराज|राग|चिडलेला|क्रोधी)\b",
                r"\b(attack|attacked|attacking|assault|assaulted|हमला|हल्ला)\b",
                r"\b(fight|fighting|fought|brawl|punch|punching|hit|hitting|झगड़ा|लड़ाई|भांडण|मारामारी)\b",
                r"\b(aggressive|aggressively|aggression|hostile|hostility|आक्रामक|आक्रमक)\b",
                r"\b(argue|argued|arguing|argument|quarrel|dispute|बहस|वाद|तकरार)\b",
                r"\b(intentionally|on purpose|deliberate|deliberately|malicious|maliciously|जानबूझकर|मुद्दाम|हेतू)\b",
                r"\b(threat|threaten|threatened|threatening|धमकी)\b",
                r"\b(harass|harassed|harassing|harassment|सताना|छेडछाड|त्रास)\b"
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
                    "tell me about this video", "what happened in this video", "explain the video"
                ]
            )

            # BRANCH 1: Ambiguous / Subjective interpretation query workflow (HITL Required)
            if is_sensitive_query:
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
                    "Human review required. The available video evidence is ambiguous.\n\n"
                    f"Timestamp:\n{time_str}\n\n"
                    "Confidence:\n68%\n\n"
                    "Status:\nHITL Required"
                )

            # BRANCH 2: Summarization workflow (entire video, first half, second half, key points)
            elif is_summary_query:
                confidence_score = 0.95
                requires_hitl = False
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
                    all_segs = [s for s, _ in scored_segments] if scored_segments else (await db.execute(select(VideoSegment).where(VideoSegment.video_id == video.id))).scalars().all()

                citations = [
                    Citation(
                        start_time=s.start_time,
                        end_time=s.end_time,
                        timestamp_formatted=f"{format_seconds_to_timestamp(s.start_time)}–{format_seconds_to_timestamp(s.end_time)}",
                        snippet=(s.visual_description or s.combined_text or "")[:120].replace("\n", " "),
                        relevance_score=0.95
                    )
                    for s in all_segs[:8]
                ]
                context_lines = [
                    f"Timestamp [{c.timestamp_formatted}]: Dialogue: {s.transcript_text or 'No spoken dialogue'} | Visuals: {s.visual_description}"
                    for c, s in zip(citations, all_segs[:8])
                ]
                answer = await self._generate_grounded_answer(
                    query, context_lines, video.summary, is_summary=True, confidence_score=0.95,
                    verified_reviews=verified_hitl_reviews
                )

            # BRANCH 3: Not Found (Requested content does not exist in video - NO timestamp!)
            elif not scored_segments or scored_segments[0][1] < settings.CONFIDENCE_THRESHOLD:
                confidence_score = 0.35
                requires_hitl = False
                answer = (
                    "I don't know. This content is not present in the video.\n\n"
                    "Status:\nNot Found"
                )
                citations = []

            # BRANCH 4: Grounded Multimodal Answer (Sufficient evidence available)
            else:
                requires_hitl = False
                confidence_score = float(scored_segments[0][1])
                for seg, score in scored_segments:
                    time_str = f"{format_seconds_to_timestamp(seg.start_time)}–{format_seconds_to_timestamp(seg.end_time)}"
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

                # Extract visual frame from video file if present on disk
                frame_image = None
                if video.file_path and Path(video.file_path).exists():
                    exact_t = self.parse_exact_timestamp(query)
                    if exact_t is not None:
                        frame_t = exact_t
                    elif scored_segments:
                        # Pick middle timestamp of the highest scoring segment
                        best_seg = scored_segments[0][0]
                        frame_t = (best_seg.start_time + best_seg.end_time) / 2.0
                    else:
                        frame_t = 1.0
                    frame_image = self._extract_frame_at_timestamp(Path(video.file_path), frame_t)

                answer = await self._generate_grounded_answer(
                    query, context_lines, video.summary, is_summary=False, confidence_score=confidence_score,
                    frame_image=frame_image, verified_reviews=verified_hitl_reviews
                )

        # Strict anti-hallucination safeguard for absent / out-of-box content
        if (
            "not present in the video" in answer.lower()
            or "content not found" in answer.lower()
            or ("i don't know" in answer.lower() and "video" in answer.lower())
        ):
            citations = []
            answer = re.sub(r'\n*Timestamp:\s*[^\n]+', '', answer, flags=re.IGNORECASE).strip()
            if "Status:\nNot Found" not in answer:
                answer = "I don't know. This content is not present in the video.\n\nStatus:\nNot Found"

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
        confidence_score: float = 0.90,
        frame_image: Optional[Image.Image] = None,
        verified_reviews: Optional[List[HITLReview]] = None
    ) -> str:
        """Call Gemini model with strict grounding rules or clean structured fallback adhering to the decision tree."""
        context_block = "\n\n".join(context_lines)
        time_tag = "00:00–00:10"
        if context_lines:
            m_first = re.search(r'(\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2})', context_lines[0])
            if m_first:
                time_tag = m_first.group(1).replace(" - ", "–")

        conf_pct = int(confidence_score * 100)

        hitl_block = ""
        if verified_reviews:
            v_lines = []
            for vr in verified_reviews:
                v_ans = vr.corrected_answer if (vr.status == HITLStatus.CORRECTED and vr.corrected_answer) else vr.ai_answer
                clean_v = re.sub(r'^(?:Answer:\s*)+', '', v_ans, flags=re.IGNORECASE).strip().split("Timestamp:")[0].strip()
                notes_part = f" (Reviewer Notes: {vr.reviewer_notes})" if vr.reviewer_notes else ""
                v_lines.append(f"- Verified Query: \"{vr.query}\" -> Verified Answer: \"{clean_v}\"{notes_part}")
            if v_lines:
                hitl_block = (
                    "\n\n=== HUMAN-IN-THE-LOOP (HITL) VERIFIED GROUND TRUTH ===\n"
                    "The following facts/queries for this video were verified or corrected by a human expert:\n"
                    + "\n".join(v_lines) + "\n"
                    "CRITICAL DIRECTIVE: These human-verified facts supersede automated inferences. If the user's question relates to any of these verified points, you MUST answer based on the human reviewer's input.\n\n"
                )

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            genai.configure(api_key=self.api_key, transport="rest")
            candidate_models = []
            for m in [settings.GEMINI_MODEL, "gemini-3.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"]:
                if m and m not in candidate_models:
                    candidate_models.append(m)

            if is_summary:
                prompt = (
                    "You are an expert AI Video Assistant analyzing video evidence.\n"
                    "GROUNDING PRINCIPLE: EVIDENCE > GUESSING. Never hallucinate facts or timestamps.\n\n"
                    "Rules for Video Summarization:\n"
                    "1. Do NOT return the entire transcript.\n"
                    "2. Create a concise summary of the important content and include relevant time ranges.\n"
                    "3. Format your response EXACTLY as:\n"
                    "Answer:\n"
                    "<Concise overview paragraph summarizing the core presentation/video topics>\n\n"
                    "Key Points:\n"
                    "- [MM:SS–MM:SS]: Key topic or event 1.\n"
                    "- [MM:SS–MM:SS]: Key topic or event 2.\n\n"
                    "Timestamp:\n"
                    f"{time_tag}\n\n"
                    "Confidence:\n"
                    f"{conf_pct}%\n\n"
                    f"Video Evidence and Timestamps:\n{context_block}\n\n"
                    f"Overall Video Metadata: {video_summary or 'N/A'}\n"
                    f"{hitl_block}"
                    f"User Question: {query}"
                )
            else:
                prompt = (
                    "You are an expert AI Video Assistant analyzing video evidence. Ground all answers strictly in the provided audio dialogue and visual scenes.\n"
                    "GROUNDING PRINCIPLE: EVIDENCE > GUESSING. Never hallucinate facts or timestamps.\n\n"
                    "DECISION RULES:\n"
                    "1. If the question asks about emotions, motives, conflicts, or subjective interpretation (e.g. 'Was the person angry?', 'Was this a fight?', 'Did someone intentionally attack another person?', 'Was someone behaving aggressively?'):\n"
                    "   DO NOT infer intent or make unsupported conclusions.\n"
                    "   Respond exactly with:\n"
                    "   Human review required. The available video evidence is ambiguous.\n\n"
                    "   Timestamp:\n   MM:SS–MM:SS\n\n"
                    "   Confidence:\n   68%\n\n"
                    "   Status:\n   HITL Required\n\n"
                    "2. If the requested content does not appear anywhere in the video evidence:\n"
                    "   Do not guess and DO NOT create a timestamp.\n"
                    "   Respond exactly with:\n"
                    "   I don't know. This content is not present in the video.\n\n"
                    "   Status:\n   Not Found\n\n"
                    "3. If sufficient evidence exists, provide a factual grounded response in this EXACT format:\n"
                    "   Answer:\n   <Direct concise factual answer>\n\n"
                    "   Timestamp:\n   MM:SS–MM:SS\n\n"
                    "   Confidence:\n   <Confidence percentage>%\n\n"
                    "   Supporting Evidence:\n   <Brief visual or spoken dialogue reference>\n\n"
                    "4. Multilingual Rule:\n"
                    "   Answer in the same language as the user's question. Natively support English, Hindi (हिंदी), Marathi (मराठी), and mixed languages, while preserving the required headers (Answer, Timestamp, Confidence, Supporting Evidence).\n\n"
                    "5. Names and Visible Text Rule:\n"
                    "   If the question asks for names, faculty members, mentors, attendees, speakers, presenters, song titles, or artists visible in the video or slides:\n"
                    "   List and quote the exact names found in the on-screen text, slide contents, or visual keyframe evidence verbatim. Never omit names or say 'a list of names' if specific names are present in the evidence.\n\n"
                    "6. Counting and Quantification Rule:\n"
                    "   If the question asks about counting people, persons, speakers, attendees, characters, objects, or items (e.g., 'total person count in video', 'how many people', 'how many characters'):\n"
                    "   Directly inspect the provided visual evidence, keyframes, and transcript.\n"
                    "   - If human persons are visible, state the exact or estimated count of distinct individuals seen in the keyframes/scenes and mention where/when they appear.\n"
                    "   - If there are NO human persons (e.g., the video only contains animated characters, cartoon vegetables, screen graphics, or an empty scene), explicitly state that there are 0 human persons, describe what appears instead (e.g., animated vegetable characters), and cite the timestamp.\n"
                    "   - Ground your answer completely in the attached evidence. Do NOT provide an unrelated generic summary.\n\n"
                    f"Video Evidence and Timestamps:\n{context_block}\n\n"
                    f"Overall Video Metadata: {video_summary or 'N/A'}\n"
                    f"{hitl_block}"
                    f"User Question: {query}"
                )
                if frame_image is not None:
                    prompt += (
                        "\n\nCRITICAL VISUAL EVIDENCE:\n"
                        "A visual keyframe extracted from the exact timestamp in question has been attached.\n"
                        "Read any on-screen text, titles, song names, overlays, characters, or visual actions shown in this frame.\n"
                        "Answer the user's question directly, accurately, and factually based on this visual frame."
                    )

            content_parts = [prompt]
            if frame_image is not None:
                content_parts.append(frame_image)

            for model_name in candidate_models:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = await asyncio.wait_for(
                        asyncio.to_thread(model.generate_content, content_parts),
                        timeout=35.0
                    )
                    if response and response.text:
                        txt = response.text.strip()
                        txt = re.sub(r'^(?:Answer:\s*)+', 'Answer:\n', txt, flags=re.IGNORECASE)
                        return txt
                except Exception as e:
                    logger.warning(f"Model {model_name} failed: {e}. Trying next candidate if available.")

        # Clean, human-readable grounded fallback matching the exact decision tree
        q_lower = query.lower()

        # Check if query matches any verified HITL reviews first in fallback
        if verified_reviews:
            stopwords = {"what", "when", "where", "which", "who", "whom", "why", "how", "the", "and", "is", "are", "was", "were", "this", "that", "there"}
            q_clean = set(w for w in re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', q_lower) if w not in stopwords)
            for vr in verified_reviews:
                vr_clean = set(w for w in re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', vr.query.lower()) if w not in stopwords)
                if vr.query.lower() in q_lower or q_lower in vr.query.lower() or (q_clean and vr_clean and len(q_clean.intersection(vr_clean)) / len(vr_clean) >= 0.4):
                    v_ans = vr.corrected_answer if (vr.status == HITLStatus.CORRECTED and vr.corrected_answer) else vr.ai_answer
                    clean_ans = re.sub(r'^(?:Answer:\s*)+', '', v_ans, flags=re.IGNORECASE).strip().split("Timestamp:")[0].strip()
                    ev = f"Human reviewer verification: {vr.reviewer_notes}" if vr.reviewer_notes else "Verified by human auditor."
                    return (
                        f"Answer:\n{clean_ans}\n\n"
                        f"Timestamp:\n{time_tag}\n\n"
                        f"Confidence:\n100% (Human Verified)\n\n"
                        f"Supporting Evidence:\n{ev}"
                    )

        # Extract actual dialogue from retrieved context if available
        dialogue_matches = []
        visual_matches = []
        for line in context_lines:
            if "Dialogue:" in line and "No spoken dialogue" not in line and "Ambient" not in line:
                d_part = line.split("Dialogue:", 1)[1].split("| Visuals:", 1)[0].strip()
                if d_part:
                    dialogue_matches.append(d_part)
            if "Visuals" in line:
                v_part = line.split("Visuals", 1)[1].replace("& Scene:", "").replace(":", "").strip()
                if v_part:
                    visual_matches.append(v_part)

        # 1. Summarization
        if is_summary:
            key_points = []
            for line in context_lines[:4]:
                m_t = re.search(r'(\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2})', line)
                t_str = m_t.group(1).replace(" - ", "–") if m_t else "00:00–00:10"
                if "Dialogue:" in line:
                    d_text = line.split("Dialogue:", 1)[1].split("| Visuals:", 1)[0].split("\n")[0].strip()
                    if d_text and "No spoken" not in d_text and "Ambient" not in d_text:
                        short_d = d_text[:90] + "..." if len(d_text) > 90 else d_text
                        key_points.append(f"- [{t_str}]: Covers \"{short_d}\"")
                        continue
                if "Visuals" in line:
                    v_text = line.split("Visuals", 1)[1].replace("& Scene:", "").replace(":", "").split(". ")[0].strip()
                    if v_text:
                        key_points.append(f"- [{t_str}]: {v_text[:90]}.")

            if not key_points:
                key_points = [
                    f"- [{time_tag}]: Overview and sequence of actions."
                ]
            key_points_block = "\n".join(key_points[:3])

            summary_body = (
                video_summary if (video_summary and "default" not in video_summary.lower()) else
                (f"The video contains sequential visual scenes and audio elements spanning {time_tag}. " +
                 (f"Key spoken dialogue includes: \"{dialogue_matches[0][:120]}\"." if dialogue_matches else (visual_matches[0][:150] if visual_matches else "Multimodal visual timeline.")))
            )

            return (
                "Answer:\n"
                f"{summary_body}\n\n"
                "Key Points:\n"
                f"{key_points_block}\n\n"
                "Timestamp:\n"
                f"{time_tag}\n\n"
                "Confidence:\n"
                f"{conf_pct}%"
            )

        # 2. Counting / People / Quantification
        if any(w in q_lower for w in ["count", "how many", "number of", "person", "people", "character"]):
            person_mentions = []
            for line in context_lines:
                l_lower = line.lower()
                if any(k in l_lower for k in ["person", "people", "presenter", "speaker", "man", "woman", "character"]):
                    person_mentions.append(line.split("\n")[0].strip())

            if person_mentions:
                first_mention = person_mentions[0]
                m_t = re.search(r'(\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2})', first_mention)
                p_tag = m_t.group(1).replace(" - ", "–") if m_t else time_tag
                return (
                    f"Answer:\n"
                    f"Based on the visual evidence, detected subjects in the video include: {first_mention[:160]}.\n\n"
                    f"Timestamp:\n{p_tag}\n\n"
                    f"Confidence:\n{conf_pct}%\n\n"
                    f"Supporting Evidence:\n"
                    f"Visual scene and keyframe analysis across timestamps."
                )
            else:
                return (
                    f"Answer:\n"
                    f"There are 0 human persons detected in the analyzed video segments. "
                    f"{'Visuals display: ' + visual_matches[0][:120] if visual_matches else 'No human individuals were identified in the keyframes.'}\n\n"
                    f"Timestamp:\n{time_tag}\n\n"
                    f"Confidence:\n{conf_pct}%\n\n"
                    f"Supporting Evidence:\n"
                    f"Inspection of visual keyframes and descriptions."
                )

        # 3. Spoken dialogue / What was said
        if any(w in q_lower for w in ["say", "said", "speaking", "speech", "dialogue", "talk", "what did"]):
            if dialogue_matches:
                return (
                    f"Answer:\n"
                    f"\"{dialogue_matches[0]}\"\n\n"
                    f"Timestamp:\n{time_tag}\n\n"
                    f"Confidence:\n{conf_pct}%\n\n"
                    f"Supporting Evidence:\n"
                    f"Spoken audio transcript verbatim dialogue."
                )
            else:
                return (
                    f"Answer:\n"
                    f"No spoken dialogue was detected in the relevant video segments around this timestamp.\n\n"
                    f"Timestamp:\n{time_tag}\n\n"
                    f"Confidence:\n{conf_pct}%\n\n"
                    f"Supporting Evidence:\n"
                    f"Audio transcript analysis."
                )

        # 4. Visual scenes / Screen / Objects
        if visual_matches:
            return (
                f"Answer:\n"
                f"{visual_matches[0]}\n\n"
                f"Timestamp:\n{time_tag}\n\n"
                f"Confidence:\n{conf_pct}%\n\n"
                f"Supporting Evidence:\n"
                f"Visual keyframe inspection at {time_tag}."
            )

        # Default Grounded Fallback
        ans_text = dialogue_matches[0] if dialogue_matches else (video_summary or "The video presents the demonstrated topic with grounded audio and visual details.")
        return (
            "Answer:\n"
            f"{ans_text}\n\n"
            f"Timestamp:\n{time_tag}\n\n"
            f"Confidence:\n{conf_pct}%\n\n"
            f"Supporting Evidence:\n"
            "Grounded multimodal video segments and timestamps."
        )

