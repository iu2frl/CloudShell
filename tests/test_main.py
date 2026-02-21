"""
tests/test_main.py — tests for backend/main.py

Covers:
- GET /api/health returns {"status": "ok", "version": ..., "uptime_seconds": ...}
- uptime_seconds is a non-negative integer
- Global exception handler catches unhandled errors and returns 500
- BOOT_ID is a non-empty UUID string
"""
import uuid

import pytest

from backend.main import BOOT_ID


# ── /api/health ───────────────────────────────────────────────────────────────

async def test_health_returns_200(client):
    """GET /api/health must return HTTP 200."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200


async def test_health_response_fields(client):
    """GET /api/health must include status, version, and uptime_seconds."""
    resp = await client.get("/api/health")
    body = resp.json()
    assert "status" in body
    assert "version" in body
    assert "uptime_seconds" in body


async def test_health_status_is_ok(client):
    """GET /api/health must return status='ok'."""
    resp = await client.get("/api/health")
    assert resp.json()["status"] == "ok"


async def test_health_uptime_non_negative(client):
    """uptime_seconds must be a non-negative integer."""
    resp = await client.get("/api/health")
    uptime = resp.json()["uptime_seconds"]
    assert isinstance(uptime, int)
    assert uptime >= 0


async def test_health_no_auth_required(client):
    """GET /api/health must be accessible without authentication."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200


# ── Global exception handler ──────────────────────────────────────────────────

async def test_unhandled_exception_returns_500(db_session):
    """An unhandled exception in a route must return HTTP 500."""
    from httpx import ASGITransport, AsyncClient
    from backend.database import get_db
    from backend.main import app

    # Attach a temporary route that intentionally raises
    @app.get("/api/_test_crash")
    async def _crash():
        raise RuntimeError("intentional test crash")

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    # raise_app_exceptions=False is required so the custom exception handler
    # can return a 500 response instead of the test transport re-raising the error.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/_test_crash")
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "Internal server error"
        assert body["type"] == "RuntimeError"
    finally:
        app.routes[:] = [r for r in app.routes if getattr(r, "path", "") != "/api/_test_crash"]
        app.dependency_overrides.clear()


# ── BOOT_ID ───────────────────────────────────────────────────────────────────

def test_boot_id_is_valid_uuid():
    """BOOT_ID must be a non-empty, valid UUID string."""
    assert BOOT_ID
    # Should not raise
    uuid.UUID(BOOT_ID)
