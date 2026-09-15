import asyncio
import logging
from pathlib import Path
from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Video, VideoStatus
from app.services.video_processor import VideoProcessor
from app.services.audio_transcriber import AudioTranscriber
from app.services.vision_describer import VisionDescriber
from app.services.fusion_indexer import FusionIndexer

logger = logging.getLogger(__name__)


class VideoTaskQueue:
    """
    Manages asynchronous pipeline execution with controlled concurrency.
    Supports high concurrency (e.g., 10+ simultaneous uploads) by queueing tasks
    and running up to MAX_CONCURRENT_WORKERS without exhausting system resources.
    """

    def __init__(self, max_concurrent: int = settings.MAX_CONCURRENT_WORKERS):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.video_processor = VideoProcessor()
        self.audio_transcriber = AudioTranscriber()
        self.vision_describer = VisionDescriber()
        self.fusion_indexer = FusionIndexer()
        self.active_tasks: Dict[str, asyncio.Task] = {}

    def enqueue_video_processing(self, video_id: str, video_path: Path) -> None:
        """Spawn a non-blocking background asyncio task to process the video."""
        task = asyncio.create_task(self._process_video_pipeline(video_id, video_path))
        self.active_tasks[video_id] = task

        def _cleanup(t):
            self.active_tasks.pop(video_id, None)

        task.add_done_callback(_cleanup)

    async def _update_video_progress(
        self,
        video_id: str,
        status: VideoStatus,
        progress_pct: int,
        stage: str,
        duration_seconds: float = None,
        error_message: str = None
    ) -> None:
        """Update video state in PostgreSQL."""
        async with AsyncSessionLocal() as db:
            video = await db.get(Video, video_id)
            if video:
                video.status = status
                video.progress_pct = progress_pct
                video.current_stage = stage
                if duration_seconds is not None:
                    video.duration_seconds = duration_seconds
                if error_message is not None:
                    video.error_message = error_message
                await db.commit()

    async def _process_video_pipeline(self, video_id: str, video_path: Path) -> None:
        """Worker executing the full perception and indexing pipeline under semaphore."""
        async with self.semaphore:
            logger.info(f"Starting processing pipeline for video {video_id} ({video_path.name})")

            try:
                # 1. Validation & Metadata extraction
                await self._update_video_progress(
                    video_id, VideoStatus.PROCESSING, 15, "Extracting Video Metadata"
                )
                meta = self.video_processor.get_metadata(video_path)

                # 2. Extract Audio & Transcribe
                await self._update_video_progress(
                    video_id, VideoStatus.PROCESSING, 30, "Extracting & Transcribing Audio",
                    duration_seconds=meta.duration_seconds
                )
                audio_path = settings.STORAGE_DIR / f"{video_id}_audio.wav"
                extracted_audio = self.video_processor.extract_audio(video_path, audio_path)
                transcripts = await self.audio_transcriber.transcribe(extracted_audio)

                # 3. Temporal Frame Sampling
                await self._update_video_progress(
                    video_id, VideoStatus.PROCESSING, 50, "Sampling Keyframes"
                )
                frame_samples = self.video_processor.sample_frames(video_path, video_id)

                # 4. Multimodal Visual Perception
                await self._update_video_progress(
                    video_id, VideoStatus.PROCESSING, 70, "Analyzing Visual Perception"
                )
                visual_observations = await self.vision_describer.describe_frames(frame_samples)

                # 5. Temporal Fusion & pgvector Indexing
                await self._update_video_progress(
                    video_id, VideoStatus.PROCESSING, 85, "Indexing Temporal Vectors in pgvector"
                )

                async with AsyncSessionLocal() as db:
                    video = await db.get(Video, video_id)
                    if not video:
                        raise ValueError(f"Video {video_id} not found in database.")
                    video.duration_seconds = meta.duration_seconds

                    await self.fusion_indexer.fuse_and_index(
                        db=db,
                        video=video,
                        transcripts=transcripts,
                        visuals=visual_observations
                    )

                logger.info(f"Pipeline completed successfully for video {video_id}")

            except Exception as e:
                logger.exception(f"Error processing video {video_id}: {e}")
                await self._update_video_progress(
                    video_id,
                    VideoStatus.FAILED,
                    0,
                    "Failed",
                    error_message=str(e)
                )


# Singleton task queue
task_queue = VideoTaskQueue()
