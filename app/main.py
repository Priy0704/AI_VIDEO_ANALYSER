import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.core.logging import setup_logging
from app.db.database import init_db
from app.api.v1.router import v1_router

setup_logging(logging.INFO if not settings.DEBUG else logging.DEBUG)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing AI Video Analyser & Chat microservice...")
    settings.init_storage()
    try:
        await init_db()
    except Exception as e:
        logger.warning(f"Database initialization note: {e}")
    yield
    logger.info("Shutting down AI Video Analyser & Chat microservice...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Production-grade microservice for generic video understanding, "
        "multimodal audio-visual temporal fusion with PostgreSQL + pgvector, "
        "and grounded conversational Q&A with timestamp citations and confidence-driven HITL."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception(f"Unhandled server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"}
    )

# Mount API routes
app.include_router(v1_router)

# Mount top-level health checks for standard orchestrators/Kubernetes
from app.api.v1.health import router as root_health_router
app.include_router(root_health_router)

# Static files & UI
static_path = Path(__file__).parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", include_in_schema=False)
async def serve_ui():
    """Serve the simple functional web UI."""
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "AI Video Analyser API is running. Visit /docs for API documentation."}
