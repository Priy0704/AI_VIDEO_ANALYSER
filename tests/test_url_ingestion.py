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
    """Return 400 when UrlDownloader raises ValueError."""
    with patch("app.api.v1.videos.UrlDownloader.download_video", side_effect=ValueError("Unsupported video site")):
        res = await async_client.post(
            "/api/v1/videos/from-url",
            json={"url": "https://example.com/unsupported"}
        )
        assert res.status_code == 400
        assert "Unsupported video site" in res.json()["detail"]


@pytest.mark.asyncio
async def test_from_url_success_flow(async_client: AsyncClient, tmp_path: Path):
    """Test successful ingestion from YouTube/URL with mocked yt-dlp download."""
    fake_video_file = tmp_path / "mock_downloaded.mp4"
    fake_video_file.write_bytes(b"dummy mp4 content for testing")

    mock_download_result = {
        "file_path": str(fake_video_file),
        "filename": "mock_downloaded.mp4",
        "title": "Sample YouTube Lecture",
        "duration_seconds": 45.0,
        "file_size_mb": 0.05,
    }

    with patch("app.api.v1.videos.UrlDownloader.download_video", new=AsyncMock(return_value=mock_download_result)), \
         patch("app.api.v1.videos.task_queue.enqueue_video_processing") as mock_enqueue:

        res = await async_client.post(
            "/api/v1/videos/from-url",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        )

        assert res.status_code == 202
        data = res.json()
        assert "video_id" in data
        assert data["filename"] == "mock_downloaded.mp4"
        assert data["status"] == "queued"
        assert "Sample YouTube Lecture" in data["message"]

        # Ensure task queue received video processing job
        mock_enqueue.assert_called_once()

        # Check status endpoint can read the queued video
        status_res = await async_client.get(f"/api/v1/videos/{data['video_id']}/status")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "queued"
        assert status_res.json()["duration_seconds"] == 45.0
