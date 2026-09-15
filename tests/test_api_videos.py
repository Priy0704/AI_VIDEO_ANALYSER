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
