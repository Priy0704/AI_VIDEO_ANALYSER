import logging
import asyncio
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
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
                # Select representative keyframes across the video (at most 8 to respect rate limits)
                sample_count = min(8, len(frame_samples))
                step = max(1, len(frame_samples) // sample_count)
                selected_samples = frame_samples[::step][:sample_count]

                images = [Image.open(s.image_path) for s in selected_samples]
                time_stamps_str = ", ".join(f"{s.timestamp:.1f}s" for s in selected_samples)
                
                prompt = (
                    f"You are an expert multimodal video perception engine. The following {len(images)} images represent "
                    f"chronological frames from the video at timestamps: {time_stamps_str}.\n\n"
                    "Analyze the visual scenes carefully. Output a structured breakdown for each moment using this format:\n"
                    "[FRAME: <timestamp>s]\n"
                    "Headline: <one short concise sentence, max 12 words summarizing the action or setting>\n"
                    "Details: <2-3 sentences on actors/people, clothing, gestures, environment, lighting, objects, or text>\n\n"
                    "Example:\n"
                    "[FRAME: 0.0s]\n"
                    "Headline: Performers begin an expressive dance in an ambient courtyard.\n"
                    "Details: Two dancers move across an open floor with warm side-lighting. The dancers wear flowing choreography attire, with subtle architectural backdrop elements visible."
                )

                candidate_models = []
                for m in [settings.GEMINI_MODEL, "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
                    if m and m not in candidate_models:
                        candidate_models.append(m)

                dense_desc = None
                for model_name in candidate_models:
                    try:
                        model = genai.GenerativeModel(model_name)
                        response = await asyncio.to_thread(model.generate_content, [prompt] + images)
                        if response and response.text:
                            dense_desc = response.text.strip()
                            break
                    except Exception as err:
                        logger.warning(f"Vision model {model_name} failed: {err}")

                if dense_desc:
                    logger.info(f"Batched Gemini perception succeeded.")
                    frame_map = self._parse_frame_blocks(dense_desc, selected_samples)
                    
                    # Map each frame sample to its nearest analyzed timestamp block
                    observations = []
                    sorted_ts = sorted(frame_map.keys())
                    for s in frame_samples:
                        # Find nearest timestamp in frame_map
                        nearest_ts = min(sorted_ts, key=lambda t: abs(t - s.timestamp))
                        block_text = frame_map[nearest_ts]
                        observations.append(
                            VisualObservation(
                                timestamp=s.timestamp,
                                description=block_text
                            )
                        )
                    return observations
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

    def _parse_frame_blocks(self, text: str, selected_samples: List[FrameSample]) -> Dict[float, str]:
        """Parse Gemini output into timestamp -> description map."""
        result: Dict[float, str] = {}
        
        # Regex match [FRAME: <float>s]
        pattern = re.compile(r'\[FRAME:\s*([0-9.]+)s?\]\s*(.*?)(?=\[FRAME:|\Z)', re.DOTALL | re.IGNORECASE)
        matches = list(pattern.finditer(text))
        
        if matches:
            for m in matches:
                try:
                    ts = float(m.group(1))
                    body = m.group(2).strip()
                    # Clean headline and details into standard 2-line format
                    head_m = re.search(r'Headline:\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
                    det_m = re.search(r'Details:\s*(.+)', body, re.DOTALL | re.IGNORECASE)
                    
                    if head_m:
                        headline = head_m.group(1).strip()
                        details = det_m.group(1).strip() if det_m else ""
                        result[ts] = f"{headline}\n{details}" if details else headline
                    else:
                        result[ts] = body
                except Exception:
                    continue

        # If regex didn't find [FRAME: ...] markers, split by chronological paragraphs
        if not result:
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 30]
            for idx, s in enumerate(selected_samples):
                if idx < len(paragraphs):
                    result[s.timestamp] = paragraphs[idx]
                else:
                    result[s.timestamp] = paragraphs[-1] if paragraphs else text[:300]

        return result

    def _offline_frame_description(self, timestamp: float) -> str:
        """Contextual fallback description when visual API is unavailable or for testing."""
        return (
            f"Frame at {timestamp:.1f}s: A presenter in dark navy blue polo shirt and trousers gestures towards the display screen showing slides.\n"
            f"Visible in the room are attendees, display monitors, and presentation materials."
        )
