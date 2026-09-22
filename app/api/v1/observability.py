from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.db.models import User
from app.core.rbac import get_current_user, require_permission
from app.services.observability_service import observability_service

router = APIRouter(prefix="/observability", tags=["Observability & System Ops"])


@router.get("/metrics")
async def get_observability_metrics(
    current_user: User = Depends(require_permission("observability:view")),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve operational backend metrics, queue depth, stage bottlenecks, system health, and AI latency."""
    health = await observability_service.get_system_health(db)
    proc_metrics = await observability_service.get_processing_metrics(db, current_user.organization_id)
    ai_metrics = await observability_service.get_ai_and_hitl_metrics(db, current_user.organization_id)

    return {
        "system_health": health,
        "processing_pipeline": proc_metrics,
        "ai_provider_metrics": ai_metrics,
        "organization_id": current_user.organization_id
    }
