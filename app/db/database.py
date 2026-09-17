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
