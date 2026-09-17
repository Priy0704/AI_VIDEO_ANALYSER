import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from pathlib import Path


@pytest.mark.asyncio
async def test_from_url_invalid_request_schema(async_client: AsyncClient):
    """Reject requests with missing or empty url field."""
    res = await async_client.post("/api/v1/videos/from-url", json={})
    assert res.status_code == 422

    res2 = await async_client.post("/api/v1/videos/from-url", json={"url": ""})
    assert res2.status_code in [400, 422]


@pytest.mark.asyncio
async def test_from_url_unsupported_or_invalid_url(async_client: AsyncClient):
    """Return 400 when URL is not a valid HTTP/HTTPS video URL."""
    res = await async_client.post("/api/v1/videos/from-url", json={"url": "ftp://not-a-valid-url.mp4"})
    assert res.status_code == 400
    assert "Invalid URL" in res.json()["detail"]


@pytest.mark.asyncio
async def test_from_url_download_failure(async_client: AsyncClient):
    """Test URL ingestion enqueues processing and returns 202."""
    from app.services.task_queue import task_queue
    called = []
    with patch.object(task_queue, "enqueue_url_processing", lambda vid, url: called.append((vid, url))):
        res = await async_client.post(
            "/api/v1/videos/from-url",
            json={"url": "https://example.com/stream.mp4"}
        )
        assert res.status_code == 202
        data = res.json()
        assert "video_id" in data
        assert len(called) == 1


@pytest.mark.asyncio
async def test_from_url_success_flow(async_client: AsyncClient, tmp_path: Path):
    """Test successful asynchronous URL ingestion."""
    from app.services.task_queue import task_queue
    called = []
    with patch.object(task_queue, "enqueue_url_processing", lambda vid, url: called.append((vid, url))):
        res = await async_client.post(
            "/api/v1/videos/from-url",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        )

        assert res.status_code == 202
        data = res.json()
        assert "video_id" in data
        assert data["status"] == "processing"

        # Check status endpoint can read the queued/processing video
        status_res = await async_client.get(f"/api/v1/videos/{data['video_id']}/status")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "processing"
