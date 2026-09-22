import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import ProcessingCostRecord, SystemConfig

logger = logging.getLogger(__name__)

# Default Enterprise Pricing Rates (Configurable via DB or API)
DEFAULT_PRICING = {
    "audio_asr_per_min": 0.006,        # $0.006 / min whisper/ASR
    "vision_per_min": 0.015,           # $0.015 / min keyframe vision
    "ocr_per_min": 0.004,              # $0.004 / min OCR extraction
    "vector_index_per_min": 0.002,     # $0.002 / min vector embedding indexing
    "gemini_input_per_1k": 0.000125,   # $0.000125 / 1K input tokens
    "gemini_output_per_1k": 0.000375   # $0.000375 / 1K output tokens
}


class CostCalculationService:
    """Configurable Pricing and Cost Tracking Engine."""

    async def get_pricing_rates(self, session: Optional[AsyncSession] = None) -> Dict[str, float]:
        """Fetch active pricing configuration or fallback to defaults."""
        if session:
            try:
                result = await session.execute(
                    select(SystemConfig).where(SystemConfig.key == "pricing_rates")
                )
                config_row = result.scalar_one_or_none()
                if config_row and isinstance(config_row.value, dict):
                    merged = DEFAULT_PRICING.copy()
                    merged.update(config_row.value)
                    return merged
            except Exception as e:
                logger.warning(f"Error reading pricing config: {e}")
        return DEFAULT_PRICING

    async def estimate_video_cost(
        self,
        duration_seconds: float,
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Calculate pre-processing estimated cost for a given video duration."""
        rates = await self.get_pricing_rates(session)
        duration_minutes = max(duration_seconds / 60.0, 0.1)

        audio_cost = duration_minutes * rates["audio_asr_per_min"]
        vision_cost = duration_minutes * rates["vision_per_min"]
        ocr_cost = duration_minutes * rates["ocr_per_min"]
        index_cost = duration_minutes * rates["vector_index_per_min"]

        # Estimated AI generation (assuming 2 calls ~2000 input tokens, ~1000 output tokens per min)
        est_input_tokens = int(duration_minutes * 2000)
        est_output_tokens = int(duration_minutes * 1000)
        ai_input_cost = (est_input_tokens / 1000.0) * rates["gemini_input_per_1k"]
        ai_output_cost = (est_output_tokens / 1000.0) * rates["gemini_output_per_1k"]

        total_estimated = round(audio_cost + vision_cost + ocr_cost + index_cost + ai_input_cost + ai_output_cost, 4)

        return {
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_minutes, 2),
            "estimated_total_cost": total_estimated,
            "breakdown": {
                "audio_asr": round(audio_cost, 4),
                "visual_keyframe": round(vision_cost, 4),
                "ocr_text": round(ocr_cost, 4),
                "search_indexing": round(index_cost, 4),
                "ai_generation": round(ai_input_cost + ai_output_cost, 4)
            },
            "rates_used": rates
        }

    async def calculate_quick_estimates(self, session: Optional[AsyncSession] = None) -> Dict[str, float]:
        """Quick cost estimates for 1, 5, 30, and 60-minute benchmark video lengths."""
        durations = [1, 5, 30, 60]
        result = {}
        for d in durations:
            est = await self.estimate_video_cost(d * 60, session)
            result[f"{d}_min"] = est["estimated_total_cost"]
        return result

    async def record_actual_cost(
        self,
        session: AsyncSession,
        video_id: str,
        organization_id: str,
        user_id: Optional[str],
        processing_stage: str,
        input_tokens: int,
        output_tokens: int,
        ai_calls_count: int = 1,
        model: str = "gemini-1.5-flash"
    ) -> ProcessingCostRecord:
        """Record measured AI token usage and actual cost ledger entry."""
        rates = await self.get_pricing_rates(session)
        input_cost = (input_tokens / 1000.0) * rates["gemini_input_per_1k"]
        output_cost = (output_tokens / 1000.0) * rates["gemini_output_per_1k"]
        actual_cost = round(input_cost + output_cost, 4)

        record = ProcessingCostRecord(
            video_id=video_id,
            organization_id=organization_id,
            user_id=user_id,
            model=model,
            processing_stage=processing_stage,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            ai_calls_count=ai_calls_count,
            estimated_cost=actual_cost,
            actual_cost=actual_cost,
            cost_breakdown_json={
                "input_token_cost": round(input_cost, 5),
                "output_token_cost": round(output_cost, 5)
            }
        )
        session.add(record)
        await session.flush()
        return record


# Singleton instance
cost_service = CostCalculationService()
