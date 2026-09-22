from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.db.models import User
from app.core.rbac import get_current_user

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


class OnboardingUpdateRequest(BaseModel):
    onboarding_completed: bool
    use_case: Optional[str] = None


@router.get("/status")
async def get_onboarding_status(
    current_user: User = Depends(get_current_user)
):
    """Get onboarding completion status for user."""
    return {
        "user_id": current_user.id,
        "onboarding_completed": bool(current_user.onboarding_completed),
        "use_case": current_user.use_case
    }


@router.post("/status")
async def update_onboarding_status(
    req: OnboardingUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Save onboarding completion or restart onboarding."""
    current_user.onboarding_completed = 1 if req.onboarding_completed else 0
    if req.use_case:
        current_user.use_case = req.use_case

    await db.commit()
    return {
        "message": "Onboarding status updated",
        "onboarding_completed": bool(current_user.onboarding_completed),
        "use_case": current_user.use_case
    }
