"""Direct open_session tests for core terminal behaviors."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest
from starlette.datastructures import Headers

from backend.models.device import AuthType, Device
from backend.routers.terminal import open_session
from backend.services.audit import ACTION_SESSION_STARTED
from fastapi import HTTPException


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
    device = MagicMock(spec=Device)
    device.id = 1
    device.name = "test-box"
    device.hostname = "192.168.1.10"
    device.port = 22
    device.username = "root"
    device.auth_type = AuthType.password
    device.encrypted_password = b"encrypted-blob" if encrypted else None
    device.key_filename = None
    device.ssh_host_fingerprint = "AA:BB:CC"
    return device


def _key_device(has_key: bool = True) -> Device:
    device = MagicMock(spec=Device)
    device.id = 2
    device.name = "key-box"
    device.hostname = "10.0.0.1"
    device.port = 22
    device.username = "deploy"
    device.auth_type = AuthType.key
    device.encrypted_password = None
    device.key_filename = "deploy.pem" if has_key else None
    device.ssh_host_fingerprint = "AA:BB:CC"
    return device


async def test_open_session_direct_device_not_found():
    with pytest.raises(HTTPException) as exc_info:
        await open_session(99999, _FakeRequest(), False, _FakeDB(device=None), "admin")
    assert exc_info.value.status_code == 404


async def test_open_session_direct_password_device_success():
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=True)

    with (
        patch("backend.routers.terminal.decrypt", return_value="cleartext-pw"),
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()) as mock_audit,
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result == {"session_id": fake_id}
    mock_audit.assert_called_once()
    call_args = mock_audit.call_args
    assert call_args.args[2] == ACTION_SESSION_STARTED


async def test_open_session_direct_password_device_no_password():
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=False)

    with (
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)) as mock_create,
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id
    _, kwargs = mock_create.call_args
    assert kwargs["password"] is None


async def test_open_session_direct_key_device_no_key_filename():
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=False)

    with (
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)) as mock_create,
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id
    _, kwargs = mock_create.call_args
    assert kwargs["private_key_path"] is None


async def test_open_session_direct_key_device_writes_temp_file():
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=True)
    captured_paths: list[str] = []

    original_unlink = os.unlink

    def _capture_unlink(path: str):
        captured_paths.append(path)
        original_unlink(path)

    with (
        patch(
            "backend.routers.terminal.load_decrypted_key",
            return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        ),
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.os.unlink", side_effect=_capture_unlink),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id
    assert len(captured_paths) == 1
    assert not os.path.exists(captured_paths[0])


async def test_open_session_direct_key_device_temp_file_cleaned_on_error():
    device = _key_device(has_key=True)
    captured_paths: list[str] = []

    original_unlink = os.unlink

    def _capture_unlink(path: str):
        captured_paths.append(path)
        original_unlink(path)

    with (
        patch(
            "backend.routers.terminal.load_decrypted_key",
            return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        ),
        patch("backend.routers.terminal.create_session", new=AsyncMock(side_effect=OSError("refused"))),
        patch("backend.routers.terminal.os.unlink", side_effect=_capture_unlink),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert exc_info.value.status_code == 502
    assert len(captured_paths) == 1


async def test_open_session_direct_unlink_oserror_is_swallowed():
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=True)

    with (
        patch(
            "backend.routers.terminal.load_decrypted_key",
            return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        ),
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)),
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
        patch("backend.routers.terminal.os.unlink", side_effect=OSError("busy")),
    ):
        result = await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert result["session_id"] == fake_id


async def test_open_session_direct_permission_denied_returns_502():
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
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable(reason="mismatch")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_oserror_returns_502():
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch("backend.routers.terminal.create_session", new=AsyncMock(side_effect=OSError("refused"))),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_asyncssh_error_returns_502():
    device = _password_device()
    with (
        patch("backend.routers.terminal.decrypt", return_value="pw"),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(side_effect=asyncssh.Error(code=0, reason="unexpected")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")
    assert exc_info.value.status_code == 502
