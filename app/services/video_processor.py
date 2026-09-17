import cv2
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import imageio_ffmpeg
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    duration_seconds: float
    fps: float
    frame_count: int
    width: int
    height: int


@dataclass
class FrameSample:
    timestamp: float
    frame_index: int
    image_path: Path


class VideoProcessor:
    """Handles video validation, metadata extraction, audio demuxing, and temporal frame sampling."""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or imageio_ffmpeg.get_ffmpeg_exe()

    def get_metadata(self, video_path: Path) -> VideoMetadata:
        """Extract duration, FPS, and dimensions using OpenCV."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
            duration = frame_count / fps if fps > 0 else 0.0

            return VideoMetadata(
                duration_seconds=round(duration, 2),
                fps=round(fps, 2),
                frame_count=frame_count,
                width=width,
                height=height
            )
        finally:
            cap.release()

    def extract_audio(self, video_path: Path, output_audio_path: Path) -> Path:
        """Extract 16kHz mono WAV audio stream from video using bundled FFmpeg."""
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite
            "-i", str(video_path),
            "-vn",  # No video
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,volume=1.5",  # Normalize speech volume for crystal clear ASR
            "-acodec", "pcm_s16le",
            "-ar", "16000",  # 16kHz sample rate standard for ASR
            "-ac", "1",      # Mono channel
            str(output_audio_path)
        ]

        logger.info(f"Extracting audio to {output_audio_path}")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            logger.warning(f"FFmpeg audio extraction warning/error: {result.stderr}")
            # Video might be silent/have no audio stream
            if "does not contain any stream" in result.stderr or not output_audio_path.exists():
                logger.info(f"Video {video_path.name} appears to have no audio stream.")
                return None

        return output_audio_path

    def sample_frames(
        self,
        video_path: Path,
        video_id: str,
        interval_sec: Optional[float] = None
    ) -> List[FrameSample]:
        """
        Simple intelligent temporal frame sampling.
        Extracts 1 frame every interval_sec (default 3.0s) along the timeline.
        Guarantees predictable compute, no memory spikes, and uniform video coverage.
        """
        base_interval = interval_sec or settings.FRAME_SAMPLE_INTERVAL_SEC
        output_dir = settings.KEYFRAME_DIR / video_id
        output_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video file for sampling: {video_path}")

        samples: List[FrameSample] = []
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            duration = total_frames / fps if fps > 0 else 0.0

            # For long videos (>5 mins / 300s, up to 30 mins), adapt interval to avoid excessive frames and disk I/O
            # while guaranteeing uniform coverage (~40-50 keyframes across the timeline)
            if duration > 300.0:
                interval = max(base_interval, duration / 50.0)
            else:
                interval = base_interval

            # Calculate timestamps to sample: 0.0, interval, 2*interval...
            current_time = 0.0
            while current_time < duration or len(samples) == 0:
                frame_idx = int(current_time * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break

                frame_filename = f"frame_{int(current_time * 1000):08d}ms.jpg"
                frame_path = output_dir / frame_filename
                
                # Resize large frames for efficient storage & AI processing (max width 1280)
                h, w = frame.shape[:2]
                if w > 1280:
                    scale = 1280 / w
                    frame = cv2.resize(frame, (1280, int(h * scale)))

                cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

                samples.append(FrameSample(
                    timestamp=round(current_time, 2),
                    frame_index=frame_idx,
                    image_path=frame_path
                ))

                current_time += interval
                if duration == 0:
                    break

            logger.info(f"Sampled {len(samples)} frames for video {video_id} (interval={interval}s)")
            return samples
        finally:
            cap.release()
