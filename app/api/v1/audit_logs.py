from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import AuditLog, User
from app.core.rbac import get_current_user, require_permission

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("")
async def list_audit_logs(
    user_email: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(require_permission("audit:view")),
    db: AsyncSession = Depends(get_db)
):
    """List audit log trail with optional multi-attribute filters."""
    stmt = select(AuditLog).where(AuditLog.organization_id == current_user.organization_id)

    if user_email:
        stmt = stmt.where(AuditLog.user_email == user_email)
    if action:
        stmt = stmt.where(AuditLog.action == action)

    stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit)
    res = await db.execute(stmt)
    logs = res.scalars().all()

    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "user_email": log.user_email or "system@videointel.ai",
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "status": log.status,
            "ip_address": log.ip_address
        }
        for log in logs
    ]
