from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    # App Information
    APP_NAME: str = "AI Video Analyser & Chat"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8090

    # PostgreSQL Database URL (host port 5433 to avoid collision with local port 5432)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgrespassword@localhost:5433/video_analyser"

    # AI Model Provider
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.6-flash"
    EMBEDDING_MODEL: str = "models/gemini-embedding-001"

    # Ingestion & Video Pipeline
    MAX_VIDEO_SIZE_MB: int = 500
    ALLOWED_EXTENSIONS: set[str] = {".mp4", ".mov", ".mkv", ".avi"}
    FRAME_SAMPLE_INTERVAL_SEC: float = 3.0
    MAX_CONCURRENT_WORKERS: int = 2
    CONFIDENCE_THRESHOLD: float = 0.70

    # Storage Directories
    STORAGE_DIR: Path = Path("./data")
    UPLOAD_DIR: Path = Path("./data/uploads")
    KEYFRAME_DIR: Path = Path("./data/keyframes")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def init_storage(self) -> None:
        """Ensure all required storage directories exist."""
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.init_storage()
