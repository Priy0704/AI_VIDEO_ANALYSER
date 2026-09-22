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
    ocr_text: str = ""


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
                # Select evenly spaced samples across the timeline (up to 50 frames to guarantee full coverage for up to 30 min videos)
                total_samples = len(frame_samples)
                target_count = min(50, total_samples)
                if total_samples > target_count:
                    step = total_samples / target_count
                    selected_samples = [frame_samples[int(i * step)] for i in range(target_count)]
                else:
                    selected_samples = list(frame_samples)

                # Process in batches of 5 frames per multimodal call
                batch_size = 5
                batches = [selected_samples[i:i + batch_size] for i in range(0, len(selected_samples), batch_size)]
                
                logger.info(f"Analyzing {len(selected_samples)} keyframes across {len(batches)} multimodal batches for full visual + OCR perception.")

                frame_map: Dict[float, Dict[str, str]] = {}
                candidate_models = []
                for m in [settings.GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
                    if m and m not in candidate_models:
                        candidate_models.append(m)

                for batch_idx, batch in enumerate(batches):
                    images = [Image.open(s.image_path) for s in batch]
                    time_stamps_str = ", ".join(f"{s.timestamp:.1f}s" for s in batch)

                    prompt = (
                        f"You are an expert multimodal video perception and OCR engine. The following {len(images)} images represent "
                        f"chronological frames from the video at timestamps: {time_stamps_str}.\n\n"
                        "MANDATORY EXTRACTION INSTRUCTIONS:\n"
                        "1. FULL OCR & ON-SCREEN TEXT: Transcribe and extract ALL visible text, presentation slides, headers, bullet points, footers, website URLs, software UI labels, subscriber counts, metrics, and logos.\n"
                        "2. EXTRACT ALL NAMES VERBATIM: If there are names of people, faculty, mentors, presenters, speakers, attendees, singers, or participants shown anywhere on screen, LIST EVERY SINGLE NAME VERBATIM. Never summarize as 'a list of names'.\n"
                        "3. DEEP BACKGROUND & VISUAL CONTEXT: Describe background elements, room setting (office, stage, classroom, outdoors, studio, street, vehicles), lighting, furniture, items, background people, clothing, and physical actions/gestures accurately. Do not invent details.\n"
                        "4. SCREEN & DISPLAY DETAILS: If a monitor, television, computer screen, or presentation is visible, describe its exact contents, layout, open tabs, subscriber counts, and UI elements.\n"
                        "5. SONG & MEDIA TITLES: If song titles, music credits, or video titles are visible, state them verbatim.\n\n"
                        "Output format for EACH frame:\n"
                        "[FRAME: <timestamp>s]\n"
                        "Headline: <One concise sentence summarizing the main visual scene, slide topic, or action>\n"
                        "Details: <2-3 sentences describing what is physically visible in the frame>\n"
                        "Visible Text & Names: <List all visible text, slide titles, bullet points, subscriber counts, and names verbatim. If none, write 'None'>\n\n"
                        "Example:\n"
                        "[FRAME: 24.0s]\n"
                        "Headline: Scene shows key visual elements and activities in the video frame.\n"
                        "Details: Visual keyframe captured from the video showing scene context and physical setting.\n"
                        "Visible Text & Names: None"
                    )

                    batch_desc = None
                    for model_name in candidate_models:
                        for attempt in range(3):
                            try:
                                model = genai.GenerativeModel(model_name)
                                response = await asyncio.wait_for(
                                    asyncio.to_thread(model.generate_content, [prompt] + images),
                                    timeout=45.0
                                )
                                if response and response.text:
                                    batch_desc = response.text.strip()
                                    break
                            except Exception as err:
                                err_str = str(err).lower()
                                if "429" in err_str or "quota" in err_str or "rate limit" in err_str:
                                    logger.warning(f"Batch {batch_idx+1} model {model_name} rate limited (429). Retrying in 4s (attempt {attempt+1}/3)...")
                                    await asyncio.sleep(4.0)
                                else:
                                    if "401" in err_str or "invalid authentication" in err_str:
                                        logger.warning(f"Gemini API key authentication failed (401). Check GEMINI_API_KEY in .env.")
                                    logger.warning(f"Batch {batch_idx+1} vision model {model_name} failed: {err}")
                                    break
                        if batch_desc:
                            break

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
                        block_info = frame_map[nearest_ts]
                        observations.append(
                            VisualObservation(
                                timestamp=s.timestamp,
                                description=block_info["description"],
                                ocr_text=block_info.get("ocr_text", "")
                            )
                        )
                    return observations
            except Exception as e:
                logger.error(f"Batched Gemini visual perception failed: {e}. Falling back to visual frame analysis.")

        # Computer Vision & Offline Fallback Baseline
        return [
            VisualObservation(
                timestamp=s.timestamp,
                description=self._cv_frame_description(s),
                ocr_text=""
            )
            for s in frame_samples
        ]

    def _parse_frame_blocks(self, text: str, selected_samples: List[FrameSample]) -> Dict[float, Dict[str, str]]:
        """Parse Gemini output into timestamp -> {description, ocr_text} map including on-screen text and names."""
        result: Dict[float, Dict[str, str]] = {}

        pattern = re.compile(r'\[FRAME:\s*([0-9.]+)s?\]\s*(.*?)(?=\[FRAME:|\Z)', re.DOTALL | re.IGNORECASE)
        matches = list(pattern.finditer(text))

        if matches:
            for m in matches:
                try:
                    ts = float(m.group(1))
                    body = m.group(2).strip()

                    head_m = re.search(r'Headline:\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
                    det_m = re.search(r'Details:\s*(.+?)(?:\n\s*(?:Visible Text|Names)|\Z)', body, re.DOTALL | re.IGNORECASE)
                    text_m = re.search(r'(?:Visible Text & Names|Visible Text|Names|OCR):\s*(.+)', body, re.DOTALL | re.IGNORECASE)

                    parts = []
                    ocr_val = ""
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
                            ocr_val = vis_names

                    full_desc = "\n".join(parts) if parts else body
                    result[ts] = {
                        "description": full_desc,
                        "ocr_text": ocr_val
                    }
                except Exception:
                    continue

        # If regex didn't find [FRAME: ...] markers, split by chronological paragraphs
        if not result:
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 30]
            for idx, s in enumerate(selected_samples):
                desc_text = paragraphs[idx] if idx < len(paragraphs) else (paragraphs[-1] if paragraphs else text[:300])
                result[s.timestamp] = {
                    "description": desc_text,
                    "ocr_text": ""
                }

        return result

    def _cv_frame_description(self, sample: FrameSample) -> str:
        """Computer Vision fallback analysis using OpenCV and PIL image properties."""
        ts = sample.timestamp
        img_path = Path(sample.image_path) if sample.image_path else None
        
        if img_path and img_path.exists():
            try:
                import cv2
                import numpy as np
                img_bgr = cv2.imread(str(img_path))
                if img_bgr is not None:
                    h, w, _ = img_bgr.shape
                    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
                    brightness = float(np.mean(gray))
                    edges = cv2.Canny(gray, 100, 200)
                    edge_density = float(np.mean(edges > 0))

                    lighting = (
                        "Night vision or low-light scene setting" if brightness < 70
                        else ("High-brightness presentation screen or brightly lit environment" if brightness > 175
                        else "Daytime outdoor ambient illumination")
                    )
                    complexity = (
                        "High visual detail and dynamic activity in frame" if edge_density > 0.05
                        else "Moderate visual structures and background elements"
                    )
                    return (
                        f"Headline: Keyframe visual capture at {ts:.1f}s.\n"
                        f"Details: Scene dimensions: {w}x{h}px. {lighting} with {complexity.lower()}."
                    )
            except Exception as e:
                logger.debug(f"CV analysis error: {e}")

        return f"Headline: Visual frame at {ts:.1f}s.\nDetails: Keyframe image sequence captured from video timeline."
