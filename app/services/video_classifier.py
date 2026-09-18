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
        summary: Optional[str] = None,
        duration_seconds: float = 0.0
    ) -> VideoClassificationResult:
        """Classify video type using multimodal perception signals."""
        fn_lower = filename.lower()
        total_transcript_words = sum(len(t.split()) for t in transcripts)
        learning_keywords = ["lecture", "tutorial", "presentation", "course", "webinar", "lesson", "education", "training", "saksham", "moodle"]
        has_learning_filename = any(kw in fn_lower for kw in learning_keywords)

        # Immediate rule 1: Videos under 60 seconds without explicit learning title are observational clips
        if 0 < duration_seconds < 60.0 and not has_learning_filename:
            return VideoClassificationResult(
                video_type="observational",
                label="Observational / Surveillance",
                confidence=0.96,
                reason=f"Short clip ({int(round(duration_seconds))}s) lacking structured educational course content."
            )

        # Immediate rule 2: Silent / audio-less videos with zero spoken words are observational footage
        if total_transcript_words == 0 and not has_learning_filename:
            return VideoClassificationResult(
                video_type="observational",
                label="Observational / Surveillance",
                confidence=0.95,
                reason="No spoken dialogue or audio transcript detected in video stream."
            )

        # 1. Attempt Gemini AI-driven classification if available
        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                ai_result = await self._classify_with_gemini(
                    filename, transcripts, visual_descriptions, ocr_texts, summary, duration_seconds
                )
                if ai_result:
                    return ai_result
            except Exception as e:
                logger.warning(f"AI classification failed: {e}. Falling back to deterministic rules.")

        # 2. Robust Deterministic Rule-Based Classification
        return self._classify_deterministic(
            filename, transcripts, visual_descriptions, ocr_texts, summary, duration_seconds
        )

    async def _classify_with_gemini(
        self,
        filename: str,
        transcripts: List[str],
        visual_descriptions: List[str],
        ocr_texts: List[str],
        summary: Optional[str] = None,
        duration_seconds: float = 0.0
    ) -> Optional[VideoClassificationResult]:
        """Perform multimodal semantic classification with Gemini LLM."""
        transcript_sample = " ".join(transcripts[:12])[:1200]
        visual_sample = " | ".join(visual_descriptions[:8])[:1000]
        ocr_sample = " | ".join([t for t in ocr_texts if t][:8])[:600]

        prompt = (
            "You are an expert video content classifier. Classify the following video into EXACTLY ONE of two categories:\n"
            "1. 'knowledge': Learning / Knowledge Content (lectures, tutorials, presentations, educational content, meetings, demos, interviews, webinars, discussions)\n"
            "2. 'observational': Observational / Surveillance (CCTV footage, surveillance, security cameras, dashcam, traffic monitoring, static facility cameras, silent raw footage, empty spaces, short clips under 1 min without voice)\n\n"
            "IMPORTANT RULES:\n"
            "- Any video with 'cctv', 'surveillance', 'security', 'cam', 'gate', or 'corridor' in the filename MUST be classified as 'observational'.\n"
            "- Any video with NO audio/speech transcript or under 60 seconds without explicit presentation content MUST be classified as 'observational'.\n\n"
            f"Filename: {filename}\n"
            f"Duration: {duration_seconds:.1f} seconds\n"
            f"Summary: {summary or 'N/A'}\n"
            f"Audio Transcript: {transcript_sample or 'No speech/audio detected'}\n"
            f"Visual Descriptions: {visual_sample or 'N/A'}\n"
            f"On-Screen OCR Text: {ocr_sample or 'None'}\n\n"
            "Respond in EXACTLY this format:\n"
            "TYPE: [knowledge OR observational]\n"
            "CONFIDENCE: [0.70 - 1.00]\n"
            "REASON: [1-2 sentences explaining why based on audio, duration, visual, and content signals]"
        )

        for model_name in [settings.GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
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
        summary: Optional[str] = None,
        duration_seconds: float = 0.0
    ) -> VideoClassificationResult:
        """Deterministic heuristic classifier examining keywords, audio presence, duration, and filenames."""
        fn_lower = filename.lower()
        total_transcript_words = sum(len(t.split()) for t in transcripts)

        # 1. High-Priority Filename Pattern Rules for CCTV / Surveillance
        cctv_filename_keywords = [
            "cctv", "surveillance", "security", "dashcam", "traffic", "gate",
            "corridor", "hallway", "parking", "patrol", "entrance", "exit", "cam"
        ]
        if any(kw in fn_lower for kw in cctv_filename_keywords):
            return VideoClassificationResult(
                video_type="observational",
                label="Observational / Surveillance",
                confidence=0.98,
                reason=f"Filename '{filename}' contains CCTV or surveillance camera indicators."
            )

        # 2. Duration & Audio Rules
        learning_filename_keywords = [
            "lecture", "tutorial", "presentation", "course", "webinar",
            "lesson", "education", "training", "saksham", "moodle", "guide"
        ]
        has_learning_filename = any(kw in fn_lower for kw in learning_filename_keywords)

        if 0 < duration_seconds < 60.0 and not has_learning_filename:
            return VideoClassificationResult(
                video_type="observational",
                label="Observational / Surveillance",
                confidence=0.96,
                reason=f"Video duration ({int(round(duration_seconds))}s) is under 1 minute without educational indicators."
            )

        combined_text = (
            f"{filename} "
            f"{summary or ''} "
            f"{' '.join(transcripts)} "
            f"{' '.join(visual_descriptions)} "
            f"{' '.join(ocr_texts)}"
        ).lower()

        observational_terms = [
            "cctv", "surveillance", "security camera", "security footage", "dashcam",
            "traffic camera", "parking lot", "entrance gate", "corridor", "camera",
            "cam1", "cam2", "monitoring", "facility camera", "night vision",
            "patrol", "perimeter", "stairwell camera", "static camera", "overhead", "footage"
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

        if total_transcript_words > 30:
            know_score += 4
        elif total_transcript_words == 0:
            obs_score += 4

        if obs_score >= know_score or (total_transcript_words == 0 and not has_learning_filename):
            return VideoClassificationResult(
                video_type="observational",
                label="Observational / Surveillance",
                confidence=0.92,
                reason="Absence of spoken dialogue or presence of observational visual markers."
            )
        else:
            return VideoClassificationResult(
                video_type="knowledge",
                label="Learning / Knowledge Content",
                confidence=0.88,
                reason="Instructional spoken dialogue or educational presentation topics detected."
            )


video_classifier = VideoClassifier()
