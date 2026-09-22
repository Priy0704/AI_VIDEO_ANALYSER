from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.database import get_db
from app.db.models import ProcessingCostRecord, User, Video
from app.core.rbac import get_current_user
from app.services.cost_service import cost_service

router = APIRouter(prefix="/costs", tags=["Cost Estimation & Ledger"])


@router.get("/estimate")
async def estimate_video_cost(
    duration_seconds: float = Query(..., description="Duration of video in seconds"),
    db: AsyncSession = Depends(get_db)
):
    """Estimate AI processing cost before video upload."""
    return await cost_service.estimate_video_cost(duration_seconds, db)


@router.get("/quick-benchmarks")
async def get_quick_cost_benchmarks(
    db: AsyncSession = Depends(get_db)
):
    """Get quick benchmark estimates for 1, 5, 30, and 60 minute video durations."""
    estimates = await cost_service.calculate_quick_estimates(db)
    rates = await cost_service.get_pricing_rates(db)
    return {
        "benchmarks": estimates,
        "pricing_rates": rates,
        "note": "Actual cost depends on model, resolution, sampling, token usage and enabled processing stages."
    }


@router.get("/summary")
async def get_cost_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated cost summary for organization."""
    q_cost = select(
        func.coalesce(func.sum(ProcessingCostRecord.actual_cost), 0.0),
        func.coalesce(func.sum(ProcessingCostRecord.input_tokens), 0),
        func.coalesce(func.sum(ProcessingCostRecord.output_tokens), 0),
        func.count(ProcessingCostRecord.id)
    ).where(ProcessingCostRecord.organization_id == current_user.organization_id)

    res = await db.execute(q_cost)
    total_cost, total_in_tokens, total_out_tokens, records_count = res.first()

    return {
        "organization_id": current_user.organization_id,
        "total_cost_usd": round(total_cost, 4),
        "total_input_tokens": total_in_tokens,
        "total_output_tokens": total_out_tokens,
        "total_processing_operations": records_count
    }
