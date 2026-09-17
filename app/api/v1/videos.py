import os
import asyncio
import mimetypes
import shutil
import logging
from pathlib import Path
from typing import List
from fastapi import APIRouter, UploadFile, File, Depends, status, Query, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.db.database import get_db
from app.db.models import Video, VideoStatus, VideoSegment
from app.schemas.video import (
    VideoUrlRequest,
    VideoUploadResponse,
    VideoStatusResponse,
    VideoDetailResponse,
    VideoSegmentResponse
)
from app.core.exceptions import (
    VideoNotFoundError,
    InvalidFileFormatError,
    FileTooLargeError
)
from app.services.task_queue import task_queue
from app.services.url_downloader import UrlDownloader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["Videos"])


async def _save_uploaded_file_fast(file: UploadFile, saved_path: Path) -> int:
    """Save an UploadFile to disk using high-throughput I/O with 16MB buffers and native worker threads."""
    underlying = getattr(file, "file", None)
    underlying_file = getattr(underlying, "_file", None) or getattr(underlying, "file", None) or underlying

    # Check if SpooledTemporaryFile has already rolled over to a temp file on disk (standard for >1MB)
    if underlying_file and hasattr(underlying_file, "name") and os.path.exists(str(underlying_file.name)):
        def _copy_disk():
            try:
                underlying_file.seek(0)
            except Exception:
                pass
            with open(saved_path, "wb") as dst:
                shutil.copyfileobj(underlying_file, dst, length=16 * 1024 * 1024)
            return os.path.getsize(saved_path)

        return await asyncio.to_thread(_copy_disk)

    # Otherwise stream chunked in 16MB blocks
    total_bytes = 0
    with open(saved_path, "wb") as buffer:
        while chunk := await file.read(16 * 1024 * 1024):
            total_bytes += len(chunk)
            if (total_bytes / (1024 * 1024)) > settings.MAX_VIDEO_SIZE_MB:
                raise FileTooLargeError(total_bytes / (1024 * 1024), settings.MAX_VIDEO_SIZE_MB)
            buffer.write(chunk)
    return total_bytes


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a video for asynchronous processing"
)
async def upload_video(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Ingests an arbitrary video file (MP4, MOV, MKV, AVI).
    Saves file to disk using high-speed 16MB buffering, creates database record, and queues processing asynchronously.
    Returns immediately with 202 Accepted and the video_id.
    """
    clean_filename = Path(file.filename or "video.mp4").name
    file_ext = Path(clean_filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise InvalidFileFormatError(clean_filename, settings.ALLOWED_EXTENSIONS)

    temp_video_id = os.urandom(8).hex()
    saved_filename = f"{temp_video_id}_{clean_filename}"
    saved_path = settings.UPLOAD_DIR / saved_filename

    try:
        total_bytes = await _save_uploaded_file_fast(file, saved_path)
    except FileTooLargeError:
        if saved_path.exists():
            saved_path.unlink(missing_ok=True)
        raise
    except Exception as err:
        if saved_path.exists():
            saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed writing video file to storage: {str(err)}"
        )

    # Create video record in PostgreSQL
    video = Video(
        filename=clean_filename,
        file_path=str(saved_path.resolve()),
        file_size_bytes=total_bytes,
        status=VideoStatus.QUEUED,
        progress_pct=0,
        current_stage="Queued"
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    # Enqueue background pipeline
    task_queue.enqueue_video_processing(video.id, saved_path)

    return VideoUploadResponse(
        video_id=video.id,
        filename=video.filename,
        status=video.status,
        message="Video accepted and queued for multimodal processing."
    )


@router.post(
    "/upload-batch",
    response_model=List[VideoUploadResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload multiple videos simultaneously in one batch"
)
async def upload_multiple_videos(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Accepts 1 to 10 video files at once.
    Saves all files to disk using fast concurrent streaming,
    registers all records in PostgreSQL, and queues background processing for all of them.
    Returns within seconds with all video IDs.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided for upload.")

    responses = []
    saved_pairs = []

    for file in files:
        clean_filename = Path(file.filename or "video.mp4").name
        file_ext = Path(clean_filename).suffix.lower()
        if file_ext not in settings.ALLOWED_EXTENSIONS:
            continue

        temp_video_id = os.urandom(8).hex()
        saved_filename = f"{temp_video_id}_{clean_filename}"
        saved_path = settings.UPLOAD_DIR / saved_filename

        try:
            total_bytes = await _save_uploaded_file_fast(file, saved_path)
            video = Video(
                filename=clean_filename,
                file_path=str(saved_path.resolve()),
                file_size_bytes=total_bytes,
                status=VideoStatus.QUEUED,
                progress_pct=0,
                current_stage="Queued"
            )
            db.add(video)
            saved_pairs.append((video, saved_path))
        except Exception as err:
            logger.error(f"Failed to save batch file {clean_filename}: {err}")
            if saved_path.exists():
                saved_path.unlink(missing_ok=True)

    if not saved_pairs:
        raise HTTPException(
            status_code=400,
            detail="None of the uploaded files have valid extensions (.mp4, .mov, .mkv, .avi)."
        )

    await db.commit()

    for video, saved_path in saved_pairs:
        await db.refresh(video)
        task_queue.enqueue_video_processing(video.id, saved_path)
        responses.append(
            VideoUploadResponse(
                video_id=video.id,
                filename=video.filename,
                status=video.status,
                message="Video accepted and queued for multimodal processing."
            )
        )

    return responses


@router.post(
    "/from-url",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Download and ingest a video from YouTube, Zoom, meeting recordings, camera streams, or web URLs"
)
@router.post(
    "/from-url/",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False
)
async def ingest_video_from_url(
    payload: VideoUrlRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Downloads and ingests a video from any URL (YouTube, Zoom/Meeting recordings, Camera RTSP/HTTP streams, or direct files),
    validates the link instantly, creates a database record, and runs downloading and multimodal indexing in the background.
    """
    url_clean = (payload.url or "").strip()
    url_l = url_clean.lower()
    if not (url_l.startswith("http://") or url_l.startswith("https://") or url_l.startswith("rtsp://") or url_l.startswith("rtmp://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL: URL must begin with http://, https://, or rtsp:// (for camera streams)"
        )

    teams_domains = [
        "teams.cloud.microsoft", "teams.microsoft.com", "teams.live.com",
        "sharepoint.com", "onedrive.live.com", "1drv.ms"
    ]
    if any(d in url_l for d in teams_domains):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This link is a private corporate Microsoft Teams / SharePoint link that requires Microsoft 365 Single Sign-On (SSO) login.\n\n"
                "External services cannot log into your private corporate Microsoft account.\n\n"
                "👉 How to analyze this meeting video:\n"
                "1. In Teams or SharePoint, click the three dots (...) or top menu on the recording and select 'Download' (saves as .mp4).\n"
                "2. Click the '📁 Local File' tab on the left and upload your video file for instant analysis!"
            )
        )

    # Derive human-friendly filename placeholder from URL
    path_stem = Path(url_clean.split("?")[0]).name
    clean_title = path_stem if (path_stem and len(path_stem) > 3) else f"stream_{os.urandom(4).hex()}.mp4"

    # Create video record in PostgreSQL immediately with PROCESSING state
    video = Video(
        filename=clean_title,
        file_path="",
        file_size_bytes=0,
        status=VideoStatus.PROCESSING,
        progress_pct=5,
        current_stage="Connecting & downloading video stream from link..."
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    # Enqueue background pipeline that downloads and runs multimodal analysis
    task_queue.enqueue_url_processing(video.id, url_clean)

    return VideoUploadResponse(
        video_id=video.id,
        filename=video.filename,
        status=video.status,
        message="Video URL accepted. Downloading stream and running multimodal analysis in background."
    )


@router.get(
    "/{video_id}/status",
    response_model=VideoStatusResponse,
    summary="Get processing status and progress"
)
async def get_video_status(
    video_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Poll the real-time processing status of a video."""
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    return VideoStatusResponse(
        video_id=video.id,
        filename=video.filename,
        status=video.status,
        progress_pct=video.progress_pct,
        current_stage=video.current_stage,
        error_message=video.error_message,
        duration_seconds=video.duration_seconds,
        video_type=getattr(video, "video_type", "knowledge") or "knowledge",
        video_type_label=getattr(video, "video_type_label", "Learning / Knowledge Content") or "Learning / Knowledge Content",
        video_type_confidence=getattr(video, "video_type_confidence", 0.90) or 0.90,
        video_type_reason=getattr(video, "video_type_reason", None),
        created_at=video.created_at,
        updated_at=video.updated_at
    )


@router.get(
    "",
    response_model=List[VideoStatusResponse],
    summary="List all videos"
)
async def list_videos(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List all ingested videos ordered by most recent."""
    stmt = select(Video).order_by(Video.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    videos = result.scalars().all()
    return [
        VideoStatusResponse(
            video_id=v.id,
            filename=v.filename,
            status=v.status,
            progress_pct=v.progress_pct,
            current_stage=v.current_stage,
            error_message=v.error_message,
            duration_seconds=v.duration_seconds,
            video_type=getattr(v, "video_type", "knowledge") or "knowledge",
            video_type_label=getattr(v, "video_type_label", "Learning / Knowledge Content") or "Learning / Knowledge Content",
            video_type_confidence=getattr(v, "video_type_confidence", 0.90) or 0.90,
            video_type_reason=getattr(v, "video_type_reason", None),
            created_at=v.created_at,
            updated_at=v.updated_at
        )
        for v in videos
    ]


@router.get(
    "/{video_id}",
    response_model=VideoDetailResponse,
    summary="Get video details and all indexed segments"
)
async def get_video_detail(
    video_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get full video information along with all indexed multimodal segments."""
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    stmt = select(VideoSegment).where(VideoSegment.video_id == video_id).order_by(VideoSegment.start_time)
    result = await db.execute(stmt)
    segments = result.scalars().all()

    return VideoDetailResponse(
        id=video.id,
        filename=video.filename,
        duration_seconds=video.duration_seconds,
        status=video.status,
        progress_pct=video.progress_pct,
        summary=video.summary,
        video_type=getattr(video, "video_type", "knowledge") or "knowledge",
        video_type_label=getattr(video, "video_type_label", "Learning / Knowledge Content") or "Learning / Knowledge Content",
        video_type_confidence=getattr(video, "video_type_confidence", 0.90) or 0.90,
        video_type_reason=getattr(video, "video_type_reason", None),
        raw_transcripts=video.raw_transcripts or [],
        created_at=video.created_at,
        segments_count=len(segments),
        segments=[
            VideoSegmentResponse(
                id=s.id,
                start_time=s.start_time,
                end_time=s.end_time,
                transcript_text=s.transcript_text,
                visual_description=s.visual_description,
                combined_text=s.combined_text
            )
            for s in segments
        ]
    )


@router.delete(
    "/{video_id}",
    summary="Delete video and all associated segments and files"
)
async def delete_video(
    video_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a video, cascading to its segments, sessions, reviews, and removing stored files."""
    # Cancel any active running or queued background task
    task_queue.cancel_task(video_id)

    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    # Delete video file from storage
    try:
        p = Path(video.file_path)
        if p.exists():
            p.unlink(missing_ok=True)
    except Exception:
        pass

    # Delete keyframes directory from storage
    try:
        kf_dir = Path(settings.KEYFRAME_DIR) / video_id
        if kf_dir.exists():
            shutil.rmtree(kf_dir, ignore_errors=True)
    except Exception:
        pass

    await db.delete(video)
    await db.commit()

    return {"status": "deleted", "video_id": video_id}


@router.post(
    "/clear-failed",
    summary="Clear all failed or abandoned test video entries"
)
async def clear_failed_videos(
    db: AsyncSession = Depends(get_db)
):
    """Clean up all videos marked as failed."""
    stmt = select(Video).where(Video.status == VideoStatus.FAILED)
    result = await db.execute(stmt)
    failed_videos = result.scalars().all()
    count = len(failed_videos)
    for v in failed_videos:
        task_queue.cancel_task(v.id)
        try:
            if v.file_path and Path(v.file_path).exists():
                Path(v.file_path).unlink(missing_ok=True)
        except Exception:
            pass
        await db.delete(v)
    await db.commit()
    return {"deleted_count": count}


@router.get(
    "/{video_id}/stream",
    summary="Stream video file with HTTP range request support"
)
async def stream_video(
    video_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Stream video with HTTP 206 partial content support for synced browser seeking."""
    video = await db.get(Video, video_id)
    if not video:
        raise VideoNotFoundError(video_id)

    path = Path(video.file_path)
    if not path.exists():
        raise VideoNotFoundError(video_id)

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    media_type = mimetypes.guess_type(str(path))[0] or "video/mp4"

    if range_header:
        # Parse byte range: "bytes=start-end"
        byte1, byte2 = 0, None
        match = range_header.replace("bytes=", "").split("-")
        if match[0]:
            byte1 = int(match[0])
        if len(match) > 1 and match[1]:
            byte2 = int(match[1])

        length = file_size - byte1 if byte2 is None else (byte2 - byte1) + 1

        def iterfile():
            with open(path, "rb") as f:
                f.seek(byte1)
                remaining = length
                while remaining > 0:
                    chunk_size = min(256 * 1024, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {byte1}-{byte1 + length - 1}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": media_type,
        }
        return StreamingResponse(iterfile(), status_code=206, headers=headers)

    def iterfile_full():
        with open(path, "rb") as f:
            while chunk := f.read(256 * 1024):
                yield chunk

    return StreamingResponse(
        iterfile_full(),
        media_type=media_type,
        headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"}
    )
