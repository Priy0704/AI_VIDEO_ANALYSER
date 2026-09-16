import pytest
import asyncio
from pathlib import Path
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_confidence_driven_hitl_workflow(async_client: AsyncClient, sample_mp4: Path):
    """Test confidence-driven HITL auto-flagging and human verification."""
    # 1. Ingest video
    with open(sample_mp4, "rb") as f:
        res = await async_client.post(
            "/api/v1/videos/upload",
            files={"file": ("hitl_test.mp4", f, "video/mp4")}
        )
    video_id = res.json()["video_id"]

    for _ in range(15):
        await asyncio.sleep(1)
        s = (await async_client.get(f"/api/v1/videos/{video_id}/status")).json()
        if s["status"] == "completed":
            break

    # 2. Ask an ambiguous question requiring subjective interpretation (< 0.70 confidence)
    chat_res = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "was the person angry?"}
    )
    assert chat_res.status_code == 200
    cdata = chat_res.json()
    assert cdata["confidence_score"] < 0.70
    assert cdata["requires_hitl"] is True
    review_id = cdata["hitl_review_id"]
    assert review_id is not None

    # 3. Verify item appears in HITL review queue
    reviews_res = await async_client.get(f"/api/v1/hitl/reviews?status_filter=pending&video_id={video_id}")
    assert reviews_res.status_code == 200
    reviews = reviews_res.json()
    assert any(r["id"] == review_id for r in reviews)

    # 4. Human reviewer submits correction
    update_res = await async_client.post(
        f"/api/v1/hitl/reviews/{review_id}",
        json={
            "status": "corrected",
            "reviewer_notes": "Presenter appears calm, verified by human auditor.",
            "corrected_answer": "No signs of anger observed; presenter is calm and professional."
        }
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["status"] == "corrected"
    assert updated_data["reviewer_notes"] == "Presenter appears calm, verified by human auditor."

    # 5. Subsequent query for the verified question now uses the human-verified answer!
    chat_verified = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "was the person angry?"}
    )
    assert chat_verified.status_code == 200
    vdata = chat_verified.json()
    assert vdata["confidence_score"] == 1.0
    assert vdata["requires_hitl"] is False
    assert "No signs of anger observed" in vdata["answer"]
    assert "Human Verified" in vdata["answer"]
    assert "Presenter appears calm, verified by human auditor" in vdata["answer"]
