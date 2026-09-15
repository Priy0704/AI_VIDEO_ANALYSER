from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db.database import get_db

router = APIRouter(tags=["Health & Readiness"])


@router.get("/health", status_code=status.HTTP_200_OK, summary="Liveness probe")
async def health():
    """Liveness probe: returns 200 OK if service is up."""
    return {"status": "healthy", "service": "AI Video Analyser & Chat"}


@router.get("/ready", summary="Readiness probe")
async def ready(response: Response, db: AsyncSession = Depends(get_db)):
    """Readiness probe: checks database connectivity and returns 200 or 503."""
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected"
        }
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "database": f"error: {str(e)}"
        }
