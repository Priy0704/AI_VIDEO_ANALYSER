from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.database import get_db
from app.db.models import Project, Video, User, Workspace
from app.core.rbac import get_current_user, require_permission
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/projects", tags=["Projects"])


class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = "#38bdf8"
    workspace_id: Optional[str] = None


@router.get("")
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all projects in current organization with video counts."""
    stmt = select(Project).where(Project.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    projects = res.scalars().all()

    result = []
    for prj in projects:
        count_stmt = select(func.count(Video.id)).where(Video.project_id == prj.id)
        c_res = await db.execute(count_stmt)
        video_count = c_res.scalar() or 0

        result.append({
            "id": prj.id,
            "name": prj.name,
            "description": prj.description,
            "color": prj.color,
            "workspace_id": prj.workspace_id,
            "video_count": video_count,
            "created_at": prj.created_at.isoformat()
        })

    return result


@router.post("")
async def create_project(
    req: ProjectCreateRequest,
    current_user: User = Depends(require_permission("project:create")),
    db: AsyncSession = Depends(get_db)
):
    """Create a new project."""
    ws_id = req.workspace_id
    if not ws_id:
        ws_stmt = select(Workspace.id).where(Workspace.organization_id == current_user.organization_id).limit(1)
        ws_res = await db.execute(ws_stmt)
        ws_id = ws_res.scalar_one_or_none() or "ws-default-prod"

    project = Project(
        organization_id=current_user.organization_id,
        workspace_id=ws_id,
        owner_id=current_user.id,
        name=req.name,
        description=req.description,
        color=req.color or "#38bdf8"
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    await log_audit_event(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        action="project.create",
        resource_type="project",
        resource_id=project.id,
        details=f"Created project {req.name}"
    )

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "color": project.color,
        "video_count": 0
    }


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: User = Depends(require_permission("project:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Delete a project."""
    stmt = select(Project).where(Project.id == project_id, Project.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await db.delete(project)
    await db.commit()

    return {"message": "Project deleted successfully"}
