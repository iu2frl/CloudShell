"""
tests/test_ssh_service.py — unit tests for services/ssh.py.

Tests cover:
- create_session stores the session in the internal registry
- create_session propagates asyncssh exceptions to the caller
- close_session removes the entry from the registry
- close_session is a no-op for an unknown session_id
- get_session_meta returns (device_label, cloudshell_user, source_ip) correctly
- get_session_meta returns empty defaults for an unknown session_id
- _ws_error sends a formatted binary frame to the WebSocket
"""
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from backend.services import ssh as ssh_module
from backend.services.ssh import (
    _ws_error,
    close_session,
    get_session_meta,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_conn() -> MagicMock:
    """Return a mock asyncssh connection that supports close() and wait_closed()."""
    conn = MagicMock()
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    return conn


def _inject_session(session_id: str, device_label: str = "box (1.2.3.4:22)",
                    cloudshell_user: str = "admin", source_ip: str | None = "5.6.7.8") -> None:
    """Directly insert a fake session into the module's _sessions store."""
    from backend.services.ssh import _Session
    ssh_module._sessions[session_id] = _Session(
        conn=_make_mock_conn(),
        device_label=device_label,
        cloudshell_user=cloudshell_user,
        source_ip=source_ip,
    )


def _cleanup_session(session_id: str) -> None:
    ssh_module._sessions.pop(session_id, None)


# ── create_session ────────────────────────────────────────────────────────────

async def test_create_session_stores_entry():
    """create_session must add an entry to _sessions on success."""
    mock_conn = _make_mock_conn()
    with patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)):
        session_id = await ssh_module.create_session(
            hostname="127.0.0.1",
            port=22,
            username="user",
            password="pass",
            known_hosts=None,
            device_label="test-box",
            cloudshell_user="admin",
            source_ip="1.2.3.4",
        )

    try:
        assert session_id in ssh_module._sessions
        entry = ssh_module._sessions[session_id]
        assert entry.device_label == "test-box"
        assert entry.cloudshell_user == "admin"
        assert entry.source_ip == "1.2.3.4"
    finally:
        _cleanup_session(session_id)


async def test_create_session_returns_uuid_string():
    """create_session must return a UUID-formatted string."""
    import uuid
    mock_conn = _make_mock_conn()
    with patch("asyncssh.connect", new=AsyncMock(return_value=mock_conn)):
        session_id = await ssh_module.create_session(
            hostname="127.0.0.1",
            port=22,
            username="user",
            known_hosts=None,
        )
    try:
        # Should not raise ValueError
        uuid.UUID(session_id)
    finally:
        _cleanup_session(session_id)


async def test_create_session_propagates_permission_denied():
    """create_session must re-raise asyncssh.PermissionDenied to the caller."""
    with patch(
        "asyncssh.connect",
        new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="Bad credentials")),
    ):
        with pytest.raises(asyncssh.PermissionDenied):
            await ssh_module.create_session(
                hostname="127.0.0.1",
                port=22,
                username="user",
                password="wrong",
                known_hosts=None,
            )


async def test_create_session_propagates_connection_lost():
    """create_session must re-raise asyncssh.ConnectionLost to the caller."""
    with patch(
        "asyncssh.connect",
        new=AsyncMock(side_effect=asyncssh.ConnectionLost(reason="Network unreachable")),
    ):
        with pytest.raises(asyncssh.ConnectionLost):
            await ssh_module.create_session(
                hostname="10.0.0.99",
                port=22,
                username="user",
                known_hosts=None,
            )


async def test_create_session_propagates_oserror():
    """create_session must re-raise OSError (e.g. host unreachable) to the caller."""
    with patch("asyncssh.connect", new=AsyncMock(side_effect=OSError("Connection refused"))):
        with pytest.raises(OSError):
            await ssh_module.create_session(
                hostname="127.0.0.1",
                port=22,
                username="user",
                known_hosts=None,
            )


# ── close_session ─────────────────────────────────────────────────────────────

async def test_close_session_removes_entry():
    """close_session must remove the session from _sessions."""
    import uuid
    session_id = str(uuid.uuid4())
    _inject_session(session_id)

    assert session_id in ssh_module._sessions
    await close_session(session_id)
    assert session_id not in ssh_module._sessions


async def test_close_session_unknown_id_is_noop():
    """close_session with an unknown session_id must not raise."""
    await close_session("00000000-0000-0000-0000-000000000000")


async def test_close_session_calls_conn_close():
    """close_session must call conn.close() on the underlying connection."""
    import uuid
    session_id = str(uuid.uuid4())
    _inject_session(session_id)
    conn = ssh_module._sessions[session_id].conn

    await close_session(session_id)
    conn.close.assert_called_once()  # type: ignore[attr-defined]


# ── get_session_meta ──────────────────────────────────────────────────────────

def test_get_session_meta_returns_stored_values():
    """get_session_meta must return the device_label, cloudshell_user and source_ip."""
    import uuid
    session_id = str(uuid.uuid4())
    _inject_session(session_id, device_label="my-box (10.0.0.1:22)",
                    cloudshell_user="alice", source_ip="192.168.0.5")

    try:
        label, user, ip = get_session_meta(session_id)
        assert label == "my-box (10.0.0.1:22)"
        assert user == "alice"
        assert ip == "192.168.0.5"
    finally:
        _cleanup_session(session_id)


def test_get_session_meta_unknown_id_returns_defaults():
    """get_session_meta for an unknown session must return ('', '', None)."""
    label, user, ip = get_session_meta("00000000-0000-0000-0000-000000000000")
    assert label == ""
    assert user == ""
    assert ip is None


def test_get_session_meta_null_source_ip():
    """get_session_meta must return None for source_ip when it was stored as None."""
    import uuid
    session_id = str(uuid.uuid4())
    _inject_session(session_id, source_ip=None)

    try:
        _, _, ip = get_session_meta(session_id)
        assert ip is None
    finally:
        _cleanup_session(session_id)


# ── _ws_error ─────────────────────────────────────────────────────────────────

async def test_ws_error_sends_binary_frame():
    """_ws_error must send a binary frame containing the error message."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock()

    await _ws_error(ws, "host unreachable")

    ws.send_bytes.assert_called_once()
    frame: bytes = ws.send_bytes.call_args[0][0]
    assert b"host unreachable" in frame


async def test_ws_error_does_not_raise_on_send_failure():
    """_ws_error must silently swallow any exception from websocket.send_bytes."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock(side_effect=RuntimeError("WebSocket closed"))

    # Must not raise
    await _ws_error(ws, "some error")
