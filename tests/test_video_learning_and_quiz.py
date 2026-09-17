import pytest
import uuid
from app.db.database import AsyncSessionLocal
from app.db.models import Video, VideoSegment, Quiz, QuizQuestion, QuizAttempt, SelfTestAttempt
from app.services.video_classifier import video_classifier
from app.services.quiz_service import quiz_service
from app.services.pdf_generator import pdf_generator


@pytest.mark.asyncio
async def test_video_classifier_observational():
    """Test classification logic recognizes surveillance and traffic camera footage as observational."""
    cctv_segments = [
        VideoSegment(
            id=str(uuid.uuid4()),
            video_id=str(uuid.uuid4()),
            start_time=0.0,
            end_time=10.0,
            transcript_text="",
            visual_description="Static overhead surveillance camera viewing empty parking lot at night.",
            ocr_text="CAM-04 2026-09-17 22:15:00",
            combined_text="Static overhead surveillance camera viewing empty parking lot at night. CAM-04 2026-09-17 22:15:00"
        ),
        VideoSegment(
            id=str(uuid.uuid4()),
            video_id=str(uuid.uuid4()),
            start_time=10.0,
            end_time=20.0,
            transcript_text="",
            visual_description="Overhead CCTV recording security gate as vehicle enters driveway.",
            ocr_text="CAM-04 2026-09-17 22:15:10",
            combined_text="Overhead CCTV recording security gate as vehicle enters driveway. CAM-04 2026-09-17 22:15:10"
        )
    ]

    result = await video_classifier.classify_video(
        filename="cctv_gate_cam04.mp4",
        transcripts=[s.transcript_text for s in cctv_segments if s.transcript_text],
        visual_descriptions=[s.visual_description for s in cctv_segments if s.visual_description],
        ocr_texts=[s.ocr_text for s in cctv_segments if s.ocr_text]
    )

    assert result.video_type == "observational"
    assert "Observational" in result.label
    assert result.confidence >= 0.7


@pytest.mark.asyncio
async def test_video_classifier_knowledge():
    """Test classification logic recognizes presentations and tutorials as knowledge content."""
    lecture_segments = [
        VideoSegment(
            id=str(uuid.uuid4()),
            video_id=str(uuid.uuid4()),
            start_time=0.0,
            end_time=15.0,
            transcript_text="Welcome to this lecture on neural networks and gradient descent.",
            visual_description="Instructor presenting slide titled 'Deep Learning Architecture and Backpropagation'.",
            ocr_text="Lecture 3: Neural Networks and Backpropagation",
            combined_text="Welcome to this lecture on neural networks and gradient descent. Instructor presenting slide titled 'Deep Learning Architecture and Backpropagation'."
        ),
        VideoSegment(
            id=str(uuid.uuid4()),
            video_id=str(uuid.uuid4()),
            start_time=15.0,
            end_time=30.0,
            transcript_text="In backpropagation, the chain rule is used to compute gradients for weight updates.",
            visual_description="Close-up of mathematical derivation on chalkboard.",
            ocr_text="dL/dw = dL/dy * dy/dw",
            combined_text="In backpropagation, the chain rule is used to compute gradients for weight updates. Close-up of mathematical derivation on chalkboard."
        )
    ]

    result = await video_classifier.classify_video(
        filename="lecture_deep_learning_intro.mp4",
        transcripts=[s.transcript_text for s in lecture_segments if s.transcript_text],
        visual_descriptions=[s.visual_description for s in lecture_segments if s.visual_description],
        ocr_texts=[s.ocr_text for s in lecture_segments if s.ocr_text]
    )

    assert result.video_type == "knowledge"
    assert "Knowledge" in result.label
    assert result.confidence >= 0.7


