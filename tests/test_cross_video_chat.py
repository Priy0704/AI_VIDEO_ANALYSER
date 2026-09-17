import pytest
import asyncio
from httpx import AsyncClient
from app.db.database import AsyncSessionLocal
from app.db.models import Video, VideoSegment, VideoStatus


@pytest.mark.asyncio
async def test_cross_video_chat_and_tracking(async_client: AsyncClient):
    """Test global cross-video search and Q&A across multiple videos."""
    async with AsyncSessionLocal() as db:
        # Create 2 mock completed videos to simulate multi-camera CCTV footage
        v1 = Video(
            filename="cctv_entrance_gate.mp4",
            file_path="data/uploads/cctv_entrance_gate.mp4",
            duration_seconds=600.0,
            status=VideoStatus.COMPLETED,
            summary="Camera at entrance gate recording vehicles and visitor arrivals."
        )
        v2 = Video(
            filename="cctv_main_corridor.mp4",
            file_path="data/uploads/cctv_main_corridor.mp4",
            duration_seconds=720.0,
            status=VideoStatus.COMPLETED,
            summary="Camera at main office corridor recording foot traffic."
        )
        db.add(v1)
        db.add(v2)
        await db.commit()
        await db.refresh(v1)
        await db.refresh(v2)

        # Add mock segments with distinct times and descriptions
        seg1 = VideoSegment(
            video_id=v1.id,
            start_time=300.0,
            end_time=315.0,
            visual_description="Individual wearing a black jacket and blue jeans enters through the north entrance gate.",
            transcript_text="Visitor arriving at gate.",
            combined_text="Individual wearing a black jacket and blue jeans enters through the north entrance gate. Visitor arriving at gate."
        )
        seg2 = VideoSegment(
            video_id=v2.id,
            start_time=420.0,
            end_time=435.0,
            visual_description="Individual wearing a black jacket and blue jeans walks down the main corridor towards the executive office.",
            transcript_text="",
            combined_text="Individual wearing a black jacket and blue jeans walks down the main corridor towards the executive office."
        )
        db.add(seg1)
        db.add(seg2)
        await db.commit()

    try:
        # 1. Global Cross-Video Query
        res = await async_client.post(
            "/api/v1/chat",
            json={
                "query": "trace the individual wearing black jacket across the cameras and give timestamps",
                "scope": "all"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["scope"] == "all"
        assert len(data["citations"]) > 0

        # Citations must have video_filename and timestamp
        filenames_cited = [c["video_filename"] for c in data["citations"] if c.get("video_filename")]
        assert len(filenames_cited) > 0

        first_cit = data["citations"][0]
        assert "timestamp_formatted" in first_cit
        assert "video_id" in first_cit
        assert "video_filename" in first_cit

        session_id = data["session_id"]

        # 2. Multi-turn cross-video conversation
        res_turn2 = await async_client.post(
            "/api/v1/chat",
            json={
                "query": "what time did they enter at the gate?",
                "session_id": session_id,
                "scope": "all"
            }
        )
        assert res_turn2.status_code == 200
        assert res_turn2.json()["session_id"] == session_id

        # 3. Global chat history retrieval
        hist_res = await async_client.get(f"/api/v1/chat/{session_id}/history")
        assert hist_res.status_code == 200
        messages = hist_res.json()["messages"]
        assert len(messages) >= 4

    finally:
        # Cleanup mock test data
        async with AsyncSessionLocal() as db:
            await db.delete(v1)
            await db.delete(v2)
            await db.commit()
