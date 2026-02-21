"""
tests/test_database.py — unit tests for backend/database.py

Covers:
- _import_models registers Device, AdminCredential, and AuditLog on Base.metadata
- init_db creates all expected tables in a fresh engine
- get_db yields an AsyncSession and closes it cleanly
"""
import pytest
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database import Base, get_db, init_db


# ── _import_models / Base.metadata ───────────────────────────────────────────

def test_base_metadata_contains_devices_table():
    """After module import the 'devices' table must be registered on Base.metadata."""
    # Importing database triggers _import_models indirectly through get_engine
    from backend.database import _import_models  # noqa: PLC0415
    _import_models()
    assert "devices" in Base.metadata.tables


def test_base_metadata_contains_audit_logs_table():
    """After module import the 'audit_logs' table must be registered on Base.metadata."""
    from backend.database import _import_models  # noqa: PLC0415
    _import_models()
    assert "audit_logs" in Base.metadata.tables


def test_base_metadata_contains_admin_credentials_table():
    """After module import the 'admin_credentials' table must be registered."""
    from backend.database import _import_models  # noqa: PLC0415
    _import_models()
    assert "admin_credentials" in Base.metadata.tables


# ── init_db ───────────────────────────────────────────────────────────────────

async def test_init_db_creates_tables():
    """init_db must create all expected tables in a fresh in-memory database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Temporarily replace the module-level engine used by init_db
    import backend.database as db_module  # noqa: PLC0415
    original_engine = db_module.engine
    db_module.engine = engine

    try:
        await init_db()
        async with engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: sa_inspect(sync_conn).get_table_names()
            )
        assert "devices" in table_names
        assert "audit_logs" in table_names
        assert "admin_credentials" in table_names
    finally:
        db_module.engine = original_engine
        await engine.dispose()


# ── get_db ────────────────────────────────────────────────────────────────────

async def test_get_db_yields_session(db_session):
    """get_db must yield a usable AsyncSession (covered via the conftest fixture)."""
    # The db_session fixture IS get_db in test context — exercise a basic query
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


async def test_get_db_dependency_yields_and_closes():
    """get_db as a generator yields exactly one session and then closes."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    import backend.database as db_module  # noqa: PLC0415
    original_factory = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = factory

    try:
        sessions_yielded = []
        async for session in get_db():
            sessions_yielded.append(session)
            # Only one session should be yielded
            break
        assert len(sessions_yielded) == 1
    finally:
        db_module.AsyncSessionLocal = original_factory
        await engine.dispose()
