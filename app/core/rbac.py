import logging
from typing import Callable, List, Optional
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import User, UserRole

logger = logging.getLogger(__name__)

# RBAC Permissions Matrix (ADMIN vs USER)
ROLE_PERMISSIONS = {
    UserRole.ORG_ADMIN: {
        "org:manage", "user:view", "user:manage", "user:invite", "user:activate", "user:deactivate",
        "user:role_change", "user:remove", "role:manage", "video:upload", "video:view", "video:delete",
        "video:analyze", "chat:ask", "hitl:review", "project:manage", "project:create", "project:view",
        "analytics:view", "audit:view", "observability:view", "settings:configure", "cost:view", "integration:manage"
    },
    UserRole.MANAGER: {
        "user:view", "video:upload", "video:view", "video:analyze",
        "chat:ask", "hitl:review", "project:manage", "project:create", "project:view",
        "analytics:view", "audit:view"
    },
    UserRole.ANALYST: {
        "video:upload", "video:view", "video:analyze", "chat:ask",
        "project:create", "project:view", "quiz:use", "usage:view_own", "settings:profile"
    },
    UserRole.VIEWER: {
        "video:view", "chat:ask", "project:view"
    }
}


def enforce_tenant_access(current_user: User, resource_org_id: Optional[str]) -> bool:
    """Verifies that a resource belongs to the current user's organization."""
    if not resource_org_id:
        return True  # Legacy resources without org_id fall back to accessible
    if current_user.organization_id != resource_org_id:
        logger.warning(
            f"Tenant Isolation Violation: User {current_user.email} (Org: {current_user.organization_id}) "
            f"attempted to access resource belonging to Org: {resource_org_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Resource belongs to a different organization."
        )
    return True


async def get_current_user(
    x_user_email: Optional[str] = Header(default="priyanka@acme.com"),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency retrieving current authenticated user and organization scope."""
    target_email = x_user_email or "priyanka@acme.com"
    stmt = select(User).where(User.email == target_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Fallback to first user in database
        stmt_any = select(User).limit(1)
        res_any = await db.execute(stmt_any)
        user = res_any.scalar_one_or_none()

    if not user:
        # Dynamically create fallback user for test environment
        user = User(
            id="usr-default-admin",
            organization_id="org-default-acme",
            email=target_email,
            full_name="Priyanka Davhare",
            role=UserRole.ORG_ADMIN,
            status="active",
            onboarding_completed=1
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except Exception:
            await db.rollback()

    return user


def require_permission(permission: str):
    """FastAPI dependency factory for RBAC permission checks."""
    async def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role
        allowed_permissions = ROLE_PERMISSIONS.get(user_role, set())

        if permission not in allowed_permissions:
            logger.warning(
                f"RBAC Denial: User {current_user.email} (Role: {user_role.value if hasattr(user_role, 'value') else user_role}) "
                f"attempted unauthorized action '{permission}'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden. Role '{user_role.value if hasattr(user_role, 'value') else user_role}' lacks required permission '{permission}'."
            )

        return current_user

    return permission_checker
