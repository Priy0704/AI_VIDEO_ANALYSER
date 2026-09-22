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
        
        # New B2B SaaS columns
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active';"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();"))
        await conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active';"))
        await conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS organization_id VARCHAR(36);"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(36);"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS project_id VARCHAR(36);"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS uploaded_by_user_id VARCHAR(36);"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS estimated_cost FLOAT DEFAULT 0.0;"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS actual_cost FLOAT DEFAULT 0.0;"))
        await conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS stage_timings_json JSON;"))

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

    # Seed Default B2B Organization, Workspace, User, and Project
    async with AsyncSessionLocal() as session:
        try:
            # Check default Organization
            result = await session.execute(text("SELECT id FROM organizations WHERE slug = 'acme-corp' LIMIT 1;"))
            org_row = result.fetchone()
            org_id = org_row[0] if org_row else "org-default-acme"

            if not org_row:
                await session.execute(text(
                    "INSERT INTO organizations (id, name, slug, plan, created_at) "
                    "VALUES (:id, 'Acme Corporation', 'acme-corp', 'Enterprise', NOW());"
                ), {"id": org_id})
                await session.commit()

            # Check default Workspace
            result = await session.execute(text("SELECT id FROM workspaces WHERE organization_id = :org_id LIMIT 1;"), {"org_id": org_id})
            ws_row = result.fetchone()
            ws_id = ws_row[0] if ws_row else "ws-default-prod"

            if not ws_row:
                await session.execute(text(
                    "INSERT INTO workspaces (id, organization_id, name, description, created_at) "
                    "VALUES (:id, :org_id, 'Production Workspace', 'Primary video analytics workspace', NOW());"
                ), {"id": ws_id, "org_id": org_id})
                await session.commit()

            # Check default Admin User
            result = await session.execute(text("SELECT id FROM users WHERE email = 'priyanka@acme.com' LIMIT 1;"))
            usr_row = result.fetchone()
            user_id = usr_row[0] if usr_row else "usr-default-admin"

            if not usr_row:
                await session.execute(text(
                    "INSERT INTO users (id, organization_id, email, full_name, role, onboarding_completed, created_at) "
                    "VALUES (:id, :org_id, 'priyanka@acme.com', 'Priyanka Davhare', 'org_admin', 1, NOW());"
                ), {"id": user_id, "org_id": org_id})
                await session.commit()

            # Check default Project
            result = await session.execute(text("SELECT id FROM projects WHERE organization_id = :org_id LIMIT 1;"), {"org_id": org_id})
            prj_row = result.fetchone()
            project_id = prj_row[0] if prj_row else "prj-default-ai"

            if not prj_row:
                await session.execute(text(
                    "INSERT INTO projects (id, organization_id, workspace_id, name, description, color, created_at) "
                    "VALUES (:id, :org_id, :ws_id, 'General AI Intelligence', 'Default intelligence container', '#38bdf8', NOW());"
                ), {"id": project_id, "org_id": org_id, "ws_id": ws_id})
                await session.commit()

            # Link unassigned existing videos to default Org, Workspace, and Project
            await session.execute(text(
                "UPDATE videos SET organization_id = :org_id, workspace_id = :ws_id, project_id = :prj_id "
                "WHERE organization_id IS NULL OR workspace_id IS NULL;"
            ), {"org_id": org_id, "ws_id": ws_id, "prj_id": project_id})
            await session.commit()

        except Exception as e:
            logger.warning(f"Note during B2B seed data initialization: {e}")
            await session.rollback()

    logger.info("Database tables initialized successfully with B2B tenancy.")


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
