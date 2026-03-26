"""
tests/test_terminal_direct.py — direct handler invocation tests for terminal.py.

The ASGI transport used by httpx dispatches handler coroutines in separate
asyncio tasks whose frames are not traced by pytest-cov's settrace-based
tracer.  Calling the handler functions directly from an async test coroutine
ensures that coverage.py records every executed line.

Covers:
- open_session: device not found (404)
- open_session: password device — success path (audit written, session_id returned)
- open_session: password device with no encrypted_password (None password branch)
- open_session: key device — PEM temp-file written, chmod, then unlinked
- open_session: key device with no key_filename (no temp file created)
- open_session: asyncssh.PermissionDenied → 401
- open_session: asyncssh.ConnectionLost → 504
- open_session: asyncssh.HostKeyNotVerifiable → 502
- open_session: OSError → 502
- open_session: asyncssh.Error → 502
- open_session: key device + OSError in create_session → temp file still cleaned up
- terminal_ws: no token → close 4001
- terminal_ws: invalid JWT → close 4001
- terminal_ws: x-forwarded-for header parsed correctly
- terminal_ws: x-real-ip header parsed correctly
- terminal_ws: fallback to websocket.client.host
- terminal_ws: WebSocketDisconnect is silently swallowed
- terminal_ws: audit_ip falls back to source_ip when get_session_meta returns None
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest
from starlette.datastructures import Headers

from backend.models.device import AuthType, Device
from backend.routers.terminal import open_session, terminal_ws
from backend.services.audit import ACTION_SESSION_ENDED, ACTION_SESSION_STARTED
from fastapi import HTTPException, WebSocketDisconnect


# -- Fake helpers --------------------------------------------------------------

class _FakeRequest:
    """Minimal Request stand-in that satisfies get_client_ip."""

    def __init__(self, xff: str | None = None):
        raw: dict[str, str] = {}
        if xff:
            raw["x-forwarded-for"] = xff
        self.headers = Headers(headers=raw)
        self.client = None


class _FakeDB:
    """Minimal AsyncSession stand-in."""

    def __init__(self, device: Device | None = None):
        self._device = device

    async def get(self, cls, pk):
        return self._device

    async def add(self, obj):
        pass

    async def commit(self):
        pass


@pytest.fixture(autouse=True)
def _mock_probe_fingerprint():
    """Avoid real-network SSH fingerprint probes in direct tests."""
    with patch(
        "backend.routers.terminal.probe_ssh_host_fingerprint",
        new=AsyncMock(return_value="AA:BB:CC"),
    ):
        yield


def _password_device(encrypted: bool = True) -> Device:
    d = MagicMock(spec=Device)
    d.id = 1
    d.name = "test-box"
    d.hostname = "192.168.1.10"
    d.port = 22
    d.username = "root"
    d.auth_type = AuthType.password
    d.encrypted_password = b"encrypted-blob" if encrypted else None
    d.key_filename = None
    d.ssh_host_fingerprint = "AA:BB:CC"
    return d


def _key_device(has_key: bool = True) -> Device:
    d = MagicMock(spec=Device)
    d.id = 2
    d.name = "key-box"
    d.hostname = "10.0.0.1"
    d.port = 22
    d.username = "deploy"
    d.auth_type = AuthType.key
    d.encrypted_password = None
    d.key_filename = "deploy.pem" if has_key else None
    d.ssh_host_fingerprint = "AA:BB:CC"
    return d


# -- open_session --------------------------------------------------------------

async def test_open_session_direct_device_not_found():
    """open_session raises 404 when the device does not exist in the DB."""
    with pytest.raises(HTTPException) as exc_info:
        await open_session(99999, _FakeRequest(), False, _FakeDB(device=None), "admin")
    assert exc_info.value.status_code == 404


async def test_open_session_direct_password_device_success():
    """Password device: decrypt is called, session created, audit written."""
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=True)

    with (
        patch("backend.routers.terminal.decrypt", return_value="cleartext-pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(return_value=fake_id),
        ),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()) as mock_audit,
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result == {"session_id": fake_id}
    mock_audit.assert_called_once()
    call_kwargs = mock_audit.call_args
    assert call_kwargs.args[2] == ACTION_SESSION_STARTED


async def test_open_session_direct_password_device_no_password():
    """Password device with no encrypted_password: password stays None."""
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=False)

    with (
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(return_value=fake_id),
        ) as mock_create,
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id
    _, kwargs = mock_create.call_args
    assert kwargs["password"] is None


async def test_open_session_direct_key_device_no_key_filename():
    """Key device with no key_filename: no temp file, key_path stays None."""
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=False)

    with (
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(return_value=fake_id),
        ) as mock_create,
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id
    _, kwargs = mock_create.call_args
    assert kwargs["private_key_path"] is None


async def test_open_session_direct_key_device_writes_temp_file():
    """Key device: PEM is written to a temp file that is deleted after the call."""
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=True)
    captured_paths: list[str] = []

    original_unlink = os.unlink

    def _capture_unlink(path: str):
        captured_paths.append(path)
        original_unlink(path)

    with (
        patch("backend.routers.terminal.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(return_value=fake_id),
        ),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.os.unlink", side_effect=_capture_unlink),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id
    assert len(captured_paths) == 1
    # Temp file must have been removed
    assert not os.path.exists(captured_paths[0])


async def test_open_session_direct_key_device_temp_file_cleaned_on_error():
    """Key device: temp file is deleted even when create_session raises."""
    device = _key_device(has_key=True)
    captured_paths: list[str] = []

    original_unlink = os.unlink

    def _capture_unlink(path: str):
        captured_paths.append(path)
        original_unlink(path)

    with (
        patch("backend.routers.terminal.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(side_effect=OSError("refused")),
        ),
        patch("backend.routers.terminal.os.unlink", side_effect=_capture_unlink),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert exc_info.value.status_code == 502
    assert len(captured_paths) == 1


async def test_open_session_direct_unlink_oserror_is_swallowed():
    """OSError raised by os.unlink inside finally must be silently suppressed."""
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=True)

    with (
        patch("backend.routers.terminal.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(return_value=fake_id),
        ),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        # Make unlink raise to exercise the except OSError: pass branch
        patch("backend.routers.terminal.os.unlink", side_effect=OSError("busy")),
    ):
        # Must not raise — the OSError from unlink must be swallowed
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id


async def test_open_session_direct_permission_denied_returns_502():
    """asyncssh.PermissionDenied must map to HTTP 502 (not 401, to avoid forcing logout)."""
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="bad pw")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_connection_lost_returns_504():
    """asyncssh.ConnectionLost must map to HTTP 504."""
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(side_effect=asyncssh.ConnectionLost(reason="lost")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 504


async def test_open_session_direct_host_key_not_verifiable_returns_502():
    """asyncssh.HostKeyNotVerifiable must map to HTTP 502."""
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(
                side_effect=asyncssh.HostKeyNotVerifiable(reason="mismatch")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502
    assert "Host key not verifiable" in exc_info.value.detail


async def test_open_session_direct_oserror_returns_502():
    """OSError must map to HTTP 502."""
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(side_effect=OSError("refused")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_asyncssh_error_returns_502():
    """Generic asyncssh.Error must map to HTTP 502."""
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(
                side_effect=asyncssh.Error(code=0, reason="unexpected")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502


# -- terminal_ws ---------------------------------------------------------------

def _make_mock_ws(token: str | None = None, headers: dict | None = None) -> MagicMock:
    """Build a minimal WebSocket mock."""
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
    """Generate a valid JWT using test settings."""
    from backend.config import get_settings
    from jose import jwt as jose_jwt
    import uuid
    from backend.main import BOOT_ID

    settings = get_settings()
    return jose_jwt.encode(
        {"sub": "admin", "jti": str(uuid.uuid4()), "bid": BOOT_ID},
        settings.secret_key,
        algorithm="HS256",
    )


async def test_ws_direct_no_token_closes_4001():
    """WebSocket with no token query-param must be closed with code 4001."""
    ws = _make_mock_ws(token=None)
    await terminal_ws("fake-session", ws)
    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_invalid_token_closes_4001():
    """WebSocket with an invalid JWT must be closed with code 4001."""
    ws = _make_mock_ws(token="this.is.garbage")
    await terminal_ws("fake-session", ws)
    ws.close.assert_called_once_with(code=4001)
    ws.accept.assert_not_called()


async def test_ws_direct_xff_header_parsed():
    """X-Forwarded-For header must be extracted as source_ip."""
    token = _valid_token()
    ws = _make_mock_ws(
        token=token,
        headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"},
    )
    fake_id = str(uuid.uuid4())

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("MyBox", "admin", "203.0.113.5"),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    ws.accept.assert_called_once()


async def test_ws_direct_xri_header_parsed():
    """X-Real-IP header must be used when X-Forwarded-For is absent."""
    token = _valid_token()
    ws = _make_mock_ws(
        token=token,
        headers={"x-real-ip": "10.20.30.40"},
    )
    fake_id = str(uuid.uuid4())

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
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
        await terminal_ws(fake_id, ws)

    ws.accept.assert_called_once()


async def test_ws_direct_client_host_fallback():
    """websocket.client.host is used when no forwarded-for headers are present."""
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
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
        await terminal_ws(fake_id, ws)

    ws.accept.assert_called_once()


async def test_ws_direct_websocket_disconnect_is_swallowed():
    """WebSocketDisconnect must be caught silently (no error frame sent)."""
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())

    with (
        patch(
            "backend.routers.terminal.stream_session",
            new=AsyncMock(side_effect=WebSocketDisconnect()),
        ),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("MyBox", "admin", "1.2.3.4"),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    # No error frame should be sent for a clean disconnect
    ws.send_bytes.assert_not_called()


async def test_ws_direct_unexpected_exception_sends_error_frame():
    """An unexpected exception in stream_session must call _ws_error."""
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())

    with (
        patch(
            "backend.routers.terminal.stream_session",
            new=AsyncMock(side_effect=RuntimeError("bang")),
        ),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("MyBox", "admin", "1.2.3.4"),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal._ws_error", new=AsyncMock()) as mock_ws_error,
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    mock_ws_error.assert_called_once_with(ws, "bang")


async def test_ws_direct_audit_ip_falls_back_to_source_ip():
    """When get_session_meta returns no audit_ip, source_ip from the token decode is used."""
    token = _valid_token()
    ws = _make_mock_ws(
        token=token,
        headers={"x-real-ip": "55.66.77.88"},
    )
    fake_id = str(uuid.uuid4())
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"user": user, "action": action, "kwargs": kwargs})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch(
            "backend.routers.terminal.get_session_meta",
            # audit_ip is None → must fall back to source_ip parsed from x-real-ip
            return_value=("MyBox", "admin", None),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert captured_audit_calls[0]["kwargs"]["source_ip"] == "55.66.77.88"


async def test_ws_direct_audit_user_falls_back_to_token_username():
    """When get_session_meta returns no audit_user, the JWT sub claim is used."""
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"user": user, "action": action})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch(
            "backend.routers.terminal.get_session_meta",
            # audit_user is empty string → must fall back to JWT sub
            return_value=("", "", None),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert captured_audit_calls[0]["user"] == "admin"


async def test_ws_direct_session_ended_audit_uses_device_label():
    """SESSION_ENDED audit detail includes device_label when available."""
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"action": action, "detail": kwargs.get("detail", "")})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("MyBox (10.0.0.1:22)", "admin", "1.1.1.1"),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
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
    """SESSION_ENDED audit detail uses session id when device_label is empty."""
    token = _valid_token()
    ws = _make_mock_ws(token=token, headers={})
    fake_id = str(uuid.uuid4())
    captured_audit_calls: list = []

    async def _capture_audit(db, user, action, **kwargs):
        captured_audit_calls.append({"action": action, "detail": kwargs.get("detail", "")})

    with (
        patch("backend.routers.terminal.stream_session", new=AsyncMock()),
        patch(
            "backend.routers.terminal.get_session_meta",
            return_value=("", "admin", "1.1.1.1"),
        ),
        patch("backend.routers.terminal.close_session", new=AsyncMock()),
        patch("backend.routers.terminal.write_audit", new=AsyncMock(side_effect=_capture_audit)),
        patch("backend.database.AsyncSessionLocal") as mock_sl,
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx
        await terminal_ws(fake_id, ws)

    assert len(captured_audit_calls) == 1
    assert fake_id[:8] in captured_audit_calls[0]["detail"]
