"""
tests/test_ssh_service_stream.py — unit tests for ssh service stream/close/meta helpers.

Covers uncovered lines in backend/services/ssh.py:
- stream_session: unknown session → _ws_error + close 4004
- stream_session: asyncssh.Error from create_process → _ws_error + close 4011
- stream_session: resize frame received before PTY creation
- stream_session: ws_to_ssh resize control frame during streaming
- stream_session: ssh_to_ws sends str chunks (encoded to bytes)
- stream_session: clean close path
- close_session: removes session and closes connection
- close_session: no-op for unknown session
- get_session_meta: returns stored values
- get_session_meta: returns empty strings for unknown session
- _ws_error: sends formatted ANSI error bytes
- _ws_error: swallows send exceptions
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from backend.services.ssh import (
    _Session,
    _sessions,
    _ws_error,
    close_session,
    create_session,
    get_session_meta,
    stream_session,
)


def _make_websocket(recv_messages: list | None = None) -> MagicMock:
    """Build a minimal WebSocket mock."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()

    # receive() returns successive messages from the list then raises
    messages = list(recv_messages or [])

    async def _receive():
        if messages:
            return messages.pop(0)
        raise asyncio.CancelledError

    ws.receive = _receive
    return ws


# ── _ws_error ─────────────────────────────────────────────────────────────────

async def test_ws_error_sends_ansi_message():
    """_ws_error must send an ANSI-formatted error message as bytes."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock()

    await _ws_error(ws, "test error")

    ws.send_bytes.assert_called_once()
    sent = ws.send_bytes.call_args[0][0]
    assert b"test error" in sent
    assert b"\x1b[31m" in sent  # ANSI red


async def test_ws_error_swallows_send_exception():
    """_ws_error must not propagate exceptions from send_bytes."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock(side_effect=RuntimeError("socket closed"))

    # Should not raise
    await _ws_error(ws, "something bad happened")


# ── get_session_meta ──────────────────────────────────────────────────────────

def test_get_session_meta_returns_stored_values():
    """get_session_meta must return the stored device_label, user, and IP."""
    sid = "test-meta-session"
    conn = MagicMock()
    _sessions[sid] = _Session(
        conn=conn,
        device_label="MyServer (10.0.0.1:22)",
        cloudshell_user="admin",
        source_ip="192.168.1.1",
    )
    try:
        label, user, ip = get_session_meta(sid)
        assert label == "MyServer (10.0.0.1:22)"
        assert user == "admin"
        assert ip == "192.168.1.1"
    finally:
        _sessions.pop(sid, None)


def test_get_session_meta_unknown_session_returns_empty():
    """get_session_meta for a missing session must return empty defaults."""
    label, user, ip = get_session_meta("no-such-session")
    assert label == ""
    assert user == ""
    assert ip is None


# ── close_session ─────────────────────────────────────────────────────────────

async def test_close_session_removes_entry():
    """close_session must remove the session from the store and close the connection."""
    sid = "test-close-session"
    conn = MagicMock()
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    _sessions[sid] = _Session(conn=conn)

    await close_session(sid)

    assert sid not in _sessions
    conn.close.assert_called_once()


async def test_close_session_unknown_is_noop():
    """close_session for an unknown session must not raise."""
    await close_session("i-do-not-exist")


async def test_close_session_swallows_conn_close_error():
    """close_session must not propagate exceptions from conn.close()."""
    sid = "test-close-error"
    conn = MagicMock()
    conn.close = MagicMock(side_effect=RuntimeError("already closed"))
    conn.wait_closed = AsyncMock()
    _sessions[sid] = _Session(conn=conn)

    await close_session(sid)  # should not raise
    assert sid not in _sessions


# ── stream_session: unknown session ───────────────────────────────────────────

