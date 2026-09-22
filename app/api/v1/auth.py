from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import User, Organization, Workspace
from app.core.rbac import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth & Identity"])


@router.get("/me")
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user context, organization, workspace, and permissions."""
    stmt_org = select(Organization).where(Organization.id == current_user.organization_id)
    org_res = await db.execute(stmt_org)
    org = org_res.scalar_one_or_none()

    stmt_ws = select(Workspace).where(Workspace.organization_id == current_user.organization_id)
    ws_res = await db.execute(stmt_ws)
    workspaces = ws_res.scalars().all()

    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role.value if hasattr(current_user.role, 'value') else current_user.role,
        "onboarding_completed": bool(current_user.onboarding_completed),
        "use_case": current_user.use_case,
        "organization": {
            "id": org.id if org else None,
            "name": org.name if org else "Acme Corporation",
            "slug": org.slug if org else "acme-corp",
            "plan": org.plan if org else "Enterprise"
        },
        "workspaces": [
            {"id": ws.id, "name": ws.name, "description": ws.description}
            for ws in workspaces
        ]
    }
