from fastapi import APIRouter
from app.api.v1.videos import router as videos_router
from app.api.v1.chat import router as chat_router
from app.api.v1.hitl import router as hitl_router
from app.api.v1.health import router as health_router
from app.api.v1.quiz import router as quiz_router
from app.api.v1.auth import router as auth_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1.projects import router as projects_router
from app.api.v1.costs import router as costs_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.observability import router as observability_router
from app.api.v1.audit_logs import router as audit_logs_router
from app.api.v1.onboarding import router as onboarding_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(videos_router)
v1_router.include_router(chat_router)
v1_router.include_router(hitl_router)
v1_router.include_router(health_router)
v1_router.include_router(quiz_router)
v1_router.include_router(auth_router)
v1_router.include_router(orgs_router)
v1_router.include_router(projects_router)
v1_router.include_router(costs_router)
v1_router.include_router(analytics_router)
v1_router.include_router(observability_router)
v1_router.include_router(audit_logs_router)
v1_router.include_router(onboarding_router)


