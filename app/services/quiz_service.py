import logging
import json
import re
import math
import asyncio
from typing import List, Dict, Optional, Tuple, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status

from app.config import settings
from app.db.models import (
    Video,
    VideoSegment,
    Quiz,
    QuizQuestion,
    QuizAttempt,
    SelfTestAttempt
)
from app.schemas.quiz import (
    QuizResponse,
    QuizQuestionResponse,
    QuestionEvaluationItem,
    TopicPerformance,
    QuizEvaluationResponse,
    SelfTestResponse
)

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

logger = logging.getLogger(__name__)


def format_seconds_to_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS format."""
    total_sec = max(0, int(round(seconds)))
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins:02d}:{secs:02d}"


def sanitize_question_text(q_text: str, topic: str = "this video") -> str:
    """Ensure question stems are direct domain conceptual questions without timestamp noise or awkward quotes."""
    if not q_text:
        return f"What primary concept or capability is demonstrated regarding {topic}?"

    q = q_text.strip()
    q = re.sub(r'according to the video (?:at [^,\.\?\n]+)?', '', q, flags=re.IGNORECASE)
    q = re.sub(r'highlighted in the video (?:at [^,\.\?\n]+)?', '', q, flags=re.IGNORECASE)
    q = re.sub(r'based on the video (?:at [^,\.\?\n]+)?', '', q, flags=re.IGNORECASE)
    q = re.sub(r'(?:at|in|between|during)?\s*\b\d{1,2}:\d{2}\s*(?:–|-|to)\s*\d{1,2}:\d{2}\b', '', q, flags=re.IGNORECASE)
    q = re.sub(r'the footage is unrelated to [^\.\?\n]+', f'the topic covers {topic}', q, flags=re.IGNORECASE)
    q = re.sub(r'\s+', ' ', q).strip()

    if q.startswith(',') or q.startswith(':') or q.startswith('-'):
        q = q[1:].strip()

    if not q or len(q) < 10 or q.lower().startswith('what key information is') or q.lower().startswith('what key concept is'):
        q = f"What primary concept or capability is demonstrated regarding {topic}?"

    if not q.endswith('?') and not q.endswith('.'):
        q += '?'

    return q


class QuizService:
    """
    Core service for Video Knowledge Assessment & Learning Loop:
    1. Grounded Quiz Generation (from actual video transcripts, visuals, OCR).
    2. Interactive Quiz Evaluation & Topic-wise Diagnosis.
    3. Self-Test / 'Test My Understanding' Written Evaluation.
    4. Smart Relearn Timestamp Linking.
    """

    def __init__(self, api_key: Optional[str] = settings.GEMINI_API_KEY):
        self.api_key = api_key
        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                genai.configure(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Gemini config failed in QuizService: {e}")

    async def generate_quiz(
        self,
        db: AsyncSession,
        video: Video,
        num_questions: int = 5,
        difficulty: str = "medium",
        question_type: str = "mixed"
    ) -> Quiz:
        """
        Generates a quiz grounded strictly in the video's content.
        Raises 400 if the video is classified as observational / surveillance.
        """
        if getattr(video, "video_type", "knowledge") == "observational":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Quiz generation is disabled for observational/surveillance footage ({video.filename}). "
                    "Quizzes can only be generated for learning and knowledge-based videos."
                )
            )

        # Retrieve video segments
        stmt = select(VideoSegment).where(VideoSegment.video_id == video.id).order_by(VideoSegment.start_time)
        segments = (await db.execute(stmt)).scalars().all()
        if not segments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video has no processed segments available to generate a quiz."
            )

        # 1. Attempt AI Generation with Gemini
        generated_data = None
        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                generated_data = await self._generate_with_gemini(
                    video=video,
                    segments=segments,
                    num_questions=num_questions,
                    difficulty=difficulty,
                    question_type=question_type
                )
            except Exception as e:
                logger.warning(f"AI Quiz Generation failed: {e}. Falling back to deterministic generation.")

        # 2. Deterministic Grounded Fallback
        if not generated_data:
            generated_data = self._generate_deterministic(
                video=video,
                segments=segments,
                num_questions=num_questions,
                difficulty=difficulty,
                question_type=question_type
            )

        # Save Quiz to DB
        quiz = Quiz(
            video_id=video.id,
            title=f"Knowledge Quiz: {video.filename}",
            difficulty=difficulty,
            question_type=question_type,
            total_questions=len(generated_data)
        )
        db.add(quiz)
        await db.flush()

        for idx, q_data in enumerate(generated_data, start=1):
            question = QuizQuestion(
                quiz_id=quiz.id,
                order_num=idx,
                question=q_data["question"],
                question_type=q_data["question_type"],
                options=q_data.get("options"),
                correct_answer=q_data["correct_answer"],
                explanation=q_data.get("explanation", "Verified from video content."),
                topic=q_data.get("topic", "General Concept"),
                relevant_timestamp_start=float(q_data.get("relevant_timestamp_start", 0.0)),
                relevant_timestamp_end=float(q_data.get("relevant_timestamp_end", 10.0)),
                relevant_timestamp_formatted=q_data.get("relevant_timestamp_formatted", "00:00–00:10")
            )
            db.add(question)

        await db.commit()
        stmt = select(Quiz).where(Quiz.id == quiz.id)
        refreshed_quiz = (await db.execute(stmt)).scalar_one()
        return refreshed_quiz

    async def _generate_with_gemini(
        self,
        video: Video,
        segments: List[VideoSegment],
        num_questions: int,
        difficulty: str,
        question_type: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate grounded questions using Gemini JSON mode."""
        # Build segment context with exact timestamps
        context_lines = []
        step = max(1, len(segments) // min(15, len(segments)))
        for seg in segments[::step][:15]:
            t_str = f"{format_seconds_to_timestamp(seg.start_time)} - {format_seconds_to_timestamp(seg.end_time)}"
            content = f"{seg.transcript_text} {seg.visual_description} {seg.ocr_text}".strip()
            if content:
                context_lines.append(f"[{t_str}]: {content[:200]}")

        context_str = "\n".join(context_lines)

        prompt = (
            f"You are a professional educational assessor creating an assessment for the video '{video.filename}'.\n"
            f"Generate a grounded {difficulty}-difficulty quiz of exactly {num_questions} questions.\n"
            f"Preferred question type: {question_type} (options: 'mcq', 'true_false', 'short_answer', or 'mixed').\n\n"
            "STRICT QUESTION & GROUNDING RULES:\n"
            "1. UNDERSTAND THE VIDEO CONTENT and frame natural, meaningful, conceptual educational questions (e.g., 'What is RAG?', 'What primary capability is demonstrated?', 'Which dataset is referenced?').\n"
            "2. NEVER create awkward fill-in-the-blank or raw quotation questions like 'According to the video at MM:SS, the content addresses: \"It will reply...\"'.\n"
            "3. For MCQ questions, provide 4 clear, plausible, distinct conceptual options (A, B, C, D) and specify the exact correct option text. DO NOT use raw truncated transcript fragments as options.\n"
            "4. For True/False questions, provide options ['True', 'False'] and specify 'True' or 'False'.\n"
            "5. For Short Answer questions, options must be null, and correct_answer must be a clear 1-2 sentence reference answer.\n"
            "6. Include a concise topic name (e.g. 'RAG', 'Architecture', 'UI Features') and an explanation.\n\n"
            f"VIDEO EVIDENCE CONTEXT:\n{context_str}\n\n"
            "Output MUST be valid JSON list of objects matching this schema:\n"
            "[\n"
            "  {\n"
            "    \"question\": \"What is...?\",\n"
            "    \"question_type\": \"mcq\" | \"true_false\" | \"short_answer\",\n"
            "    \"options\": [\"Option 1\", \"Option 2\", \"Option 3\", \"Option 4\"] or null,\n"
            "    \"correct_answer\": \"Option 1\",\n"
            "    \"explanation\": \"Because...\",\n"
            "    \"topic\": \"Topic Name\",\n"
            "    \"relevant_timestamp_start\": 12.0,\n"
            "    \"relevant_timestamp_end\": 24.0,\n"
            "    \"relevant_timestamp_formatted\": \"00:12 - 00:24\"\n"
            "  }\n"
            "]"
        )

        for model_name in [settings.GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
            try:
                model = genai.GenerativeModel(model_name)
                res = await asyncio.wait_for(
                    asyncio.to_thread(model.generate_content, prompt),
                    timeout=30.0
                )
                if res and res.text:
                    clean = res.text.strip()
                    if "```json" in clean:
                        clean = clean.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean:
                        clean = clean.split("```")[1].split("```")[0].strip()
                    parsed = json.loads(clean)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        for item in parsed:
                            if isinstance(item, dict) and "question" in item:
                                item["question"] = sanitize_question_text(item["question"], item.get("topic", "this video"))
                        return parsed[:num_questions]
            except Exception as e:
                logger.warning(f"Model {model_name} quiz generation error: {e}")

        return None

    def _generate_deterministic(
        self,
        video: Video,
        segments: List[VideoSegment],
        num_questions: int,
        difficulty: str,
        question_type: str
    ) -> List[Dict[str, Any]]:
        """Deterministic fallback question generator extracting grounded facts from segments."""
        questions: List[Dict[str, Any]] = []

        # Find segments with substantive transcript or OCR
        informative_segments = [
            s for s in segments
            if (s.transcript_text and len(s.transcript_text.split()) >= 4)
            or (s.ocr_text and len(s.ocr_text) > 5)
            or (s.visual_description and len(s.visual_description) > 15)
        ]
        if not informative_segments:
            informative_segments = segments

        step = max(1, len(informative_segments) // max(1, num_questions))

        # While we have fewer questions than needed, repeat segments with different question angles
        idx = 0
        while len(questions) < num_questions and informative_segments:
            seg = informative_segments[idx % len(informative_segments)]
            idx += 1
            t_start = seg.start_time
            t_end = seg.end_time
            t_fmt = f"{format_seconds_to_timestamp(t_start)}–{format_seconds_to_timestamp(t_end)}"

            # Decide question type
            if question_type == "mcq":
                curr_type = "mcq"
            elif question_type == "true_false":
                curr_type = "true_false"
            elif question_type == "short_answer":
                curr_type = "short_answer"
            else:
                # Mixed
                types_cycle = ["mcq", "true_false", "short_answer"]
                curr_type = types_cycle[len(questions) % len(types_cycle)]

            text_body = seg.transcript_text or seg.ocr_text or seg.visual_description or f"Video overview at {t_fmt}"
            clean_text = text_body.strip()

            # Extract clean summary sentence without raw quotes
            clean_summary = clean_text
            if len(clean_text) > 90:
                first_sent = clean_text.split('.')[0].strip()
                clean_summary = first_sent if len(first_sent) >= 15 else clean_text[:90].strip()

            # Derive topic
            topic = "General Concept"
            for kw, top in [
                ("saksham", "Saksham LMS Platform"),
                ("moodle", "Moodle E-Learning"),
                ("dashboard", "System Dashboard"),
                ("subscriber", "Channel Metrics"),
                ("rag", "Retrieval Augmented Generation"),
                ("embedding", "Embeddings & Vector Search"),
                ("presentation", "Presentation Overview"),
                ("person", "Visual Identification"),
                ("screen", "On-Screen Content")
            ]:
                if kw in clean_text.lower() or kw in video.filename.lower():
                    topic = top
                    break

            if curr_type == "true_false":
                is_true = (len(questions) % 2 == 0)
                if is_true:
                    q_text = f"Does the video address key principles of {topic}?"
                    ans = "True"
                    expl = f"Verified directly from the video recording at {t_fmt}."
                else:
                    q_text = f"Does the video focus on unrelated external topics rather than {topic}?"
                    ans = "False"
                    expl = f"Incorrect; the footage at {t_fmt} specifically addresses {topic}."

                questions.append({
                    "question": q_text,
                    "question_type": "true_false",
                    "options": ["True", "False"],
                    "correct_answer": ans,
                    "explanation": expl,
                    "topic": topic,
                    "relevant_timestamp_start": t_start,
                    "relevant_timestamp_end": t_end,
                    "relevant_timestamp_formatted": t_fmt
                })

            elif curr_type == "short_answer":
                q_text = f"Explain the primary mechanism or core workflow regarding {topic}."
                ans = clean_summary
                questions.append({
                    "question": q_text,
                    "question_type": "short_answer",
                    "options": None,
                    "correct_answer": ans,
                    "explanation": f"The video demonstrates: '{ans}' at {t_fmt}.",
                    "topic": topic,
                    "relevant_timestamp_start": t_start,
                    "relevant_timestamp_end": t_end,
                    "relevant_timestamp_formatted": t_fmt
                })

            else:  # mcq
                q_text = f"What primary concept or function is demonstrated regarding {topic}?"
                correct_opt = f"Demonstrates {clean_summary.lower() if not clean_summary.lower().startswith('demonstrates') else clean_summary.lower()}"
                if len(correct_opt) > 120:
                    correct_opt = correct_opt[:117] + "..."

                distractor_1 = f"Explores unrelated historical background unrelated to {topic.lower()}"
                distractor_2 = f"No substantive features or information are presented during this section"
                distractor_3 = f"Presents claims contrary to the video demonstration"

                opts = [correct_opt, distractor_1, distractor_2, distractor_3]
                questions.append({
                    "question": q_text,
                    "question_type": "mcq",
                    "options": opts,
                    "correct_answer": correct_opt,
                    "explanation": f"Directly observed in the video at {t_fmt}.",
                    "topic": topic,
                    "relevant_timestamp_start": t_start,
                    "relevant_timestamp_end": t_end,
                    "relevant_timestamp_formatted": t_fmt
                })

            if len(questions) >= num_questions:
                break

        return questions[:num_questions]

    async def evaluate_quiz(
        self,
        db: AsyncSession,
        quiz: Quiz,
        answers: Dict[str, str]
    ) -> QuizEvaluationResponse:
        """
        Evaluates submitted quiz answers, diagnoses weak/strong concepts,
        generates smart relearn recommendations with timestamps, and records the attempt.
        """
        # Load questions for this quiz
        stmt = select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.order_num)
        questions = (await db.execute(stmt)).scalars().all()

        total_questions = len(questions)
        evaluated_items: List[QuestionEvaluationItem] = []
        topic_map: Dict[str, Dict[str, int]] = {}  # topic -> {"correct": int, "total": int}

        total_score = 0.0

        for q in questions:
            user_ans = answers.get(q.id, "").strip()
            topic = q.topic or "General"
            if topic not in topic_map:
                topic_map[topic] = {"correct": 0, "total": 0}
            topic_map[topic]["total"] += 1

            is_unanswered = (user_ans == "")
            is_correct = False
            q_score = 0.0

            if not is_unanswered:
                if q.question_type in ["mcq", "true_false"]:
                    # 1. Exact or normalized match
                    clean_u = re.sub(r'[^a-zA-Z0-9]', '', user_ans).lower()
                    clean_c = re.sub(r'[^a-zA-Z0-9]', '', q.correct_answer).lower()
                    if clean_u == clean_c or user_ans.strip().lower() == q.correct_answer.strip().lower():
                        is_correct = True
                        q_score = 1.0
                    else:
                        # 2. Check if user_ans is an index (0, 1, 2, 3) or letter (A, B, C, D) mapping to q.options
                        opts = q.options or []
                        if isinstance(opts, list) and len(opts) > 0:
                            u_text = None
                            if user_ans.isdigit() and 0 <= int(user_ans) < len(opts):
                                u_text = opts[int(user_ans)]
                            elif len(user_ans) == 1 and user_ans.upper() in ['A', 'B', 'C', 'D', 'E', 'F']:
                                idx = ord(user_ans.upper()) - 65
                                if 0 <= idx < len(opts):
                                    u_text = opts[idx]
                            
                            if u_text:
                                clean_ut = re.sub(r'[^a-zA-Z0-9]', '', u_text).lower()
                                if clean_ut == clean_c or u_text.strip().lower() == q.correct_answer.strip().lower():
                                    is_correct = True
                                    q_score = 1.0
                else:
                    # Short Answer semantic evaluation
                    is_correct, q_score = await self._evaluate_short_answer(
                        question=q.question,
                        user_answer=user_ans,
                        reference_answer=q.correct_answer,
                        explanation=q.explanation
                    )

            if is_correct:
                topic_map[topic]["correct"] += 1
                total_score += q_score

            evaluated_items.append(
                QuestionEvaluationItem(
                    question_id=q.id,
                    order_num=q.order_num,
                    question=q.question,
                    question_type=q.question_type,
                    options=q.options,
                    user_answer=user_ans if user_ans else "(Unanswered)",
                    correct_answer=q.correct_answer,
                    is_correct=is_correct,
                    is_unanswered=is_unanswered,
                    score=round(q_score, 2),
                    topic=topic,
                    explanation=q.explanation or "Grounded in video evidence.",
                    relevant_timestamp_formatted=q.relevant_timestamp_formatted,
                    relevant_timestamp_start=q.relevant_timestamp_start,
                    relevant_timestamp_end=q.relevant_timestamp_end
                )
            )

        correct_count = sum(1 for item in evaluated_items if item.is_correct)
        incorrect_count = sum(1 for item in evaluated_items if not item.is_correct and not item.is_unanswered)
        unanswered_count = sum(1 for item in evaluated_items if item.is_unanswered)

        percentage = round((total_score / max(1.0, float(total_questions))) * 100.0, 1)

        # Diagnose topic performance (Strong >= 75%, Needs Improvement < 75%)
        topic_performance: List[TopicPerformance] = []
        strong_areas: List[str] = []
        needs_improvement: List[str] = []

        for t_name, t_data in topic_map.items():
            t_pct = round((t_data["correct"] / max(1, t_data["total"])) * 100.0, 1)
            status_label = "Strong Area" if t_pct >= 75.0 else "Needs Improvement"
            if t_pct >= 75.0:
                strong_areas.append(t_name)
            else:
                needs_improvement.append(t_name)

            topic_performance.append(
                TopicPerformance(
                    topic=t_name,
                    correct_count=t_data["correct"],
                    total_count=t_data["total"],
                    percentage=t_pct,
                    status=status_label
                )
            )

        # Save Attempt in Database
        attempt = QuizAttempt(
            quiz_id=quiz.id,
            video_id=quiz.video_id,
            total_score=round(total_score, 2),
            max_score=float(total_questions),
            percentage=percentage,
            correct_count=correct_count,
            incorrect_count=incorrect_count,
            unanswered_count=unanswered_count,
            answers=answers,
            evaluation_data={
                "strong_areas": strong_areas,
                "needs_improvement": needs_improvement,
                "topic_performance": [tp.dict() for tp in topic_performance],
                "evaluated_items": [ei.dict() for ei in evaluated_items]
            }
        )
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)

        return QuizEvaluationResponse(
            attempt_id=attempt.id,
            quiz_id=quiz.id,
            video_id=quiz.video_id,
            total_score=round(total_score, 2),
            max_score=float(total_questions),
            percentage=percentage,
            correct_count=correct_count,
            incorrect_count=incorrect_count,
            unanswered_count=unanswered_count,
            strong_areas=strong_areas,
            needs_improvement=needs_improvement,
            topic_performance=topic_performance,
            questions=evaluated_items,
            created_at=attempt.created_at
        )

    async def _evaluate_short_answer(
        self,
        question: str,
        user_answer: str,
        reference_answer: str,
        explanation: Optional[str] = None
    ) -> Tuple[bool, float]:
        """Evaluate a short answer response using Gemini or semantic token comparison."""
        if not user_answer or len(user_answer.strip()) < 2:
            return False, 0.0

        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                prompt = (
                    "Evaluate a student's answer against the reference answer strictly based on factual correctness.\n"
                    f"Question: {question}\n"
                    f"Reference Correct Answer: {reference_answer}\n"
                    f"Student Answer: {user_answer}\n\n"
                    "Respond with:\n"
                    "SCORE: [0.0 to 1.0]\n"
                    "IS_CORRECT: [true or false]"
                )
                for model_name in [settings.GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
                    try:
                        model = genai.GenerativeModel(model_name)
                        res = await asyncio.wait_for(
                            asyncio.to_thread(model.generate_content, prompt),
                            timeout=10.0
                        )
                        if res and res.text:
                            m_score = re.search(r'SCORE:\s*([0-9.]+)', res.text, re.IGNORECASE)
                            m_correct = re.search(r'IS_CORRECT:\s*(true|false)', res.text, re.IGNORECASE)
                            score_val = float(m_score.group(1)) if m_score else 0.0
                            is_corr = (m_correct.group(1).lower() == "true") if m_correct else (score_val >= 0.6)
                            return is_corr, min(1.0, max(0.0, score_val))
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"AI short answer evaluation error: {e}")

        # Deterministic keyword token overlap
        ref_words = set(re.findall(r'\b[a-zA-Z0-9]{3,}\b', reference_answer.lower()))
        usr_words = set(re.findall(r'\b[a-zA-Z0-9]{3,}\b', user_answer.lower()))

        if not ref_words:
            return True, 1.0

        overlap = len(ref_words.intersection(usr_words))
        ratio = overlap / float(len(ref_words))
        is_corr = (ratio >= 0.35)
        score = min(1.0, ratio * 1.5)
        return is_corr, round(score, 2)

    async def generate_self_test_prompt(
        self,
        db: AsyncSession,
        video: Video
    ) -> Dict[str, Any]:
        """
        Generates an AI question / concept prompt for 'Test My Understanding'
        based on key video segments.
        """
        if getattr(video, "video_type", "knowledge") == "observational":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Test My Understanding is disabled for observational/surveillance footage."
            )

        stmt = select(VideoSegment).where(VideoSegment.video_id == video.id).order_by(VideoSegment.start_time)
        segments = (await db.execute(stmt)).scalars().all()
        if not segments:
            raise HTTPException(status_code=400, detail="Video has no indexed segments.")

        import random
        seg = random.choice(segments)
        t_fmt = f"{format_seconds_to_timestamp(seg.start_time)}–{format_seconds_to_timestamp(seg.end_time)}"
        concept = seg.transcript_text or seg.ocr_text or seg.visual_description or video.summary or "Video concept"

        # Derive clean topic
        topic = "Video Concept"
        for kw, top in [
            ("saksham", "Saksham LMS Platform"),
            ("moodle", "Moodle E-Learning"),
            ("dashboard", "System Dashboard"),
            ("subscriber", "Channel Metrics"),
            ("rag", "Retrieval Augmented Generation"),
            ("embedding", "Embeddings & Vector Search"),
            ("presentation", "Presentation Overview"),
            ("person", "Visual Identification"),
            ("screen", "On-Screen Content")
        ]:
            if kw in concept.lower() or kw in video.filename.lower():
                topic = top
                break

        question = f"What key concept or capability is demonstrated regarding {topic}?"

        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                prompt = (
                    "You are an expert tutor creating a direct domain conceptual question for a student.\n"
                    f"Video Title: {video.filename}\n"
                    f"Segment Subject Context: {concept}\n\n"
                    "CRITICAL RULES:\n"
                    "1. Generate 1 realistic, domain-specific conceptual question based on what is actually taught in this section (e.g. 'What is Retrieval Augmented Generation (RAG)?', 'How does vector embedding search work?').\n"
                    "2. ABSOLUTELY DO NOT mention timestamps, time ranges (e.g. 'at 00:20-00:30', 'in the video at MM:SS'), or phrases like 'What key information is highlighted in the video at...' inside the question!\n"
                    "3. Ask a direct, professional subject-matter question about the topic being discussed.\n\n"
                    "Format output strictly as:\n"
                    "QUESTION: [Your direct domain/subject question]\n"
                    "TOPIC: [1-3 word topic name]"
                )
                for model_name in [settings.GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
                    try:
                        model = genai.GenerativeModel(model_name)
                        res = await asyncio.wait_for(
                            asyncio.to_thread(model.generate_content, prompt),
                            timeout=10.0
                        )
                        if res and res.text:
                            m_q = re.search(r'QUESTION:\s*(.+)', res.text, re.IGNORECASE)
                            m_t = re.search(r'TOPIC:\s*(.+)', res.text, re.IGNORECASE)
                            if m_q:
                                raw_q = m_q.group(1).strip()
                                # Post-process: remove any stray timestamp strings or meta-phrasing
                                raw_q = re.sub(r'(?:at|in|between|during)?\s*\b\d{1,2}:\d{2}\s*(?:–|-|to)\s*\d{1,2}:\d{2}\b', '', raw_q, flags=re.IGNORECASE)
                                raw_q = re.sub(r'according to the video (?:at [^,\.\?\n]+)?', '', raw_q, flags=re.IGNORECASE)
                                raw_q = re.sub(r'highlighted in the video (?:at [^,\.\?\n]+)?', '', raw_q, flags=re.IGNORECASE)
                                raw_q = re.sub(r'\s+', ' ', raw_q).strip()
                                if raw_q:
                                    question = raw_q
                            if m_t:
                                topic = m_t.group(1).strip()
                            break
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"AI self test prompt error: {e}")

        return {
            "video_id": video.id,
            "question": question,
            "topic": topic,
            "timestamp_start": seg.start_time,
            "timestamp_end": seg.end_time,
            "timestamp_formatted": t_fmt
        }

    async def evaluate_self_test(
        self,
        db: AsyncSession,
        video: Video,
        user_question: str,
        user_answer: str
    ) -> SelfTestResponse:
        """
        'Test My Understanding': Evaluates a user-submitted question and written explanation
        against the uploaded video's factual segments, providing score (e.g. 3/10 or 8/10),
        status ('Needs Improvement' vs 'Mastered'), feedback, and the relevant video timestamp.
        """
        if getattr(video, "video_type", "knowledge") == "observational":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Test My Understanding is disabled for observational/surveillance footage."
            )

        # Retrieve video segments
        stmt = select(VideoSegment).where(VideoSegment.video_id == video.id).order_by(VideoSegment.start_time)
        segments = (await db.execute(stmt)).scalars().all()
        if not segments:
            raise HTTPException(status_code=400, detail="Video has no indexed segments.")

        # Find most relevant segment for user_question
        q_words = set(re.findall(r'\b[a-zA-Z0-9]{3,}\b', user_question.lower()))
        best_segment = segments[0]
        best_score = -1

        for s in segments:
            text = f"{s.combined_text} {s.ocr_text}".lower()
            matches = sum(1 for w in q_words if w in text)
            if matches > best_score:
                best_score = matches
                best_segment = s

        t_start = best_segment.start_time
        t_end = best_segment.end_time
        t_fmt = f"{format_seconds_to_timestamp(t_start)}–{format_seconds_to_timestamp(t_end)}"
        grounded_concept = best_segment.transcript_text or best_segment.ocr_text or best_segment.visual_description or video.summary or "Video content overview."

        # Derive topic
        topic = "Video Understanding"
        for kw, top in [
            ("rag", "Retrieval Augmented Generation"),
            ("ai", "Artificial Intelligence"),
            ("moodle", "LMS Systems"),
            ("saksham", "Saksham Platform"),
            ("database", "Database"),
            ("model", "Machine Learning Models"),
            ("subscriber", "Metrics & Analytics")
        ]:
            if kw in user_question.lower() or kw in user_answer.lower():
                topic = top
                break

        score = 0.0
        status_label = "Needs Improvement"
        feedback = ""

        # AI Evaluation if available
        if self.api_key and HAS_GENAI and self.api_key != "your_gemini_api_key_here":
            try:
                prompt = (
                    "You are a strict educational assessor evaluating a student's answer against the video's actual content.\n"
                    f"Student Question: {user_question}\n"
                    f"Student Written Answer: {user_answer}\n"
                    f"Actual Video Evidence at {t_fmt}: {grounded_concept}\n\n"
                    "Evaluate whether the student's answer accurately captures the concept explained in the video.\n"
                    "Respond in EXACTLY this format:\n"
                    "SCORE: [integer 0 to 10]\n"
                    "STATUS: [Mastered | Partially Correct | Needs Improvement]\n"
                    "FEEDBACK: [1-2 sentences explaining what was correct or missing]\n"
                    "CORRECT_CONCEPT: [Clear 1-2 sentence statement of the correct concept according to the video]"
                )

                for model_name in [settings.GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
                    try:
                        model = genai.GenerativeModel(model_name)
                        res = await asyncio.wait_for(
                            asyncio.to_thread(model.generate_content, prompt),
                            timeout=15.0
                        )
                        if res and res.text:
                            m_sc = re.search(r'SCORE:\s*(\d+)', res.text, re.IGNORECASE)
                            m_st = re.search(r'STATUS:\s*(Mastered|Partially Correct|Needs Improvement)', res.text, re.IGNORECASE)
                            m_fb = re.search(r'FEEDBACK:\s*(.+?)(?=CORRECT_CONCEPT:|$)', res.text, re.IGNORECASE | re.DOTALL)
                            m_cc = re.search(r'CORRECT_CONCEPT:\s*(.+)', res.text, re.IGNORECASE | re.DOTALL)

                            score = float(m_sc.group(1)) if m_sc else 5.0
                            status_label = m_st.group(1).title() if m_st else ("Mastered" if score >= 8 else ("Partially Correct" if score >= 5 else "Needs Improvement"))
                            feedback = m_fb.group(1).strip() if m_fb else "Evaluated against video content."
                            correct_concept = m_cc.group(1).strip() if m_cc else grounded_concept[:200]
                            break
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"AI self-test evaluation error: {e}")

        # Deterministic fallback evaluation
        if not feedback:
            ref_words = set(re.findall(r'\b[a-zA-Z0-9]{3,}\b', grounded_concept.lower()))
            ans_words = set(re.findall(r'\b[a-zA-Z0-9]{3,}\b', user_answer.lower()))

            overlap = len(ref_words.intersection(ans_words))
            ratio = overlap / float(max(1, len(ref_words)))

            if ratio >= 0.40:
                score = 9.0
                status_label = "Mastered"
                feedback = "Excellent! Your explanation accurately aligns with the concepts presented in the video."
            elif ratio >= 0.15:
                score = 5.0
                status_label = "Partially Correct"
                feedback = "Your answer is partially related, but it misses several key details covered in the video."
            else:
                score = 3.0
                status_label = "Needs Improvement"
                feedback = "Your answer is not sufficiently accurate according to the uploaded video explanation."

            correct_concept = grounded_concept[:220]

        # Record SelfTestAttempt in DB
        attempt = SelfTestAttempt(
            video_id=video.id,
            user_question=user_question,
            user_answer=user_answer,
            score=score,
            max_score=10.0,
            status=status_label,
            feedback=feedback,
            correct_concept=correct_concept,
            topic=topic,
            relevant_timestamp_start=t_start,
            relevant_timestamp_end=t_end,
            relevant_timestamp_formatted=t_fmt
        )
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)

        return SelfTestResponse(
            id=attempt.id,
            video_id=video.id,
            user_question=user_question,
            user_answer=user_answer,
            score=score,
            max_score=10.0,
            status=status_label,
            feedback=feedback,
            correct_concept=correct_concept,
            topic=topic,
            relevant_timestamp_formatted=t_fmt,
            relevant_timestamp_start=t_start,
            relevant_timestamp_end=t_end,
            created_at=attempt.created_at
        )


quiz_service = QuizService()

