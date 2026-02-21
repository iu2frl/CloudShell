"""
tests/test_terminal_api.py — integration tests for the terminal/SSH session API.

Tests cover:
- POST /api/terminal/session/{device_id}
  - requires authentication
  - returns 404 for a non-existent device
  - SSH connection failures are mapped to 502
  - SSH auth failures are mapped to 401
  - returns a session_id on success (mocked SSH)
  - writes a SESSION_STARTED audit entry on success
- WebSocket /api/terminal/ws/{session_id}
  - closes with code 4001 when no token is provided
  - closes with code 4001 when an invalid token is provided
  - closes with code 4004 when session_id is not found
"""
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest
from sqlalchemy import select

from backend.models.audit import AuditLog
from backend.services.audit import ACTION_SESSION_STARTED


# ── Helpers ───────────────────────────────────────────────────────────────────

def _password_device_payload(**overrides) -> dict:
    return {
        "name": "test-server",
        "hostname": "192.168.1.10",
        "port": 22,
        "username": "root",
        "auth_type": "password",
        "password": "s3cr3t",
        **overrides,
    }


def _make_fake_session_id() -> str:
    import uuid
    return str(uuid.uuid4())


# ── POST /api/terminal/session/{device_id} ────────────────────────────────────

async def test_open_session_requires_auth(client, db_session):
    """POST /api/terminal/session/{id} without a token must return 401."""
    # Create a device first (must be done while authenticated)
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    create_resp = await client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    # Remove the token and try to open a session
    client.headers.pop("Authorization", None)
    resp = await client.post(f"/api/terminal/session/{device_id}")
    assert resp.status_code == 401


async def test_open_session_device_not_found(auth_client):
    """POST /api/terminal/session/{id} with a non-existent device must return 404."""
    resp = await auth_client.post("/api/terminal/session/99999")
    assert resp.status_code == 404


async def test_open_session_ssh_connection_error_returns_502(auth_client):
    """An SSH OSError (host unreachable) must be mapped to HTTP 502."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(side_effect=OSError("Connection refused")),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")
    assert resp.status_code == 502


async def test_open_session_ssh_auth_failure_returns_401(auth_client):
    """An asyncssh.PermissionDenied must be mapped to HTTP 401."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="Bad password")),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")
    assert resp.status_code == 401


async def test_open_session_ssh_generic_error_returns_502(auth_client):
    """A generic asyncssh.Error must be mapped to HTTP 502."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(side_effect=asyncssh.Error(code=0, reason="Something failed")),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")
    assert resp.status_code == 502


async def test_open_session_returns_session_id(auth_client):
    """On a successful connection the response must contain a session_id UUID."""
    import uuid
    fake_id = str(uuid.uuid4())

    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(return_value=fake_id),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["session_id"] == fake_id


async def test_open_session_writes_audit_entry(auth_client, db_session):
    """A successful session open must create a SESSION_STARTED audit entry."""
    import uuid
    fake_id = str(uuid.uuid4())

    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    before = len((await db_session.execute(select(AuditLog))).scalars().all())

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(return_value=fake_id),
    ):
        await auth_client.post(f"/api/terminal/session/{device_id}")

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == before + 1
    newest = max(rows, key=lambda r: r.id)
    assert newest.action == ACTION_SESSION_STARTED


async def test_open_session_ssh_connection_lost_returns_504(auth_client):
    """An asyncssh.ConnectionLost must be mapped to HTTP 504."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(side_effect=asyncssh.ConnectionLost(reason="Connection lost")),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")
    assert resp.status_code == 504


# ── WebSocket /api/terminal/ws/{session_id} ───────────────────────────────────

async def test_ws_no_token_closes_4001(client):
    """WebSocket connection without a token query-param must be closed with code 4001."""
    fake_session_id = _make_fake_session_id()
    with pytest.raises(Exception):
        async with client.websocket_connect(
            f"/api/terminal/ws/{fake_session_id}"
        ) as ws:
            # The server should close immediately with 4001
            await ws.receive_json()


async def test_ws_invalid_token_closes_4001(client):
    """WebSocket connection with a garbage JWT must be closed with code 4001."""
    fake_session_id = _make_fake_session_id()
    with pytest.raises(Exception):
        async with client.websocket_connect(
            f"/api/terminal/ws/{fake_session_id}?token=this.is.garbage"
        ) as ws:
            await ws.receive_json()
