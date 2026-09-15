import pytest
import asyncio
import cv2
import numpy as np
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from app.services.task_queue import task_queue


@pytest.fixture(scope="session")
def event_loop():
    """Create a single session-wide event loop for all tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Ensure data directories exist and run tests offline to preserve API quota."""
    settings.init_storage()
    settings.GEMINI_API_KEY = None


@pytest.fixture
def sample_mp4(tmp_path) -> Path:
    """Generate a real, valid MP4 video file (3 seconds, 10 fps) with visual elements."""
    video_path = tmp_path / "test_sample.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = 10.0
    width, height = 320, 240
    out = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))

    for i in range(30):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (25, 35, 55)
        cx = int(40 + (i * 8)) % width
        cv2.circle(frame, (cx, 120), 18, (0, 255, 255), -1)
        cv2.putText(frame, f"T: {i/fps:.1f}s", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        out.write(frame)

    out.release()
    return video_path


@pytest.fixture
async def async_client():
    """Asynchronous HTTP test client for FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Wait for any running background tasks before tear down
    if task_queue.active_tasks:
        await asyncio.gather(*task_queue.active_tasks.values(), return_exceptions=True)
