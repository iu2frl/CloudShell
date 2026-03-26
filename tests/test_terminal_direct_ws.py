"""Direct terminal_ws tests for token and websocket behavior."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.routers.terminal import terminal_ws
from backend.services.audit import ACTION_SESSION_ENDED
from fastapi import WebSocketDisconnect


@pytest.fixture(autouse=True)
def _mock_revocation_check():
    """Avoid DB lookups for revoked tokens in direct websocket tests."""
    with patch("backend.routers.auth._is_revoked", new=AsyncMock(return_value=False)):
        yield


def _make_mock_ws(token: str | None = None, headers: dict | None = None) -> MagicMock:
    from fastapi import WebSocket

    ws = MagicMock(spec=WebSocket)
    ws.query_params = {"token": token} if token else {}
    ws.headers = headers or {}
    ws.client = MagicMock()
    ws.client.host = "127.0.0.1"
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


def _valid_token() -> str:
    from backend.config import get_settings
    from backend.main import BOOT_ID
    from jose import jwt as jose_jwt

    settings = get_settings()
    return jose_jwt.encode(
        {"sub": "admin", "jti": str(uuid.uuid4()), "bid": BOOT_ID},
        settings.secret_key,
        algorithm="HS256",
    )


async def test_ws_direct_no_token_closes_4001():
    ws = _make_mock_ws(token=None)
    await terminal_ws("fake-session", ws)
    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_invalid_token_closes_4001():
    ws = _make_mock_ws(token="this.is.garbage")
    await terminal_ws("fake-session", ws)
    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_invalid_ticket_closes_4001():
    ws = _make_mock_ws(token=None)
    ws.query_params = {"ticket": "invalid-ticket"}

    await terminal_ws("fake-session", ws)

    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_token_missing_jti_closes_4001():
    from backend.config import get_settings
    from backend.main import BOOT_ID
    from jose import jwt as jose_jwt

    settings = get_settings()
    token = jose_jwt.encode(
        {"sub": "admin", "bid": BOOT_ID},
        settings.secret_key,
        algorithm="HS256",
    )
    ws = _make_mock_ws(token=token)

    await terminal_ws("fake-session", ws)

    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_xff_header_parsed():
    token = _valid_token()
    ws = _make_mock_ws(
        token=token,
        headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"},
    )
    fake_id = str(uuid.uuid4())

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
    token = _valid_token()
    ws = _make_mock_ws(
        token=token,
        headers={"x-real-ip": "10.20.30.40"},
    )
    fake_id = str(uuid.uuid4())

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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())

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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())

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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())

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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
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
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
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
