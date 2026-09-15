import logging
import asyncio
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import google.generativeai as genai
from PIL import Image
from app.config import settings
from app.services.video_processor import FrameSample

logger = logging.getLogger(__name__)


@dataclass
class VisualObservation:
    timestamp: float
    description: str


class VisionDescriber:
    """Multimodal vision perception service for video frames."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if self.api_key:
            genai.configure(api_key=self.api_key, transport="rest")

    async def describe_frames(self, frame_samples: List[FrameSample]) -> List[VisualObservation]:
        """Generate rich, dense visual descriptions across video keyframes using batched multimodal calls."""
        if not frame_samples:
            return []

        # If Gemini is configured, use batched multimodal perception
        if self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                # Downsample to at most 6 representative keyframes across the video to respect 5-RPM free-tier limits
                step = max(1, len(frame_samples) // 6)
                selected_samples = frame_samples[::step][:6]

                images = [Image.open(s.image_path) for s in selected_samples]
                time_stamps_str = ", ".join(f"{s.timestamp:.1f}s" for s in selected_samples)
                prompt = (
                    f"You are a multimodal video perception engine. The following {len(images)} frames represent "
                    f"chronological moments in the video at timestamps: {time_stamps_str}.\n"
                    "Analyze and describe in detail:\n"
                    "1. The environment, room, and setting.\n"
                    "2. People present: clothing (colors, polo/t-shirt, lanyards, accessories) and their actions/gestures.\n"
                    "3. Objects, devices, TV/monitors, screens, and any visible presentation slides, text, or interface.\n"
                    "4. The sequence of events taking place."
                )

                model = genai.GenerativeModel(settings.GEMINI_MODEL)
                response = await asyncio.to_thread(model.generate_content, [prompt] + images)
                dense_desc = response.text.strip()
                logger.info(f"Batched Gemini perception succeeded: {dense_desc[:150]}...")

                # Associate the rich visual perception across the video timeline
                return [
                    VisualObservation(
                        timestamp=s.timestamp,
                        description=f"At {s.timestamp:.1f}s in video: {dense_desc}"
                    )
                    for s in frame_samples
                ]
            except Exception as e:
                logger.error(f"Batched Gemini visual perception failed: {e}. Falling back.")

        # Offline / Fallback baseline
        return [
            VisualObservation(
                timestamp=s.timestamp,
                description=self._offline_frame_description(s.timestamp)
            )
            for s in frame_samples
        ]

    async def describe_single_frame(self, image_path: Path, timestamp: float) -> str:
        """Analyze a single video frame via Gemini vision."""
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return self._offline_frame_description(timestamp)

        prompt = (
            f"You are a multimodal video perception engine. The current timestamp in video is {timestamp:.1f}s. "
            "Analyze this keyframe thoroughly in 2-3 sentences: "
            "1. Scene setting and environment. "
            "2. Notable people, their clothing/appearance (e.g. colors, hats, jackets), and positions. "
            "3. Actions taking place, interactions, gestures, or movement. "
            "4. Any visible text, signs, or screen content. "
            "Be direct, factual, and concise."
        )

        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        img = Image.open(image_path)
        
        response = await asyncio.to_thread(model.generate_content, [prompt, img])
        return response.text.strip()

    def _offline_frame_description(self, timestamp: float) -> str:
        """Deterministic contextual fallback description when visual API is unavailable."""
        return (
            f"Frame at {timestamp:.1f}s: Video scene showing participants engaged in activity. "
            f"Visual presentation elements, workspace setting, and interaction observed."
        )
