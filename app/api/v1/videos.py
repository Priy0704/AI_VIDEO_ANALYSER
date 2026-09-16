import os
import mimetypes
import shutil
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

router = APIRouter(prefix="/videos", tags=["Videos"])


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
    Saves file to disk, creates database record, and queues processing asynchronously.
    Returns immediately with 202 Accepted and the video_id.
    """
    clean_filename = Path(file.filename or "video.mp4").name
    file_ext = Path(clean_filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise InvalidFileFormatError(clean_filename, settings.ALLOWED_EXTENSIONS)

    # Temporary write to check size and persist
    temp_video_id = os.urandom(8).hex()
    saved_filename = f"{temp_video_id}_{clean_filename}"
    saved_path = settings.UPLOAD_DIR / saved_filename

    total_bytes = 0
    too_large = False
    try:
        # Stream in 8MB chunks for fast I/O throughput with large (up to 50 GB) videos
        upload_chunk_size = 8 * 1024 * 1024
        with open(saved_path, "wb") as buffer:
            while chunk := await file.read(upload_chunk_size):
                total_bytes += len(chunk)
                size_mb = total_bytes / (1024 * 1024)
                if size_mb > settings.MAX_VIDEO_SIZE_MB:
                    too_large = True
                    break
                buffer.write(chunk)
    except Exception as err:
        try:
            if saved_path.exists():
                saved_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed writing video file to storage: {str(err)}"
        )

    if too_large:
        try:
            if saved_path.exists():
                saved_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise FileTooLargeError(total_bytes / (1024 * 1024), settings.MAX_VIDEO_SIZE_MB)

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
    "/from-url",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Download and ingest a video from YouTube, Zoom, meeting recordings, camera streams, or web URLs"
)
async def ingest_video_from_url(
    payload: VideoUrlRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Downloads and ingests a video from any URL (YouTube, Zoom/Meeting recordings, Camera RTSP/HTTP streams, or direct files),
    saves the MP4 stream, creates a database record, and queues multimodal processing.
    """
    downloader = UrlDownloader(download_dir=settings.UPLOAD_DIR)
    try:
        download_info = await downloader.download_video(payload.url)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch video: {str(e)}"
        )

    file_path = Path(download_info["file_path"])
    total_bytes = int(download_info["file_size_mb"] * 1024 * 1024)

    # Create video record in PostgreSQL
    video = Video(
        filename=download_info["filename"],
        file_path=str(file_path.resolve()),
        file_size_bytes=total_bytes,
        duration_seconds=download_info.get("duration_seconds"),
        status=VideoStatus.QUEUED,
        progress_pct=0,
        current_stage="Queued"
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    # Enqueue background multimodal processing
    task_queue.enqueue_video_processing(video.id, file_path)

    return VideoUploadResponse(
        video_id=video.id,
        filename=video.filename,
        status=video.status,
        message=f"Video '{download_info['title']}' fetched and queued for multimodal processing."
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
