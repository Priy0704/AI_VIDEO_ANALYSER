import pytest
import asyncio
from httpx import AsyncClient
from app.db.database import AsyncSessionLocal
from app.db.models import Video, VideoSegment, VideoStatus
from app.schemas.chat import ChatResponse


@pytest.mark.asyncio
async def test_multimodal_multi_video_search_and_qa_system(async_client: AsyncClient):
    """
    Comprehensive test suite validating the True Multi-Video Multimodal Search and QA System:
    1. Multi-Video Search across multiple unrelated videos without selecting a video
    2. Multimodal Evidence across all 4 modalities (Transcript, Visual, OCR, Event)
    3. Conflicting Evidence Reconciliation (The 3000 vs 2.56K subscriber count test)
    4. Cross-Video Subject Tracking with identity caution
    5. Absence of Evidence / Anti-hallucination safeguard
    6. Exact 4-part structured output (Answer, Evidence, Confidence, Reason)
    7. Calibrated Confidence (High, Medium, Low)
    """
    async with AsyncSessionLocal() as db:
        # Video 1: YouTube Tutorial with conflicting spoken vs on-screen subscriber metrics
        v_tutorial = Video(
            filename="youtube_creator_tutorial.mp4",
            file_path="data/uploads/youtube_creator_tutorial.mp4",
            duration_seconds=300.0,
            status=VideoStatus.COMPLETED,
            summary="Channel growth walkthrough and live dashboard overview."
        )

        # Video 2: CCTV Entrance Camera
        v_cctv1 = Video(
            filename="cctv_entrance_north.mp4",
            file_path="data/uploads/cctv_entrance_north.mp4",
            duration_seconds=600.0,
            status=VideoStatus.COMPLETED,
            summary="Security camera at the North entrance gate."
        )

        # Video 3: CCTV Corridor Camera
        v_cctv2 = Video(
            filename="cctv_hallway_corridor.mp4",
            file_path="data/uploads/cctv_hallway_corridor.mp4",
            duration_seconds=600.0,
            status=VideoStatus.COMPLETED,
            summary="Security camera monitoring the 2nd floor office hallway."
        )

        db.add(v_tutorial)
        db.add(v_cctv1)
        db.add(v_cctv2)
        await db.commit()
        await db.refresh(v_tutorial)
        await db.refresh(v_cctv1)
        await db.refresh(v_cctv2)

        # Segments for Video 1: Conflicting subscriber count
        # Transcript says: "We are approaching 3,000 subscribers" at 01:20
        # OCR / On-screen says: "2.56K subscribers" at 01:20
        seg_tutorial = VideoSegment(
            video_id=v_tutorial.id,
            start_time=80.0,
            end_time=95.0,
            visual_description="The creator shares their computer screen displaying their YouTube Studio channel overview page. Headline: Channel Analytics Dashboard. Details: A web browser window displays channel stats and recent subscriber growth metrics. On-Screen Text & Names: 2.56K subscribers",
            transcript_text="As you can see, we are approaching 3,000 subscribers on this channel.",
            ocr_text="2.56K subscribers",
            combined_text="Channel analytics dashboard showing 2.56K subscribers while speaker says approaching 3,000 subscribers."
        )

        # Segments for Video 2: CCTV Entrance
        seg_cctv1 = VideoSegment(
            video_id=v_cctv1.id,
            start_time=300.0,  # 05:00
            end_time=315.0,
            visual_description="An individual wearing a black jacket and blue jeans enters through the North security gate holding a backpack.",
            transcript_text="",
            ocr_text="GATE NORTH - 05:00:00",
            combined_text="Individual wearing a black jacket enters through North security gate."
        )

        # Segments for Video 3: CCTV Corridor
        seg_cctv2 = VideoSegment(
            video_id=v_cctv2.id,
            start_time=420.0,  # 07:00
            end_time=435.0,
            visual_description="An individual wearing a black jacket and blue jeans walks down the hallway corridor towards the server room.",
            transcript_text="",
            ocr_text="CORRIDOR 2F - 07:00:00",
            combined_text="Individual wearing a black jacket walks down hallway corridor."
        )

        db.add(seg_tutorial)
        db.add(seg_cctv1)
        db.add(seg_cctv2)
        await db.commit()

    try:
        # =====================================================================
        # TEST 1: RECONCILING CONFLICTING EVIDENCE (Subscriber Count Dilemma)
        # =====================================================================
        res_sub = await async_client.post(
            "/api/v1/chat",
            json={"query": "How many subscribers does the channel have?"}
        )
        assert res_sub.status_code == 200
        d_sub = res_sub.json()
        ans_sub = d_sub["answer"]

        # Must report both the spoken statement and the on-screen display
        assert "3,000" in ans_sub or "3000" in ans_sub
        assert "2.56K" in ans_sub or "2.56" in ans_sub
        assert "Answer:" in ans_sub
        assert "Evidence:" in ans_sub
        assert "Confidence:" in ans_sub
        assert "Reason:" in ans_sub

        # Must differentiate Transcript vs OCR modalities in evidence citations
        modalities_cited = [c.get("modality") for c in d_sub["citations"]]
        assert any(m in ["Transcript", "OCR", "Visual"] for m in modalities_cited)
        assert d_sub["confidence_level"] in ["High", "Medium"]

        # =====================================================================
        # TEST 2: CROSS-VIDEO SUBJECT TRACKING (CCTV surveillance)
        # =====================================================================
        res_track = await async_client.post(
            "/api/v1/chat",
            json={"query": "Trace the individual wearing the black jacket across the cameras and give timestamps"}
        )
        assert res_track.status_code == 200
        d_track = res_track.json()
        ans_track = d_track["answer"]

        # Must cite both cameras / video names
        assert "cctv_entrance_north.mp4" in ans_track or "cctv_entrance" in ans_track.lower()
        assert "cctv_hallway_corridor.mp4" in ans_track or "cctv_hallway" in ans_track.lower()

        # Must include identity caution
        assert "insufficient to confirm identity" in ans_track or "represent the same person" in ans_track

        # Must have timestamps for both appearances
        assert "05:00" in ans_track
        assert "07:00" in ans_track

        # Exact 4-part structure
        assert "Answer:" in ans_track
        assert "Evidence:" in ans_track
        assert "Confidence:" in ans_track
        assert "Reason:" in ans_track

        # =====================================================================
        # TEST 3: MULTI-VIDEO SEARCH WITHOUT VIDEO SELECTION
        # =====================================================================
        # The user does NOT select any video, system automatically searches all processed videos
        assert d_track["scope"] == "all"
        assert len(d_track["videos_analyzed"]) >= 3

        # =====================================================================
        # TEST 4: ABSENCE OF EVIDENCE (Not Found Handling)
        # =====================================================================
        res_absent = await async_client.post(
            "/api/v1/chat",
            json={"query": "Where is the flying purple submarine parked?"}
        )
        assert res_absent.status_code == 200
        d_absent = res_absent.json()
        ans_absent = d_absent["answer"]

        # Must clearly state absence without guessing
        assert "No sufficient evidence was found in the uploaded videos." in ans_absent
        assert "No supporting evidence found in the uploaded videos." in ans_absent
        assert "Confidence:\nLow" in ans_absent or "Low" in d_absent.get("confidence_level", "")
        assert d_absent["confidence_score"] <= 0.25
        assert len(d_absent["citations"]) == 0
        # Anti-hallucination check: NO timestamp in answer
        assert "Timestamp:" not in ans_absent

        # =====================================================================
        # TEST 5: MULTIMODAL CITATIONS INTEGRITY
        # =====================================================================
        citations = d_sub["citations"]
        assert len(citations) >= 1
        for cit in citations:
            assert "start_time" in cit
            assert "end_time" in cit
            assert "timestamp_formatted" in cit
            assert "video_filename" in cit
            assert "modality" in cit
            assert cit["modality"] in ["Transcript", "Visual", "OCR", "Event", "Multimodal"]

    finally:
        # Cleanup mock test records
        async with AsyncSessionLocal() as db:
            await db.delete(v_tutorial)
            await db.delete(v_cctv1)
            await db.delete(v_cctv2)
            await db.commit()
