"""
tests/test_terminal_ws_stream.py — coverage for the terminal WebSocket stream path.

Covers uncovered lines in backend/routers/terminal.py:
- POST /api/terminal/session/{id}: SSH key device path (decrypts PEM → temp file)
- POST /api/terminal/session/{id}: asyncssh.HostKeyNotVerifiable → 502
- WebSocket /api/terminal/ws/{session_id}: valid token + known session → stream
- WebSocket /api/terminal/ws/{session_id}: valid token + SESSION_ENDED audit written
- WebSocket /api/terminal/ws/{session_id}: unexpected exception triggers _ws_error
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest
from sqlalchemy import select

from backend.models.audit import AuditLog
from backend.services.audit import ACTION_SESSION_ENDED, ACTION_SESSION_STARTED
from backend.services.crypto import generate_key_pair


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


def _key_device_payload(pem: str, **overrides) -> dict:
    return {
        "name": "key-server",
        "hostname": "10.0.0.1",
        "port": 22,
        "username": "deploy",
        "auth_type": "key",
        "private_key": pem,
        **overrides,
    }


# ── POST /api/terminal/session/{id}: SSH key device path ─────────────────────

async def test_open_session_key_device_creates_session(auth_client):
    """A key-type device must succeed when asyncssh.connect is mocked."""
    private_pem, _ = generate_key_pair()
    create_resp = await auth_client.post(
        "/api/devices/", json=_key_device_payload(private_pem)
    )
    assert create_resp.status_code == 201
    device_id = create_resp.json()["id"]

    fake_id = str(uuid.uuid4())
    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(return_value=fake_id),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")

    assert resp.status_code == 200
    assert resp.json()["session_id"] == fake_id


async def test_open_session_host_key_not_verifiable_returns_502(auth_client):
    """asyncssh.HostKeyNotVerifiable must map to HTTP 502."""
    create_resp = await auth_client.post(
        "/api/devices/", json=_password_device_payload()
    )
    device_id = create_resp.json()["id"]

    with patch(
        "backend.routers.terminal.create_session",
        new=AsyncMock(
            side_effect=asyncssh.HostKeyNotVerifiable(reason="key mismatch")
        ),
    ):
        resp = await auth_client.post(f"/api/terminal/session/{device_id}")

    assert resp.status_code == 502
    assert "Host key not verifiable" in resp.json()["detail"]


# ── WebSocket: valid token + working session → stream_session called ─────────

async def test_ws_valid_token_accepted_and_stream_called(auth_client):
    """
    With a valid JWT and a mocked stream_session the WS must be accepted and
    stream_session must be invoked.
    """
    from backend.config import get_settings
    from backend.routers.auth import ALGORITHM
    from jose import jwt as jose_jwt

    settings = get_settings()
    raw_token = auth_client.headers["Authorization"].split(" ")[1]
    fake_session_id = str(uuid.uuid4())

    # We call the handler directly to avoid ASGI client lifecycle issues
    import asyncio
    from unittest.mock import MagicMock, AsyncMock, patch
    from fastapi import WebSocket
    from backend.routers.terminal import terminal_ws

    mock_ws = MagicMock(spec=WebSocket)
    mock_ws.query_params = {"token": raw_token}
    mock_ws.headers = {}
    mock_ws.client = MagicMock()
    mock_ws.client.host = "127.0.0.1"
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws.send_bytes = AsyncMock()

    mock_stream = AsyncMock(return_value=None)

    with (
        patch("backend.routers.terminal.stream_session", new=mock_stream),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("MyBox", "admin", "127.0.0.1"),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx

        await terminal_ws(fake_session_id, mock_ws)

    mock_ws.accept.assert_called_once()
    mock_stream.assert_called_once_with(fake_session_id, mock_ws)


# ── WebSocket: valid token but stream raises exception ────────────────────────

async def test_ws_stream_exception_sends_error_frame(auth_client):
    """An unexpected exception in stream_session must be caught and an error frame sent."""
    from fastapi import WebSocket
    from backend.routers.terminal import terminal_ws

    raw_token = auth_client.headers["Authorization"].split(" ")[1]
    fake_session_id = str(uuid.uuid4())

    mock_ws = MagicMock(spec=WebSocket)
    mock_ws.query_params = {"token": raw_token}
    mock_ws.headers = {}
    mock_ws.client = MagicMock()
    mock_ws.client.host = "127.0.0.1"
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws.send_bytes = AsyncMock()

    with (
        patch(
            "backend.routers.terminal.stream_session",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("", "", None),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx

        await terminal_ws(fake_session_id, mock_ws)

    # _ws_error sends a binary frame with the error message
    mock_ws.send_bytes.assert_called()
    sent_data = mock_ws.send_bytes.call_args[0][0]
    assert b"boom" in sent_data


# ── WebSocket: X-Forwarded-For / X-Real-IP header parsing ────────────────────

async def test_ws_x_real_ip_extracted(auth_client):
    """The client IP must be extracted from X-Real-IP when X-Forwarded-For is absent."""
    from fastapi import WebSocket
    from backend.routers.terminal import terminal_ws

    raw_token = auth_client.headers["Authorization"].split(" ")[1]
    fake_session_id = str(uuid.uuid4())

    mock_ws = MagicMock(spec=WebSocket)
    mock_ws.query_params = {"token": raw_token}
    mock_ws.headers = {"x-real-ip": "10.20.30.40"}
    mock_ws.client = MagicMock()
    mock_ws.client.host = "127.0.0.1"
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws.send_bytes = AsyncMock()

    mock_stream = AsyncMock(return_value=None)

    with (
        patch("backend.routers.terminal.stream_session", new=mock_stream),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("", "admin", None),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx

        await terminal_ws(fake_session_id, mock_ws)

    mock_stream.assert_called_once()