@pytest.mark.asyncio
async def test_quiz_generation_and_grounding(async_client):
    """Test generating a quiz grounded in video segments."""
    video_id = str(uuid.uuid4())
    quiz_id = None
    async with AsyncSessionLocal() as db:
        vid = Video(
            id=video_id,
            filename="training_course_demo.mp4",
            file_path=f"data/uploads/{video_id}.mp4",
            status="completed",
            duration_seconds=120.0,
            video_type="knowledge",
            video_type_label="Knowledge / Content-based",
            video_type_confidence=0.95
        )
        db.add(vid)
        await db.commit()

        # Seed knowledge segments
        seg1 = VideoSegment(
            id=str(uuid.uuid4()),
            video_id=video_id,
            start_time=10.0,
            end_time=40.0,
            transcript_text="Docker containers isolate applications from their underlying host environment using namespaces and cgroups.",
            visual_description="Presenter demonstrating Docker CLI commands in terminal.",
            ocr_text="docker run -d -p 8080:80 nginx",
            combined_text="Docker containers isolate applications from their underlying host environment using namespaces and cgroups."
        )
        seg2 = VideoSegment(
            id=str(uuid.uuid4()),
            video_id=video_id,
            start_time=40.0,
            end_time=80.0,
            transcript_text="Kubernetes orchestrates container deployments, automatic scaling, and load balancing across worker nodes.",
            visual_description="Slide showing Kubernetes cluster architecture with Control Plane and Worker Nodes.",
            ocr_text="Kubernetes Architecture: kube-apiserver, etcd, kubelet",
            combined_text="Kubernetes orchestrates container deployments, automatic scaling, and load balancing across worker nodes."
        )
        db.add_all([seg1, seg2])
        await db.commit()

    try:
        # Generate Quiz via API
        resp = await async_client.post(
            f"/api/v1/videos/{video_id}/quiz/generate",
            json={"num_questions": 5, "difficulty": "medium", "question_type": "mixed"}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "id" in data
        assert data["video_id"] == video_id
        assert data["total_questions"] >= 2
        assert len(data["questions"]) >= 2

        # Check question grounding
        first_q = data["questions"][0]
        assert "question" in first_q
        assert "options" in first_q
        assert first_q["relevant_timestamp_start"] is not None
        assert first_q["relevant_timestamp_start"] in [10.0, 40.0]

        quiz_id = data["id"]

        # Fetch Quiz details
        q_resp = await async_client.get(f"/api/v1/quizzes/{quiz_id}")
        assert q_resp.status_code == 200
        q_data = q_resp.json()
        assert q_data["id"] == quiz_id

        # Submit Quiz Answers
        answers_payload = {}
        for q in data["questions"]:
            if q["id"] == first_q["id"]:
                answers_payload[q["id"]] = q.get("correct_answer") or "Docker containers isolate applications"
            else:
                answers_payload[q["id"]] = "WRONG_ANSWER"

        sub_resp = await async_client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={"answers": answers_payload}
        )
        assert sub_resp.status_code == 200
        sub_data = sub_resp.json()

        assert "total_score" in sub_data
        assert "percentage" in sub_data
        assert sub_data["total_score"] >= 0
        assert "strong_areas" in sub_data
        assert "needs_improvement" in sub_data
        assert len(sub_data["questions"]) == len(data["questions"])

        attempt_id = sub_data["attempt_id"]

        # Test Question Paper PDF Endpoint
        pdf_q_resp = await async_client.get(f"/api/v1/quizzes/{quiz_id}/pdf/questions")
        assert pdf_q_resp.status_code == 200
        assert pdf_q_resp.headers["content-type"] == "application/pdf"
        assert pdf_q_resp.content.startswith(b"%PDF-")

        # Test Evaluation Report PDF Endpoint
        pdf_rep_resp = await async_client.get(f"/api/v1/quizzes/{quiz_id}/attempts/{attempt_id}/pdf/report")
        assert pdf_rep_resp.status_code == 200
        assert pdf_rep_resp.headers["content-type"] == "application/pdf"
        assert pdf_rep_resp.content.startswith(b"%PDF-")

    finally:
        # Cleanup
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            if quiz_id:
                await db.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id))
                await db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))
                await db.execute(delete(Quiz).where(Quiz.id == quiz_id))
            await db.execute(delete(VideoSegment).where(VideoSegment.video_id == video_id))
            await db.execute(delete(Video).where(Video.id == video_id))
            await db.commit()


@pytest.mark.asyncio
async def test_observational_video_blocks_quiz(async_client):
    """Test that observational / surveillance videos block quiz generation with an explanatory error."""
    video_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        vid = Video(
            id=video_id,
            filename="cctv_entrance_cam1.mp4",
            file_path=f"data/uploads/{video_id}.mp4",
            status="completed",
            duration_seconds=60.0,
            video_type="observational",
            video_type_label="Observational / Surveillance",
            video_type_confidence=0.98,
            video_type_reason="Surveillance camera monitoring entrance."
        )
        db.add(vid)
        await db.commit()

    try:
        resp = await async_client.post(
            f"/api/v1/videos/{video_id}/quiz/generate",
            json={"num_questions": 5, "difficulty": "medium", "question_type": "mixed"}
        )
        assert resp.status_code == 400
        err_msg = resp.json().get("detail", "")
        assert "disabled for observational" in err_msg.lower()

        # Also verify self-test is blocked
        st_resp = await async_client.post(
            f"/api/v1/videos/{video_id}/self-test",
            json={"user_question": "What happened?", "user_answer": "Cars passed by."}
        )
        assert st_resp.status_code == 400
        assert "disabled for observational" in st_resp.json().get("detail", "").lower()

    finally:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            await db.execute(delete(Video).where(Video.id == video_id))
            await db.commit()


@pytest.mark.asyncio
async def test_self_test_evaluation(async_client):
    """Test the free-form Test My Understanding written assessment."""
    video_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        vid = Video(
            id=video_id,
            filename="saksham_lms_overview.mp4",
            file_path=f"data/uploads/{video_id}.mp4",
            status="completed",
            duration_seconds=90.0,
            video_type="knowledge",
            video_type_label="Knowledge / Content-based"
        )
        db.add(vid)

        seg = VideoSegment(
            id=str(uuid.uuid4()),
            video_id=video_id,
            start_time=15.0,
            end_time=45.0,
            transcript_text="Saksham LMS automates candidate training and assessment tracking with interactive question banks.",
            visual_description="Dashboard demo of Saksham platform showing learner progress bars.",
            ocr_text="Saksham Learning Platform - Candidate Progress",
            combined_text="Saksham LMS automates candidate training and assessment tracking with interactive question banks."
        )
        db.add(seg)
        await db.commit()

    try:
        resp = await async_client.post(
            f"/api/v1/videos/{video_id}/self-test",
            json={
                "user_question": "What is Saksham LMS?",
                "user_answer": "Saksham is a learning platform that tracks candidate training and assessments."
            }
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "score" in data
        assert 0 <= data["score"] <= 10
        assert "feedback" in data
        assert "relevant_timestamp_start" in data
        assert data["relevant_timestamp_start"] == 15.0

    finally:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            await db.execute(delete(SelfTestAttempt).where(SelfTestAttempt.video_id == video_id))
            await db.execute(delete(VideoSegment).where(VideoSegment.video_id == video_id))
            await db.execute(delete(Video).where(Video.id == video_id))
            await db.commit()
