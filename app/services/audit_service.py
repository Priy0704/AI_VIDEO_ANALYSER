import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import AuditLog

logger = logging.getLogger(__name__)


async def log_audit_event(
    session: AsyncSession,
    organization_id: str,
    action: str,
    resource_type: str,
    user_id: Optional[str] = "usr-default-admin",
    user_email: Optional[str] = "priyanka@acme.com",
    resource_id: Optional[str] = None,
    details: Optional[str] = None,
    status: str = "success",
    ip_address: str = "127.0.0.1"
) -> AuditLog:
    """Record an immutable audit log entry."""
    try:
        log_entry = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            status=status,
            ip_address=ip_address
        )
        session.add(log_entry)
        await session.flush()
        return log_entry
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}")
        return None