async def test_stream_session_unknown_session_sends_error_and_closes():
    """stream_session with an unknown session_id must send an error and close with 4004."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()
    ws.receive = AsyncMock()

    await stream_session("no-such-session", ws)

    ws.send_bytes.assert_called_once()
    ws.close.assert_called_once_with(code=4004)


# ── stream_session: create_process raises asyncssh.Error ─────────────────────

async def test_stream_session_create_process_error_closes_4011():
    """If create_process raises asyncssh.Error the WS must be closed with code 4011."""
    sid = "test-process-error"
    conn = MagicMock()
    conn.create_process = AsyncMock(
        side_effect=asyncssh.Error(code=0, reason="pty failed")
    )
    _sessions[sid] = _Session(conn=conn)

    # Provide a resize frame as first message so the flow reaches create_process
    resize_msg = {"bytes": json.dumps({"type": "resize", "cols": 80, "rows": 24}).encode()}
    ws = _make_websocket([resize_msg])
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()

    try:
        await stream_session(sid, ws)
    finally:
        _sessions.pop(sid, None)

    ws.close.assert_called_with(code=4011)


# ── stream_session: resize frame processing ───────────────────────────────────

async def test_stream_session_uses_resize_dimensions():
    """A resize frame received before PTY creation must set the PTY dimensions."""
    sid = "test-resize-dims"
    conn = MagicMock()

    process = MagicMock()
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdout = MagicMock()
    # Return empty bytes to end the ssh_to_ws loop
    process.stdout.read = AsyncMock(return_value=b"")
    process.change_terminal_size = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    _sessions[sid] = _Session(conn=conn)

    resize_msg = {"bytes": json.dumps({"type": "resize", "cols": 120, "rows": 40}).encode()}

    ws = MagicMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()

    # First receive() returns the resize frame; subsequent calls raise to end the loop
    call_count = {"n": 0}

    async def _recv():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return resize_msg
        raise asyncio.CancelledError

    ws.receive = _recv

    try:
        await stream_session(sid, ws)
    finally:
        _sessions.pop(sid, None)

    # create_process must have been called with the resize dimensions
    _, kwargs = conn.create_process.call_args
    assert kwargs["term_size"] == (120, 40)


# ── stream_session: text frame fallback ──────────────────────────────────────

async def test_stream_session_initial_timeout_uses_defaults():
    """When the initial resize frame times out, fallback dimensions are used."""
    sid = "test-resize-timeout"
    conn = MagicMock()

    process = MagicMock()
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdout = MagicMock()
    process.stdout.read = AsyncMock(return_value=b"")
    process.change_terminal_size = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    _sessions[sid] = _Session(conn=conn)

    ws = MagicMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()

    # Make the initial wait_for call always raise TimeoutError, then let
    # subsequent receive() calls raise CancelledError to end the stream loop.
    wait_for_called = {"n": 0}
    real_wait_for = asyncio.wait_for

    async def _fake_wait_for(coro, timeout):
        wait_for_called["n"] += 1
        if wait_for_called["n"] == 1:
            # Consume the coroutine to avoid the "never awaited" warning
            coro.close()
            raise asyncio.TimeoutError
        return await real_wait_for(coro, timeout)

    with patch("asyncio.wait_for", side_effect=_fake_wait_for):
        try:
            await stream_session(sid, ws)
        finally:
            _sessions.pop(sid, None)

    _, kwargs = conn.create_process.call_args
    assert kwargs["term_size"] == (220, 50)  # default fallback


# ── stream_session: str chunk encoding ───────────────────────────────────────

async def test_stream_session_str_chunks_encoded_to_bytes():
    """ssh_to_ws must encode str chunks from the SSH process to bytes."""
    sid = "test-str-chunk"
    conn = MagicMock()

    process = MagicMock()
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdout = MagicMock()
    # First call returns a str, second returns empty to end the loop
    process.stdout.read = AsyncMock(side_effect=["hello", b""])
    process.change_terminal_size = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    _sessions[sid] = _Session(conn=conn)

    resize_msg = {"bytes": json.dumps({"type": "resize", "cols": 80, "rows": 24}).encode()}

    ws = MagicMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()

    call_count = {"n": 0}

    async def _recv():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return resize_msg
        raise asyncio.CancelledError

    ws.receive = _recv

    try:
        await stream_session(sid, ws)
    finally:
        _sessions.pop(sid, None)

    # At least one send_bytes call must have received bytes
    calls = [c[0][0] for c in ws.send_bytes.call_args_list]
    assert any(isinstance(c, bytes) for c in calls)


# ── create_session ────────────────────────────────────────────────────────────

async def test_create_session_with_password_stores_metadata():
    """create_session must store device_label and cloudshell_user in the session."""
    conn = MagicMock()
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()

    with (
        patch("backend.services.ssh._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await create_session(
            hostname="10.0.0.1",
            port=22,
            username="root",
            password="secret",
            device_label="TestBox (10.0.0.1:22)",
            cloudshell_user="admin",
            source_ip="127.0.0.1",
        )

    try:
        assert sid in _sessions
        label, user, ip = get_session_meta(sid)
        assert label == "TestBox (10.0.0.1:22)"
        assert user == "admin"
        assert ip == "127.0.0.1"
    finally:
        _sessions.pop(sid, None)


async def test_create_session_propagates_connection_error():
    """create_session must propagate asyncssh errors to the caller."""
    with (
        patch("backend.services.ssh._known_hosts_path", return_value=None),
        patch(
            "asyncssh.connect",
            new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="bad key")),
        ),
    ):
        with pytest.raises(asyncssh.PermissionDenied):
            await create_session(
                hostname="10.0.0.1",
                port=22,
                username="root",
            )
