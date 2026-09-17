import asyncio
import logging
import math
import hashlib
from typing import List, Optional
import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.models import Video, VideoSegment, VideoStatus
from app.services.audio_transcriber import TranscriptSegment
from app.services.vision_describer import VisualObservation

logger = logging.getLogger(__name__)


class FusionIndexer:
    """Fuses audio transcripts and visual observations into temporal segments and indexes them in PostgreSQL + pgvector."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if self.api_key:
            genai.configure(api_key=self.api_key, transport="rest")

    async def fuse_and_index(
        self,
        db: AsyncSession,
        video: Video,
        transcripts: List[TranscriptSegment],
        visuals: List[VisualObservation],
        window_size_sec: float = 10.0
    ) -> List[VideoSegment]:
        """
        Groups audio and visual evidence into sliding temporal windows, computes vector embeddings,
        and saves VideoSegment records in PostgreSQL with pgvector embeddings.
        """
        duration = video.duration_seconds or (
            max([v.timestamp for v in visuals] + [t.end for t in transcripts] + [10.0])
        )

        num_windows = max(1, math.ceil(duration / window_size_sec))
        segments_to_create: List[VideoSegment] = []

        # Store full high-fidelity raw transcripts on the video record
        if transcripts:
            video.raw_transcripts = [
                {"start": round(t.start, 2), "end": round(t.end, 2), "text": t.text}
                for t in transcripts
            ]

        logger.info(f"Fusing {len(transcripts)} transcripts and {len(visuals)} visuals into {num_windows} temporal windows.")

        for i in range(num_windows):
            start_t = round(i * window_size_sec, 2)
            end_t = round(min(duration, (i + 1) * window_size_sec), 2)

            # Gather transcripts whose midpoint falls within this window to avoid duplicating across adjacent windows
            if i == num_windows - 1:
                window_transcripts = [
                    t.text for t in transcripts
                    if start_t <= ((t.start + t.end) / 2) <= end_t
                ]
            else:
                window_transcripts = [
                    t.text for t in transcripts
                    if start_t <= ((t.start + t.end) / 2) < end_t
                ]
            transcript_text = " ".join(window_transcripts).strip()

            # Gather visuals occurring within this window
            window_visuals = [
                v.description for v in visuals
                if start_t <= v.timestamp <= end_t
            ]
            visual_text = " ".join(window_visuals).strip()

            # Gather OCR on-screen text occurring within this window
            window_ocr = [
                getattr(v, "ocr_text", "") for v in visuals
                if start_t <= v.timestamp <= end_t and getattr(v, "ocr_text", "")
            ]
            # Deduplicate while preserving order
            ocr_text = " | ".join(dict.fromkeys(window_ocr)).strip()

            # Combine audio, visual, and OCR perception into a unified contextual string
            parts = []
            if transcript_text:
                parts.append(f"Audio/Dialogue: {transcript_text}")
            if visual_text:
                parts.append(f"Visual Scene: {visual_text}")
            if ocr_text:
                parts.append(f"On-Screen Text/OCR: {ocr_text}")

            combined_text = "\n".join(parts) if parts else f"Timestamp [{start_t:.1f}s - {end_t:.1f}s]: General video progression."

            # Generate 768-dim vector embedding
            embedding_vec = await self.generate_embedding(combined_text)

            segment = VideoSegment(
                video_id=video.id,
                start_time=start_t,
                end_time=end_t,
                transcript_text=transcript_text,
                visual_description=visual_text,
                ocr_text=ocr_text,
                combined_text=combined_text,
                embedding=embedding_vec
            )
            db.add(segment)
            segments_to_create.append(segment)

        # Generate a video-level summary
        summary = await self._generate_video_summary(segments_to_create)
        video.summary = summary
        video.status = VideoStatus.COMPLETED
        video.progress_pct = 100
        video.current_stage = "Completed"

        await db.commit()
        logger.info(f"Successfully indexed {len(segments_to_create)} segments for video {video.id} with pgvector embeddings.")
        return segments_to_create

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate a consistent 768-dimensional normalized embedding."""
        return self._deterministic_embedding(text, dim=768)

    def _deterministic_embedding(self, text: str, dim: int = 768) -> List[float]:
        """Generate a deterministic normalized vector based on SHA-256 tokens."""
        words = text.lower().split()
        vec = [0.0] * dim
        if not words:
            vec[0] = 1.0
            return vec

        for word in words:
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            idx = h % dim
            val = ((h >> 8) % 1000) / 1000.0 - 0.5
            vec[idx] += val

        # Normalize L2 norm
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0
        return vec

    async def _generate_video_summary(self, segments: List[VideoSegment]) -> str:
        """Create a cohesive overview of the entire video across its full timeline."""
        if not segments:
            return "No segments indexed for this video."

        # Sample representative moments across the entire video (start, middle, end)
        step = max(1, len(segments) // 8)
        sampled = segments[::step][:8]
        sample_snippets = [
            f"[{s.start_time:.0f}s - {s.end_time:.0f}s]: {s.combined_text[:140]}"
            for s in sampled
        ]
        context = "\n".join(sample_snippets)

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            candidate_models = []
            for m in [settings.GEMINI_MODEL, "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
                if m and m not in candidate_models:
                    candidate_models.append(m)

            prompt = (
                "Provide a concise, engaging 2-3 sentence overview summarizing what occurs in this video "
                "(such as song performance, music video theme, dialogue, or visual progression) "
                f"based on these chronological moments sampled across the timeline:\n{context}"
            )
            for model_name in candidate_models:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = await asyncio.to_thread(model.generate_content, prompt)
                    if response and response.text:
                        return response.text.strip()
                except Exception as e:
                    logger.warning(f"Summary generation with {model_name} failed: {e}")

        # Intelligent fallback summary derived from actual sampled visual descriptions and audio
        headlines = []
        for s in sampled:
            if s.visual_description:
                first_line = s.visual_description.split("\n")[0].replace("Headline:", "").strip()
                if first_line and first_line not in headlines and len(first_line) > 10:
                    headlines.append(first_line)

        lyrics_preview = [s.transcript_text for s in sampled if s.transcript_text and len(s.transcript_text) > 3]
        parts = []
        if headlines:
            parts.append(f"Visual progression highlights: {'; '.join(headlines[:3])}.")
        if lyrics_preview:
            parts.append(f"Includes spoken/lyric dialogue such as \"{lyrics_preview[0][:70]}\".")

        if parts:
            return " ".join(parts)

        return (
            f"Video spans {len(segments)} indexed temporal moments with coordinated visual scenes "
            f"and audio from {segments[0].start_time:.1f}s to {segments[-1].end_time:.1f}s."
        )
