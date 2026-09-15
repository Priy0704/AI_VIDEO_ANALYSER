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
            genai.configure(api_key=self.api_key)

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

        logger.info(f"Fusing {len(transcripts)} transcripts and {len(visuals)} visuals into {num_windows} temporal windows.")

        for i in range(num_windows):
            start_t = round(i * window_size_sec, 2)
            end_t = round(min(duration, (i + 1) * window_size_sec), 2)

            # Gather transcripts overlapping this time window
            window_transcripts = [
                t.text for t in transcripts
                if not (t.end < start_t or t.start > end_t)
            ]
            transcript_text = " ".join(window_transcripts).strip()

            # Gather visuals occurring within this window
            window_visuals = [
                v.description for v in visuals
                if start_t <= v.timestamp <= end_t
            ]
            visual_text = " ".join(window_visuals).strip()

            # Combine audio and visual perception into a unified contextual string
            parts = []
            if transcript_text:
                parts.append(f"Audio/Dialogue: {transcript_text}")
            if visual_text:
                parts.append(f"Visual Scene: {visual_text}")

            combined_text = "\n".join(parts) if parts else f"Timestamp [{start_t:.1f}s - {end_t:.1f}s]: General video progression."

            # Generate 768-dim vector embedding
            embedding_vec = await self.generate_embedding(combined_text)

            segment = VideoSegment(
                video_id=video.id,
                start_time=start_t,
                end_time=end_t,
                transcript_text=transcript_text,
                visual_description=visual_text,
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
        """Generate a 768-dimensional normalized vector embedding."""
        if self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                result = genai.embed_content(
                    model="models/text-embedding-004",
                    content=text,
                    task_type="retrieval_document"
                )
                vec = result['embedding']
                if len(vec) == 768:
                    return vec
            except Exception as e:
                logger.warning(f"Gemini embedding API call failed: {e}. Falling back to deterministic embedding.")

        # Offline / deterministic 768-dimensional normalized embedding
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
        """Create a hierarchical summary of the entire video."""
        sample_snippets = [
            f"[{s.start_time:.0f}s - {s.end_time:.0f}s]: {s.combined_text[:120]}"
            for s in segments[:10]
        ]
        context = "\n".join(sample_snippets)

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                model = genai.GenerativeModel(settings.GEMINI_MODEL)
                prompt = (
                    "Provide a comprehensive 2-3 sentence overview summarizing what occurs in this video "
                    f"based on these chronological segments:\n{context}"
                )
                response = await model.generate_content_async(prompt)
                return response.text.strip()
            except Exception as e:
                logger.warning(f"Summary generation error: {e}")

        return (
            f"Video contains {len(segments)} indexed temporal segments spanning actions, visual scenes, "
            f"and dialogue from {segments[0].start_time:.1f}s to {segments[-1].end_time:.1f}s."
        )
