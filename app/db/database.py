import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from app.config import settings
from app.db.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def init_db() -> None:
    """Initialize database tables and apply backward-compatible schema updates."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # In PostgreSQL, apply ALTER TABLE with IF NOT EXISTS to guarantee smooth migration
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE video_segments ADD COLUMN IF NOT EXISTS ocr_text TEXT;"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_type VARCHAR(50) DEFAULT 'knowledge';"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_type_label VARCHAR(100) DEFAULT 'Learning / Knowledge Content';"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_type_confidence FLOAT DEFAULT 0.90;"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_type_reason TEXT;"))

        # Re-classify existing database records for CCTV/Surveillance footage & short audio-less clips
        await conn.execute(text("""
            UPDATE videos
            SET video_type = 'observational',
                video_type_label = 'Observational / Surveillance',
                video_type_reason = 'Observational camera footage or short video (<60s) without voice learning material.'
            WHERE (
                LOWER(filename) LIKE '%cctv%' OR
                LOWER(filename) LIKE '%surveillance%' OR
                LOWER(filename) LIKE '%cam%' OR
                LOWER(filename) LIKE '%gate%' OR
                LOWER(filename) LIKE '%hallway%' OR
                LOWER(filename) LIKE '%corridor%' OR
                LOWER(filename) LIKE '%dashcam%' OR
                LOWER(filename) LIKE '%traffic%' OR
                (duration_seconds IS NOT NULL AND duration_seconds > 0 AND duration_seconds < 60.0 AND LOWER(filename) NOT LIKE '%lecture%' AND LOWER(filename) NOT LIKE '%tutorial%' AND LOWER(filename) NOT LIKE '%presentation%')
            ) AND video_type = 'knowledge';
        """))

    logger.info("Database tables initialized successfully.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
