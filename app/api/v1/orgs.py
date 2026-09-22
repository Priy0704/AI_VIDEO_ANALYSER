from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.db.models import Organization, Workspace, User, UserRole
from app.core.rbac import get_current_user, require_permission
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/orgs", tags=["Organizations & Team"])


class UserInviteRequest(BaseModel):
    email: str
    full_name: str
    role: str = "analyst"


class WorkspaceCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None


@router.get("/users")
async def list_org_users(
    current_user: User = Depends(require_permission("user:view")),
    db: AsyncSession = Depends(get_db)
):
    """List all team users within the organization."""
    stmt = select(User).where(User.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    users = res.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, 'value') else u.role,
            "onboarding_completed": bool(u.onboarding_completed),
            "created_at": u.created_at.isoformat()
        }
        for u in users
    ]


@router.post("/users/invite")
async def invite_user(
    req: UserInviteRequest,
    current_user: User = Depends(require_permission("user:invite")),
    db: AsyncSession = Depends(get_db)
):
    """Invite a new team user to the organization."""
    # Check existing user
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User with this email already exists.")

    try:
        role_enum = UserRole(req.role)
    except ValueError:
        role_enum = UserRole.ANALYST

    new_user = User(
        organization_id=current_user.organization_id,
        email=req.email,
        full_name=req.full_name,
        role=role_enum,
        onboarding_completed=0
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    await log_audit_event(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        action="user.invite",
        resource_type="user",
        resource_id=new_user.id,
        details=f"Invited user {req.email} as {role_enum.value}"
    )

    return {
        "id": new_user.id,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role.value if hasattr(new_user.role, 'value') else new_user.role,
        "status": "Invited"
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: str,
    current_user: User = Depends(require_permission("role:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Update role for a user."""
    stmt = select(User).where(User.id == user_id, User.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    try:
        role_enum = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role specified.")

    old_role = target_user.role
    target_user.role = role_enum
    await db.commit()

    await log_audit_event(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        action="user.role_change",
        resource_type="user",
        resource_id=target_user.id,
        details=f"Changed role for {target_user.email} from {old_role} to {role_enum.value}"
    )

    return {"message": "User role updated successfully", "user_id": target_user.id, "new_role": role_enum.value}


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    status_val: str,
    current_user: User = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Activate or deactivate a user account."""
    stmt = select(User).where(User.id == user_id, User.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    target_user.status = "active" if status_val.lower() == "active" else "inactive"
    await db.commit()

    await log_audit_event(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        action="user.status_change",
        resource_type="user",
        resource_id=target_user.id,
        details=f"Updated status for {target_user.email} to {target_user.status}"
    )

    return {"message": f"User status updated to {target_user.status}", "user_id": target_user.id, "status": target_user.status}


@router.delete("/users/{user_id}")
async def remove_user(
    user_id: str,
    current_user: User = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Remove a user from the organization."""
    stmt = select(User).where(User.id == user_id, User.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    await db.delete(target_user)
    await db.commit()

    await log_audit_event(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        action="user.remove",
        resource_type="user",
        resource_id=user_id,
        details=f"Removed user {target_user.email} from organization"
    )

    return {"message": "User removed successfully", "user_id": user_id}


@router.get("/workspaces")
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List workspaces in organization."""
    stmt = select(Workspace).where(Workspace.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    workspaces = res.scalars().all()
    return [
        {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "created_at": ws.created_at.isoformat()
        }
        for ws in workspaces
    ]


@router.post("/workspaces")
async def create_workspace(
    req: WorkspaceCreateRequest,
    current_user: User = Depends(require_permission("org:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Create a new workspace."""
    ws = Workspace(
        organization_id=current_user.organization_id,
        name=req.name,
        description=req.description
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return {"id": ws.id, "name": ws.name, "description": ws.description}
