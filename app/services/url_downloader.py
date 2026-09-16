import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Dict, Any
import yt_dlp

logger = logging.getLogger(__name__)


class UrlDownloader:
    """Service to fetch and download videos from YouTube and supported web URLs via yt-dlp."""

    def __init__(self, download_dir: Path):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to avoid OS path conflicts."""
        return re.sub(r'[^\w\-_\. ]', '_', filename).strip()

    def _sync_download(self, url: str) -> Dict[str, Any]:
        """Synchronous worker function to download video with yt-dlp."""
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("Invalid URL: must start with http:// or https://")

        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(self.download_dir / '%(id)s_%(title).60B.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as de:
                logger.error(f"yt-dlp download failed for URL '{url}': {de}")
                raise ValueError(f"Failed to download video from URL: {str(de)}")
            except Exception as e:
                logger.error(f"Unexpected error downloading URL '{url}': {e}")
                raise ValueError(f"Failed to process video URL: {str(e)}")

        if not info:
            raise ValueError("No video metadata could be extracted from URL.")

        downloaded_file = ydl.prepare_filename(info)
        # In case postprocessor changed extension to .mp4
        if not os.path.exists(downloaded_file):
            base, _ = os.path.splitext(downloaded_file)
            if os.path.exists(f"{base}.mp4"):
                downloaded_file = f"{base}.mp4"

        if not os.path.exists(downloaded_file):
            raise FileNotFoundError(f"Expected downloaded video file not found: {downloaded_file}")

        file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
        title = info.get('title') or Path(downloaded_file).stem
        duration = float(info.get('duration') or 0.0)
        filename = Path(downloaded_file).name

        return {
            "file_path": downloaded_file,
            "filename": filename,
            "title": title,
            "duration_seconds": duration,
            "file_size_mb": round(file_size_mb, 2),
            "thumbnail_url": info.get('thumbnail')
        }

    async def download_video(self, url: str) -> Dict[str, Any]:
        """Asynchronously download video from URL without blocking FastAPI event loop."""
        return await asyncio.to_thread(self._sync_download, url)
