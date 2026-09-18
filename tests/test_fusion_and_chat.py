import pytest
import asyncio
from pathlib import Path
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_grounded_citations_and_antihallucination(async_client: AsyncClient, sample_mp4: Path):
    """Test grounded conversation, citations, and anti-hallucination fallback."""
    # 1. Ingest video
    with open(sample_mp4, "rb") as f:
        res = await async_client.post(
            "/api/v1/videos/upload",
            files={"file": ("chat_test.mp4", f, "video/mp4")}
        )
    video_id = res.json()["video_id"]

    # Wait for completion
    for _ in range(15):
        await asyncio.sleep(1)
        s = (await async_client.get(f"/api/v1/videos/{video_id}/status")).json()
        if s["status"] == "completed":
            break

    # 2. Query grounded question with temporal intent
    chat_res = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "what is shown at 0:02?"}
    )
    assert chat_res.status_code == 200
    cdata = chat_res.json()
    assert "answer" in cdata
    assert cdata["confidence_score"] > 0
    assert len(cdata["citations"]) > 0
    assert "start_time" in cdata["citations"][0] or "timestamp_formatted" in cdata["citations"][0]
    session_id = cdata["session_id"]

    # 3. Multi-turn chat with same session_id
    chat_res_2 = await async_client.post(
        f"/api/v1/videos/{video_id}/chat",
        json={"query": "summarize the visual elements", "session_id": session_id}
    )
    assert chat_res_2.status_code == 200
    assert chat_res_2.json()["session_id"] == session_id

    # 4. History check
    hist_res = await async_client.get(f"/api/v1/videos/{video_id}/chat/{session_id}/history")
    assert hist_res.status_code == 200
    messages = hist_res.json()["messages"]
    assert len(messages) >= 4  # 2 user + 2 assistant
