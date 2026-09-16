import asyncio
import logging
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
import yt_dlp

logger = logging.getLogger(__name__)


def _get_ffmpeg_executable() -> Optional[str]:
    """Find or prepare ffmpeg executable from imageio_ffmpeg or system PATH."""
    try:
        import imageio_ffmpeg
        raw_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if raw_exe and os.path.exists(raw_exe):
            bin_dir = os.path.dirname(raw_exe)
            target_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
            target_path = os.path.join(bin_dir, target_name)
            if not os.path.exists(target_path):
                shutil.copyfile(raw_exe, target_path)
            return target_path
    except Exception as e:
        logger.debug(f"Could not load ffmpeg from imageio_ffmpeg: {e}")

    return shutil.which("ffmpeg")


class UrlDownloader:
    """Service to fetch and download videos from any URL: YouTube, Zoom/Meeting recordings, Camera RTSP/HTTP feeds, and direct files."""

    def __init__(self, download_dir: Path):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = _get_ffmpeg_executable()

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to avoid OS path conflicts."""
        return re.sub(r'[^\w\-_\. ]', '_', filename).strip()

    def _download_via_ffmpeg(self, url: str) -> Dict[str, Any]:
        """Capture or download a video from camera feeds (RTSP/RTMP), HLS streams, or direct video file URLs using FFmpeg."""
        ffmpeg_bin = self.ffmpeg_path or "ffmpeg"
        unique_id = uuid.uuid4().hex[:8]
        out_name = f"stream_{unique_id}.mp4"
        out_path = self.download_dir / out_name

        logger.info(f"Attempting direct FFmpeg stream capture for URL: {url}")
        cmd_copy = [
            ffmpeg_bin, "-y",
            "-i", url,
            "-t", "3600",
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path)
        ]

        try:
            res = subprocess.run(cmd_copy, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
            if res.returncode != 0 or not out_path.exists() or os.path.getsize(out_path) == 0:
                # Transcode if copy failed due to stream codecs
                cmd_transcode = [
                    ffmpeg_bin, "-y",
                    "-i", url,
                    "-t", "3600",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                subprocess.run(cmd_transcode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        except Exception as e:
            logger.error(f"FFmpeg stream capture error for '{url}': {e}")
            raise ValueError(f"Failed to capture video stream from URL: {e}")

        if not out_path.exists() or os.path.getsize(out_path) == 0:
            raise ValueError(f"Could not retrieve a playable video stream from: {url}")

        file_size_mb = os.path.getsize(out_path) / (1024 * 1024)
        duration = 0.0
        try:
            import cv2
            cap = cv2.VideoCapture(str(out_path))
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
                duration = frames / fps if fps > 0 else 0.0
                cap.release()
        except Exception as e:
            logger.debug(f"Could not probe duration via cv2: {e}")

        clean_title = Path(url.split("?")[0]).stem or f"Stream_{unique_id}"
        return {
            "file_path": str(out_path.resolve()),
            "filename": out_name,
            "title": clean_title,
            "duration_seconds": round(duration, 2),
            "file_size_mb": round(file_size_mb, 2),
            "thumbnail_url": None
        }

    def _sync_download(self, url: str) -> Dict[str, Any]:
        """Synchronous worker function supporting any video URL: web platforms, meeting links, camera feeds, or direct files."""
        url_l = url.strip().lower()
        if not (url_l.startswith("http://") or url_l.startswith("https://") or url_l.startswith("rtsp://") or url_l.startswith("rtmp://")):
            raise ValueError("Invalid URL: must start with http://, https://, or rtsp://")

        # Detect internal authenticated Microsoft Teams chat/meeting/SharePoint links
        teams_domains = [
            "teams.cloud.microsoft", "teams.microsoft.com", "teams.live.com",
            "sharepoint.com", "onedrive.live.com", "1drv.ms"
        ]
        if any(d in url_l for d in teams_domains):
            raise ValueError(
                "This link is a private corporate Microsoft Teams / SharePoint link that requires Microsoft 365 Single Sign-On (SSO) login.\n\n"
                "External services cannot log into your private corporate Microsoft account.\n\n"
                "👉 How to analyze this meeting video:\n"
                "1. In Teams or SharePoint, click the three dots (...) or top menu on the recording and select 'Download' (saves as .mp4).\n"
                "2. Click the '📁 Local File' tab on the left and upload your video file for instant analysis!"
            )

        # Directly use FFmpeg for RTSP/RTMP security and IP camera streams
        if url_l.startswith("rtsp://") or url_l.startswith("rtmp://"):
            return self._download_via_ffmpeg(url)

        ydl_opts: Dict[str, Any] = {
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(self.download_dir / '%(id)s_%(title).60B.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,  # Bypass corporate SSL MITM / proxy interception certificates
            'windowsfilenames': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web']
                }
            },
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }

        if self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_path

        # Support optional cookies.txt if user exports authenticated session cookies
        cookie_file = Path("cookies.txt")
        if cookie_file.exists():
            ydl_opts['cookiefile'] = str(cookie_file.resolve())

        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as yt_err:
            err_str = str(yt_err)
            if any(d in url_l for d in teams_domains):
                raise ValueError(
                    "This link is an internal Microsoft Teams / SharePoint link that requires corporate login.\n\n"
                    "Please download the video (.mp4) from Teams and upload it via the '📁 Local File' tab."
                )
            logger.warning(f"yt-dlp could not process URL '{url}' directly ({yt_err}). Falling back to stream capture...")
            # Fallback to direct stream/file capture via FFmpeg (for direct camera feeds, custom IP cams, or CDN file links)
            try:
                return self._download_via_ffmpeg(url)
            except Exception:
                if "Unsupported URL" in err_str:
                    raise ValueError(
                        f"This URL is not a supported direct video stream. "
                        f"If this is a private or login-protected page (e.g. Teams, Zoom with password, or Google Drive), "
                        f"please download the video (.mp4 / .mov) to your device and upload it via the '📁 Local File' tab!"
                    )
                raise ValueError(f"Failed to download video from URL: {str(yt_err)}")

        if not info:
            try:
                return self._download_via_ffmpeg(url)
            except Exception:
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
            "file_path": str(Path(downloaded_file).resolve()),
            "filename": filename,
            "title": title,
            "duration_seconds": duration,
            "file_size_mb": round(file_size_mb, 2),
            "thumbnail_url": info.get('thumbnail')
        }

    async def download_video(self, url: str) -> Dict[str, Any]:
        """Asynchronously download video from any supported URL without blocking FastAPI event loop."""
        return await asyncio.to_thread(self._sync_download, url)
