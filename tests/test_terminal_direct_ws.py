"""Direct terminal_ws tests for ticket-based websocket behavior."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.routers.terminal import _issue_ws_ticket, terminal_ws
from backend.services.audit import ACTION_SESSION_ENDED
from fastapi import WebSocketDisconnect


def _make_mock_ws(ticket: str | None = None, headers: dict | None = None) -> MagicMock:
    from fastapi import WebSocket

    ws = MagicMock(spec=WebSocket)
    ws.query_params = {"ticket": ticket} if ticket else {}
    ws.headers = headers or {}
    ws.client = MagicMock()
    ws.client.host = "127.0.0.1"
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws

async def test_ws_direct_no_token_closes_4001():
    ws = _make_mock_ws(ticket=None)
    await terminal_ws("fake-session", ws)
    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_invalid_ticket_closes_4001():
    ws = _make_mock_ws(ticket="invalid-ticket")
    await terminal_ws("fake-session", ws)
    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_legacy_token_query_param_rejected():
    ws = _make_mock_ws(ticket=None)
    ws.query_params = {"token": "legacy.jwt.value"}

    await terminal_ws("fake-session", ws)

    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_xff_header_parsed():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(
        ticket=ticket,
        headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"},
    )

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_session_meta", return_value=("MyBox", "admin", "203.0.113.5")),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    ws.accept.assert_called_once()


async def test_ws_direct_xri_header_parsed():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(
        ticket=ticket,
        headers={"x-real-ip": "10.20.30.40"},
    )

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_session_meta", return_value=("", "admin", None)),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    ws.accept.assert_called_once()


async def test_ws_direct_client_host_fallback():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_session_meta", return_value=("", "admin", None)),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    ws.accept.assert_called_once()


async def test_ws_direct_websocket_disconnect_is_swallowed():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})

    with (
        patch(
            "backend.routers.terminal.stream_session",
            new=AsyncMock(side_effect=WebSocketDisconnect()),
        ),
        patch("backend.routers.terminal.get_session_meta", return_value=("MyBox", "admin", "1.2.3.4")),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    ws.send_bytes.assert_not_called()


async def test_ws_direct_unexpected_exception_sends_error_frame():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock(side_effect=RuntimeError("bang"))),
        patch("backend.routers.terminal.get_session_meta", return_value=("MyBox", "admin", "1.2.3.4")),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal._ws_error", new=AsyncMock()) as mock_ws_error,
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    mock_ws_error.assert_called_once_with(ws, "bang")


async def test_ws_direct_audit_ip_falls_back_to_source_ip():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"user": user, "action": action, "kwargs": kwargs})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_client_ip", return_value="55.66.77.88"),
        patch("backend.routers.terminal.get_session_meta", return_value=("MyBox", "admin", None)),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert captured_audit_calls[0]["kwargs"]["source_ip"] == "55.66.77.88"


async def test_ws_direct_audit_user_falls_back_to_token_username():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"user": user, "action": action})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_session_meta", return_value=("", "", None)),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert captured_audit_calls[0]["user"] == "admin"


async def test_ws_direct_session_ended_audit_uses_device_label():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"action": action, "detail": kwargs.get("detail", "")})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_session_meta", return_value=("MyBox (10.0.0.1:22)", "admin", "1.1.1.1")),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert captured_audit_calls[0]["action"] == ACTION_SESSION_ENDED
    assert "MyBox" in captured_audit_calls[0]["detail"]


async def test_ws_direct_session_ended_audit_fallback_detail():
    fake_id = str(uuid.uuid4())
    ticket = await _issue_ws_ticket(fake_id, "admin")
    ws = _make_mock_ws(ticket=ticket, headers={})
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"action": action, "detail": kwargs.get("detail", "")})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch("backend.routers.terminal.get_session_meta", return_value=("", "admin", "1.1.1.1")),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.routers.terminal.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert fake_id[:8] in captured_audit_calls[0]["detail"]
