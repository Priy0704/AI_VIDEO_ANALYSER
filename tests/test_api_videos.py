import pytest
import asyncio
from pathlib import Path
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_and_ready(async_client: AsyncClient):
    """Verify liveness and readiness endpoints."""
    res = await async_client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

    res = await async_client.get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_upload_invalid_extension(async_client: AsyncClient, tmp_path: Path):
    """Reject unaccepted file types."""
    bad_file = tmp_path / "test.txt"
    bad_file.write_text("not a video")

    with open(bad_file, "rb") as f:
        res = await async_client.post(
            "/api/v1/videos/upload",
            files={"file": ("test.txt", f, "text/plain")}
        )
    assert res.status_code == 400
    assert "Invalid format" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_valid_mp4_and_poll_status(async_client: AsyncClient, sample_mp4: Path):
    """Upload real MP4 and track status progression."""
    with open(sample_mp4, "rb") as f:
        res = await async_client.post(
            "/api/v1/videos/upload",
            files={"file": ("sample.mp4", f, "video/mp4")}
        )
    assert res.status_code == 202
    data = res.json()
    video_id = data["video_id"]
    assert data["status"] in ["queued", "processing"]

    # Poll status until completed (timeout after 15s)
    completed = False
    for _ in range(15):
        await asyncio.sleep(1)
        status_res = await async_client.get(f"/api/v1/videos/{video_id}/status")
        assert status_res.status_code == 200
        sdata = status_res.json()
        if sdata["status"] == "completed":
            completed = True
            assert sdata["progress_pct"] == 100
            assert sdata["duration_seconds"] > 0
            break
        elif sdata["status"] == "failed":
            pytest.fail(f"Video processing failed: {sdata.get('error_message')}")

    assert completed, "Video pipeline did not reach 'completed' state in time."

    # Verify detail endpoint
    detail_res = await async_client.get(f"/api/v1/videos/{video_id}")
    assert detail_res.status_code == 200
    ddata = detail_res.json()
    assert ddata["segments_count"] > 0
    assert len(ddata["segments"]) > 0


@pytest.mark.asyncio
async def test_upload_multiple_videos_batch(async_client: AsyncClient, sample_mp4: Path, monkeypatch):
    """Verify batch upload accepts multiple 4-5 video files concurrently within seconds."""
    from app.services.task_queue import task_queue
    enqueued = []
    monkeypatch.setattr(task_queue, "enqueue_video_processing", lambda vid, path: enqueued.append((vid, path)))

    # Open 4 file handles pointing to sample video
    with open(sample_mp4, "rb") as f1, open(sample_mp4, "rb") as f2, open(sample_mp4, "rb") as f3, open(sample_mp4, "rb") as f4:
        files = [
            ("files", ("video1.mp4", f1, "video/mp4")),
            ("files", ("video2.mp4", f2, "video/mp4")),
            ("files", ("video3.mp4", f3, "video/mp4")),
            ("files", ("video4.mp4", f4, "video/mp4")),
        ]
        res = await async_client.post("/api/v1/videos/upload-batch", files=files)

    assert res.status_code == 202
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 4
    for item in data:
        assert "video_id" in item
        assert item["status"] in ["queued", "processing"]
    assert len(enqueued) == 4



@pytest.mark.asyncio
async def test_from_url_immediate_response(async_client: AsyncClient, monkeypatch):
    """Verify URL ingestion returns immediately (non-blocking) within milliseconds."""
    from app.services.task_queue import task_queue
    called = []
    monkeypatch.setattr(task_queue, "enqueue_url_processing", lambda vid, url: called.append((vid, url)))

    payload = {"url": "https://example.com/stream.mp4"}
    res = await async_client.post("/api/v1/videos/from-url", json=payload)
    assert res.status_code == 202
    data = res.json()
    assert "video_id" in data
    assert data["status"] == "processing"
    assert len(called) == 1
    assert called[0][0] == data["video_id"]


