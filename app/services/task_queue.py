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
from app.services.video_classifier import VideoClassifier

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
        self.video_classifier = VideoClassifier()
        self.active_tasks: Dict[str, asyncio.Task] = {}

    def enqueue_video_processing(self, video_id: str, video_path: Path) -> None:
        """Spawn a non-blocking background asyncio task to process the video."""
        task = asyncio.create_task(self._process_video_pipeline(video_id, video_path))
        self.active_tasks[video_id] = task

        def _cleanup(t):
            self.active_tasks.pop(video_id, None)

        task.add_done_callback(_cleanup)

    def enqueue_url_processing(self, video_id: str, url: str) -> None:
        """Spawn a non-blocking background asyncio task to download and process a video from a URL."""
        task = asyncio.create_task(self._process_url_pipeline(video_id, url))
        self.active_tasks[video_id] = task

        def _cleanup(t):
            self.active_tasks.pop(video_id, None)

        task.add_done_callback(_cleanup)

    def cancel_task(self, video_id: str) -> bool:
        """Cancel an in-progress or queued background task for a video."""
        task = self.active_tasks.get(video_id)
        if task and not task.done():
            task.cancel()
            self.active_tasks.pop(video_id, None)
            logger.info(f"Cancelled background task for video {video_id}")
            return True
        return False

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

    async def _run_pipeline_steps(self, video_id: str, video_path: Path) -> None:
        """Execute metadata extraction, transcription, vision descriptions, and pgvector fusion indexing."""
        # 1. Validation & Metadata extraction
        await self._update_video_progress(
            video_id, VideoStatus.PROCESSING, 20, "Extracting Video Metadata"
        )
        meta = self.video_processor.get_metadata(video_path)

        # 2. Extract Audio & Transcribe
        await self._update_video_progress(
            video_id, VideoStatus.PROCESSING, 35, "Extracting & Transcribing Audio",
            duration_seconds=meta.duration_seconds
        )
        audio_path = settings.STORAGE_DIR / f"{video_id}_audio.wav"
        extracted_audio = self.video_processor.extract_audio(video_path, audio_path)
        transcripts = await self.audio_transcriber.transcribe(extracted_audio)

        # 3. Temporal Frame Sampling
        await self._update_video_progress(
            video_id, VideoStatus.PROCESSING, 55, "Sampling Keyframes"
        )
        frame_samples = self.video_processor.sample_frames(video_path, video_id)

        # 4. Multimodal Visual Perception
        await self._update_video_progress(
            video_id, VideoStatus.PROCESSING, 75, "Analyzing Visual Perception"
        )
        visual_observations = await self.vision_describer.describe_frames(frame_samples)

        # 5. Temporal Fusion & pgvector Indexing
        await self._update_video_progress(
            video_id, VideoStatus.PROCESSING, 90, "Indexing Temporal Vectors in pgvector"
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

            # 6. Video Type Classification (Knowledge vs Observational)
            await self._update_video_progress(
                video_id, VideoStatus.PROCESSING, 96, "Classifying Video Content"
            )
            classification = await self.video_classifier.classify_video(
                filename=video.filename,
                transcripts=[t.text for t in transcripts],
                visual_descriptions=[v.description for v in visual_observations],
                ocr_texts=[getattr(v, "ocr_text", "") for v in visual_observations],
                summary=video.summary,
                duration_seconds=meta.duration_seconds
            )
            video.video_type = classification.video_type
            video.video_type_label = classification.label
            video.video_type_confidence = classification.confidence
            video.video_type_reason = classification.reason
            await db.commit()

        await self._update_video_progress(
            video_id, VideoStatus.COMPLETED, 100, "Completed"
        )
        logger.info(f"Pipeline completed successfully for video {video_id} (classified as: {classification.label})")

    async def _process_video_pipeline(self, video_id: str, video_path: Path) -> None:
        """Worker executing the full perception and indexing pipeline under semaphore."""
        async with self.semaphore:
            logger.info(f"Starting processing pipeline for video {video_id} ({video_path.name})")
            try:
                await self._run_pipeline_steps(video_id, video_path)
            except Exception as e:
                logger.exception(f"Error processing video {video_id}: {e}")
                await self._update_video_progress(
                    video_id,
                    VideoStatus.FAILED,
                    0,
                    "Failed",
                    error_message=str(e)
                )

    async def _process_url_pipeline(self, video_id: str, url: str) -> None:
        """Worker executing asynchronous URL download followed by multimodal pipeline under semaphore."""
        async with self.semaphore:
            logger.info(f"Starting URL download pipeline for video {video_id} ({url})")
            try:
                await self._update_video_progress(
                    video_id, VideoStatus.PROCESSING, 10, "Downloading video stream from link..."
                )
                from app.services.url_downloader import UrlDownloader
                downloader = UrlDownloader(download_dir=settings.UPLOAD_DIR)
                download_info = await downloader.download_video(url)

                file_path = Path(download_info["file_path"])
                total_bytes = int(download_info.get("file_size_mb", 0) * 1024 * 1024)

                async with AsyncSessionLocal() as db:
                    video = await db.get(Video, video_id)
                    if video:
                        video.filename = download_info.get("filename", video.filename)
                        video.file_path = str(file_path.resolve())
                        video.file_size_bytes = total_bytes
                        if download_info.get("duration_seconds"):
                            video.duration_seconds = download_info["duration_seconds"]
                        await db.commit()

                await self._run_pipeline_steps(video_id, file_path)

            except Exception as e:
                logger.exception(f"Error downloading or processing video {video_id} from URL {url}: {e}")
                await self._update_video_progress(
                    video_id,
                    VideoStatus.FAILED,
                    0,
                    "Failed",
                    error_message=str(e)
                )


# Singleton task queue
task_queue = VideoTaskQueue()
