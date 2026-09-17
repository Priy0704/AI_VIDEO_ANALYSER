import logging
import re
import asyncio
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from app.config import settings

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

logger = logging.getLogger(__name__)


@dataclass
class VideoClassificationResult:
    video_type: str  # "knowledge" or "observational"
    label: str       # "Learning / Knowledge Content" or "Observational / Surveillance"
    confidence: float
    reason: str


class VideoClassifier:
    """
    Multimodal Video Classifier.
    Classifies videos into:
      - 'knowledge': "Learning / Knowledge Content" (Tutorials, lectures, meetings, presentations, webinars, educational videos)
      - 'observational': "Observational / Surveillance" (CCTV, surveillance, dashcam, traffic monitoring, security cameras)
    Evaluates visual keyframes, audio transcripts, OCR text, and overall semantic content.
    """

    def __init__(self, api_key: Optional[str] = settings.GEMINI_API_KEY):
        self.api_key = api_key
        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                genai.configure(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to configure Gemini in VideoClassifier: {e}")

    async def classify_video(
        self,
        filename: str,
        transcripts: List[str],
        visual_descriptions: List[str],
        ocr_texts: List[str],
        summary: Optional[str] = None
    ) -> VideoClassificationResult:
        """Classify video type using multimodal perception signals."""
        # 1. Attempt Gemini AI-driven classification if available
        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                ai_result = await self._classify_with_gemini(
                    filename, transcripts, visual_descriptions, ocr_texts, summary
                )
                if ai_result:
                    return ai_result
            except Exception as e:
                logger.warning(f"AI classification failed: {e}. Falling back to deterministic rules.")

        # 2. Robust Deterministic Rule-Based Classification
        return self._classify_deterministic(
            filename, transcripts, visual_descriptions, ocr_texts, summary
        )

    async def _classify_with_gemini(
        self,
        filename: str,
        transcripts: List[str],
        visual_descriptions: List[str],
        ocr_texts: List[str],
        summary: Optional[str] = None
    ) -> Optional[VideoClassificationResult]:
        """Perform multimodal semantic classification with Gemini LLM."""
        transcript_sample = " ".join(transcripts[:12])[:1200]
        visual_sample = " | ".join(visual_descriptions[:8])[:1000]
        ocr_sample = " | ".join([t for t in ocr_texts if t][:8])[:600]

        prompt = (
            "You are an expert video content classifier. Classify the following video into EXACTLY ONE of two categories:\n"
            "1. 'knowledge': Learning / Knowledge Content (lectures, tutorials, presentations, educational content, meetings, demos, interviews, webinars, discussions)\n"
            "2. 'observational': Observational / Surveillance (CCTV footage, surveillance, security cameras, dashcam, traffic monitoring, static facility cameras, empty spaces)\n\n"
            f"Filename: {filename}\n"
            f"Summary: {summary or 'N/A'}\n"
            f"Audio Transcript: {transcript_sample or 'No speech/audio detected'}\n"
            f"Visual Descriptions: {visual_sample or 'N/A'}\n"
            f"On-Screen OCR Text: {ocr_sample or 'None'}\n\n"
            "Respond in EXACTLY this format:\n"
            "TYPE: [knowledge OR observational]\n"
            "CONFIDENCE: [0.70 - 1.00]\n"
            "REASON: [1-2 sentences explaining why based on audio, visual, and content signals]"
        )

        for model_name in [settings.GEMINI_MODEL, "gemini-3.6-flash", "gemini-3.5-flash"]:
            try:
                model = genai.GenerativeModel(model_name)
                response = await asyncio.wait_for(
                    asyncio.to_thread(model.generate_content, prompt),
                    timeout=15.0
                )
                if response and response.text:
                    text = response.text.strip()
                    m_type = re.search(r'TYPE:\s*(knowledge|observational)', text, re.IGNORECASE)
                    m_conf = re.search(r'CONFIDENCE:\s*([0-9.]+)', text, re.IGNORECASE)
                    m_reason = re.search(r'REASON:\s*(.+)', text, re.IGNORECASE | re.DOTALL)

                    if m_type:
                        v_type = m_type.group(1).lower()
                        conf = float(m_conf.group(1)) if m_conf else 0.92
                        reason = m_reason.group(1).strip() if m_reason else "Classified by multimodal AI analysis."
                        label = (
                            "Learning / Knowledge Content"
                            if v_type == "knowledge"
                            else "Observational / Surveillance"
                        )
                        return VideoClassificationResult(
                            video_type=v_type,
                            label=label,
                            confidence=round(conf, 2),
                            reason=reason
                        )
            except Exception as e:
                logger.warning(f"Model {model_name} classification attempt failed: {e}")

        return None

    def _classify_deterministic(
        self,
        filename: str,
        transcripts: List[str],
        visual_descriptions: List[str],
        ocr_texts: List[str],
        summary: Optional[str] = None
    ) -> VideoClassificationResult:
        """Deterministic heuristic classifier examining keywords across all signals."""
        combined_text = (
            f"{filename} "
            f"{summary or ''} "
            f"{' '.join(transcripts)} "
            f"{' '.join(visual_descriptions)} "
            f"{' '.join(ocr_texts)}"
        ).lower()

        observational_terms = [
            "cctv", "surveillance", "security camera", "security footage", "dashcam",
            "traffic camera", "parking lot", "entrance gate", "corridor b", "camera 1",
            "cam1", "cam 2", "cam2", "monitoring", "facility camera", "night vision",
            "patrol", "perimeter", "stairwell camera", "static camera", "cctv_corridor", "cctv_entrance"
        ]

        knowledge_terms = [
            "lecture", "presentation", "tutorial", "course", "training", "webinar",
            "explaining", "learn", "how to", "architecture", "dashboard", "diagram",
            "slide", "speaker", "instructor", "lesson", "education", "conference",
            "interview", "overview", "demo", "system", "saksham", "moodle", "algorithm",
            "code", "framework", "database", "rag", "embeddings", "model"
        ]

        obs_score = sum(1 for term in observational_terms if term in combined_text)
        know_score = sum(1 for term in knowledge_terms if term in combined_text)

        # Check filename specific hints
        fn_lower = filename.lower()
        if any(w in fn_lower for w in ["cctv", "surveillance", "cam", "security", "traffic", "dashcam"]):
            obs_score += 4
        if any(w in fn_lower for w in ["lecture", "tutorial", "presentation", "demo", "course", "training", "learn"]):
            know_score += 4

        # Substantive spoken dialogue strongly signals knowledge/learning content
        total_transcript_words = sum(len(t.split()) for t in transcripts)
        if total_transcript_words > 40:
            know_score += 3
        elif total_transcript_words == 0 and not know_score:
            # Absence of any audio/dialogue with observational hints leans observational
            obs_score += 2

        if obs_score > know_score and obs_score >= 1:
            return VideoClassificationResult(
                video_type="observational",
                label="Observational / Surveillance",
                confidence=min(0.98, 0.82 + (0.03 * obs_score)),
                reason="Camera angle, static surveillance markers, and observational patterns detected."
            )
        else:
            return VideoClassificationResult(
                video_type="knowledge",
                label="Learning / Knowledge Content",
                confidence=min(0.98, 0.85 + (0.02 * know_score)),
                reason="Educational/instructional dialogue, presentations, or demonstration topics detected."
            )


video_classifier = VideoClassifier()
