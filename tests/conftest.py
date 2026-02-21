"""
tests/conftest.py — shared fixtures for the CloudShell test suite.

Each test gets a fresh in-memory SQLite database and a pre-authenticated
HTTP client so individual tests stay focused on what they actually test.
"""
import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# ── Force test environment variables BEFORE any backend module is imported ────
os.environ.setdefault("SECRET_KEY",           "test-secret-key-do-not-use-in-prod")
os.environ.setdefault("ADMIN_USER",           "admin")
os.environ.setdefault("ADMIN_PASSWORD",       "admin")
os.environ.setdefault("TOKEN_TTL_HOURS",      "1")
os.environ.setdefault("DATA_DIR",             "/tmp/cloudshell-pytest")
os.environ.setdefault("AUDIT_RETENTION_DAYS", "7")

# ── Backend imports (after env vars are set) ──────────────────────────────────
from backend.config import get_settings  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402


@pytest_asyncio.fixture()
async def db_session():
    """Yield an AsyncSession backed by a fully-isolated in-memory SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession):
    """Return an AsyncClient with the DB dependency overridden to the test session."""

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    get_settings.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def auth_client(client: AsyncClient):
    """Return an AsyncClient with a valid admin Bearer token already attached."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
