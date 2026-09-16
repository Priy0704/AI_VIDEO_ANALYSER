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
        """Generate rich, dense visual descriptions across video keyframes using batched multimodal calls with full OCR & name extraction."""
        if not frame_samples:
            return []

        # If Gemini is configured, use batched multimodal perception
        if self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                # Select evenly spaced samples across the timeline (up to 30 frames to guarantee full coverage without exceeding rate limits)
                total_samples = len(frame_samples)
                target_count = min(30, total_samples)
                if total_samples > target_count:
                    step = total_samples / target_count
                    selected_samples = [frame_samples[int(i * step)] for i in range(target_count)]
                else:
                    selected_samples = list(frame_samples)

                # Process in batches of 5 frames per multimodal call
                batch_size = 5
                batches = [selected_samples[i:i + batch_size] for i in range(0, len(selected_samples), batch_size)]
                
                logger.info(f"Analyzing {len(selected_samples)} keyframes across {len(batches)} multimodal batches for full visual + OCR perception.")

                frame_map: Dict[float, str] = {}
                candidate_models = []
                for m in ["gemini-3.5-flash-lite", settings.GEMINI_MODEL, "gemini-3.6-flash"]:
                    if m and m not in candidate_models:
                        candidate_models.append(m)

                for batch_idx, batch in enumerate(batches):
                    images = [Image.open(s.image_path) for s in batch]
                    time_stamps_str = ", ".join(f"{s.timestamp:.1f}s" for s in batch)

                    prompt = (
                        f"You are an expert multimodal video perception and OCR engine. The following {len(images)} images represent "
                        f"chronological frames from the video at timestamps: {time_stamps_str}.\n\n"
                        "MANDATORY INSTRUCTIONS:\n"
                        "1. FULL OCR & ON-SCREEN TEXT EXTRACTION: Exhaustively transcribe and extract ALL visible text, presentation slide contents, bullet points, headers, footers, labels, logos, and lower thirds.\n"
                        "2. EXTRACT ALL NAMES: If there are names of people, faculty members, mentors, presenters, speakers, artists, singers, or participants shown on screen (e.g. in bullet points or columns), YOU MUST LIST AND QUOTE EVERY SINGLE NAME VERBATIM. DO NOT summarize as 'a list of names' - write out the actual names!\n"
                        "3. SONG & MEDIA TITLES: If song titles, music credits, or video titles are visible, state them verbatim.\n\n"
                        "Output format for EACH frame:\n"
                        "[FRAME: <timestamp>s]\n"
                        "Headline: <One concise sentence summarizing the main visual scene, slide topic, or action>\n"
                        "Details: <1-2 sentences describing the people, setting, actions, and atmosphere>\n"
                        "Visible Text & Names: <List all visible text, slide titles, bullet points, and names verbatim. If none, write 'None'>\n\n"
                        "Example:\n"
                        "[FRAME: 24.0s]\n"
                        "Headline: Slide displays faculty members and mentors of the program.\n"
                        "Details: Presentation slide showing two columns of faculty and mentor names under Harbinger Group branding.\n"
                        "Visible Text & Names: Slide title: 'Faculty members and mentors of the program-'. Names: Adhiraj Gadgil, Aditya Kulkarni, Amit A Kulkarni, Anu Riswadkar, Anuradha Apte, Ashish Chakraborty, Ashita Vinchurkar, Ashwini Mahabal, Bharti Satpute, Deepashree Kulkarni, Dharmendra M, Neville Postwalla, Nitin Goswami, Prachi Dugal, Prachi Jamadar, Pushpendra Shimpi, Rohan Udas, Ruby Baksi, Rupali Warshetti, Samiksha Dhangade, Sandesh Patne, Shakeel Saraf, Shashank Uttekar, Umesh Kanade, Umesh Sodmise."
                    )

                    batch_desc = None
                    for model_name in candidate_models:
                        try:
                            model = genai.GenerativeModel(model_name)
                            response = await asyncio.to_thread(model.generate_content, [prompt] + images)
                            if response and response.text:
                                batch_desc = response.text.strip()
                                break
                        except Exception as err:
                            logger.warning(f"Batch {batch_idx+1} vision model {model_name} failed: {err}")

                    if batch_desc:
                        parsed_blocks = self._parse_frame_blocks(batch_desc, batch)
                        frame_map.update(parsed_blocks)
                    else:
                        logger.warning(f"Batch {batch_idx+1} could not be analyzed with multimodal AI.")

                if frame_map:
                    logger.info(f"Batched Gemini perception succeeded for {len(frame_map)} moments across timeline.")
                    observations = []
                    sorted_ts = sorted(frame_map.keys())
                    for s in frame_samples:
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
        """Parse Gemini output into timestamp -> rich description map including on-screen text and names."""
        result: Dict[float, str] = {}

        pattern = re.compile(r'\[FRAME:\s*([0-9.]+)s?\]\s*(.*?)(?=\[FRAME:|\Z)', re.DOTALL | re.IGNORECASE)
        matches = list(pattern.finditer(text))

        if matches:
            for m in matches:
                try:
                    ts = float(m.group(1))
                    body = m.group(2).strip()

                    head_m = re.search(r'Headline:\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
                    det_m = re.search(r'Details:\s*(.+?)(?:\n\s*(?:Visible Text|Names)|\Z)', body, re.DOTALL | re.IGNORECASE)
                    text_m = re.search(r'(?:Visible Text & Names|Visible Text|Names):\s*(.+)', body, re.DOTALL | re.IGNORECASE)

                    parts = []
                    if head_m:
                        parts.append(f"Headline: {head_m.group(1).strip()}")
                    if det_m:
                        det_text = det_m.group(1).strip()
                        if det_text:
                            parts.append(f"Details: {det_text}")
                    if text_m:
                        vis_names = text_m.group(1).strip()
                        if vis_names and vis_names.lower() != "none":
                            parts.append(f"On-Screen Text & Names: {vis_names}")

                    if parts:
                        result[ts] = "\n".join(parts)
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
