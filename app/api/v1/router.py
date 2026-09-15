from fastapi import APIRouter
from app.api.v1.videos import router as videos_router
from app.api.v1.chat import router as chat_router
from app.api.v1.hitl import router as hitl_router
from app.api.v1.health import router as health_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(videos_router)
v1_router.include_router(chat_router)
v1_router.include_router(hitl_router)
v1_router.include_router(health_router)
