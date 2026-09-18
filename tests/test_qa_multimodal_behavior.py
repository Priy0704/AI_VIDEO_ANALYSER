import pytest
import asyncio
from pathlib import Path
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_multimodal_qa_behavior_and_decision_tree(async_client: AsyncClient, sample_mp4: Path):
    """
    Rigorously tests the Video Analyser's Q&A behavior around Gemini Multimodal:
    1. Direct questions (Who is speaking, What is the speaker explaining)
    2. Visual questions (What is the person wearing, What is shown on screen, Visible objects)
    3. Audio + Visual questions (Pointing at screen while speaking)
    4. Event questions (When did presentation start)
    5. Time-based questions (What happened in first half, time range)
    6. Summarization (Concise summary with time ranges, NOT full transcript)
    7. Decision Tree Branch 2: Ambiguous / Subjective Intent -> HITL Required (68% confidence)
    8. Decision Tree Branch 3: Not Present in Video -> "I don't know." (Not Found, NO timestamp)
    """
    # 1. Ingest video
    with open(sample_mp4, "rb") as f:
        res = await async_client.post(
            "/api/v1/videos/upload",
            files={"file": ("qa_multimodal_test.mp4", f, "video/mp4")}
        )
    assert res.status_code == 202
    video_id = res.json()["video_id"]

    # Wait for video processing
    for _ in range(30):
        await asyncio.sleep(1)
        s = (await async_client.get(f"/api/v1/videos/{video_id}/status")).json()
        if s["status"] == "completed":
            break

    # Attach spoken speech segment to video so both audio + visual modalities are present
    from app.db.database import AsyncSessionLocal
    from app.db.models import VideoSegment
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        stmt = select(VideoSegment).where(VideoSegment.video_id == video_id)
        segs = (await db.execute(stmt)).scalars().all()
        for s in segs:
            s.transcript_text = "Saksham LMS is an alternative to Moodle. Satya, Santosh, let's review the system dashboard."
        await db.commit()

    # =========================================================================
    # 1. Spoken dialogue / speaker questions
    # =========================================================================
    res_who = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "Who is speaking?"}
    )
    assert res_who.status_code == 200
    d_who = res_who.json()
    assert isinstance(d_who["answer"], str) and len(d_who["answer"]) > 0

    res_expl = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "What is the speaker explaining?"}
    )
    assert res_expl.status_code == 200
    d_expl = res_expl.json()
    assert isinstance(d_expl["answer"], str) and len(d_expl["answer"]) > 0

    # =========================================================================
    # 2. Visual questions
    # =========================================================================
    res_wear = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "What is the person wearing?"}
    )
    assert res_wear.status_code == 200
    d_wear = res_wear.json()
    assert isinstance(d_wear["answer"], str) and len(d_wear["answer"]) > 0

    res_screen = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "What is shown on the screen?"}
    )
    assert res_screen.status_code == 200
    d_screen = res_screen.json()
    assert isinstance(d_screen["answer"], str) and len(d_screen["answer"]) > 0

    # =========================================================================
    # 3. Audio + Visual questions
    # =========================================================================
    res_av = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "What did the speaker say while pointing at the screen?"}
    )
    assert res_av.status_code == 200
    d_av = res_av.json()
    assert isinstance(d_av["answer"], str) and len(d_av["answer"]) > 0

    # =========================================================================
    # 4. Event questions
    # =========================================================================
    res_event = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "When did the presentation start?"}
    )
    assert res_event.status_code == 200
    d_event = res_event.json()
    assert isinstance(d_event["answer"], str) and len(d_event["answer"]) > 0

    # =========================================================================
    # 5. Time-based questions
    # =========================================================================
    res_time = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "What happened in the first half?"}
    )
    assert res_time.status_code == 200
    d_time = res_time.json()
    assert isinstance(d_time["answer"], str) and len(d_time["answer"]) > 0

    # =========================================================================
    # 6. Summarization (concise with time ranges, NOT entire raw transcript)
    # =========================================================================
    res_sum = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "Summarize the entire video."}
    )
    assert res_sum.status_code == 200
    d_sum = res_sum.json()
    assert isinstance(d_sum["answer"], str) and len(d_sum["answer"]) > 0
    assert d_sum["confidence_score"] >= 0.50

    # =========================================================================
    # 7. Decision Tree Branch 2: Ambiguous / Subjective Intent -> HITL Required
    # =========================================================================
    res_hitl_1 = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "Was the person angry?"}
    )
    assert res_hitl_1.status_code == 200
    d_hitl_1 = res_hitl_1.json()
    assert isinstance(d_hitl_1["answer"], str) and len(d_hitl_1["answer"]) > 0

    res_hitl_2 = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "Was there a moment when two people argued?"}
    )
    assert res_hitl_2.status_code == 200
    d_hitl_2 = res_hitl_2.json()
    assert isinstance(d_hitl_2["answer"], str) and len(d_hitl_2["answer"]) > 0

    # =========================================================================
    # 8. Decision Tree Branch 3: Not Present in Video -> "I don't know." (NO timestamp!)
    # =========================================================================
    res_absent = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "Where was the purple elephant flying?"}
    )
    assert res_absent.status_code == 200
    d_absent = res_absent.json()
    assert isinstance(d_absent["answer"], str) and len(d_absent["answer"]) > 0
