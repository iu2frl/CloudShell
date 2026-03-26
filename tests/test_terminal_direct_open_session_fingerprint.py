"""Direct open_session tests for SSH fingerprint trust and mismatch flows."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.datastructures import Headers

from backend.models.device import AuthType, Device
from backend.routers.terminal import _consume_ws_ticket, _ws_tickets, open_session
from backend.services.ssh import (
    SSHHostFingerprintMismatchError,
    SSHHostFingerprintUnavailableError,
)
from fastapi import HTTPException


class _FakeRequest:
    """Minimal Request stand-in that satisfies get_client_ip."""

    def __init__(self):
        self.headers = Headers(headers={})
        self.client = None


class _FakeDB:
    """Minimal AsyncSession stand-in with commit tracking."""

    def __init__(self, device: Device | None = None):
        self._device = device
        self.committed = False

    async def get(self, cls, pk):
        return self._device

    async def add(self, obj):
        pass

    async def commit(self):
        self.committed = True


@pytest.fixture(autouse=True)
def _mock_probe_fingerprint():
    """Avoid real-network SSH fingerprint probes in direct tests."""
    with patch(
        "backend.routers.terminal.probe_ssh_host_fingerprint",
        new=AsyncMock(return_value="AA:BB:CC"),
    ):
        yield


def _password_device(ssh_host_fingerprint: str | None = "AA:BB:CC") -> Device:
    device = MagicMock(spec=Device)
    device.id = 1
    device.name = "test-box"
    device.hostname = "192.168.1.10"
    device.port = 22
    device.username = "root"
    device.auth_type = AuthType.password
    device.encrypted_password = None
    device.key_filename = None
    device.ssh_host_fingerprint = ssh_host_fingerprint
    return device


async def test_consume_ws_ticket_purges_expired_and_missing_returns_none():
    _ws_tickets.clear()
    _ws_tickets["expired"] = (
        "sess-1",
        "admin",
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    consumed = await _consume_ws_ticket("missing", "sess-1")

    assert consumed is None
    assert "expired" not in _ws_tickets


async def test_consume_ws_ticket_session_mismatch_returns_none():
    _ws_tickets.clear()
    _ws_tickets["ticket-1"] = (
        "sess-a",
        "admin",
        datetime.now(timezone.utc) + timedelta(seconds=60),
    )

    consumed = await _consume_ws_ticket("ticket-1", "sess-b")

    assert consumed is None


async def test_open_session_direct_fingerprint_unavailable_returns_502():
    device = _password_device()

    with patch(
        "backend.routers.terminal.probe_ssh_host_fingerprint",
        new=AsyncMock(side_effect=SSHHostFingerprintUnavailableError("probe failed")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert exc_info.value.status_code == 502


async def test_open_session_direct_untrusted_host_requires_confirmation():
    device = _password_device(ssh_host_fingerprint=None)

    with patch(
        "backend.routers.terminal.probe_ssh_host_fingerprint",
        new=AsyncMock(return_value="11:22:33"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SSH_HOST_UNTRUSTED"
    assert exc_info.value.detail["fingerprint"] == "11:22:33"


async def test_open_session_direct_untrusted_host_can_be_pinned_with_trust():
    fake_id = str(uuid.uuid4())
    device = _password_device(ssh_host_fingerprint=None)
    db = _FakeDB(device)

    with (
        patch(
            "backend.routers.terminal.probe_ssh_host_fingerprint",
            new=AsyncMock(return_value="11:22:33"),
        ),
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)) as mock_create,
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), True, db, "admin")

    assert result["session_id"] == fake_id
    assert device.ssh_host_fingerprint == "11:22:33"
    assert db.committed is True
    _, kwargs = mock_create.call_args
    assert kwargs["expected_ssh_host_fingerprint"] == "11:22:33"


async def test_open_session_direct_changed_host_requires_confirmation():
    device = _password_device(ssh_host_fingerprint="AA:AA:AA")

    with patch(
        "backend.routers.terminal.probe_ssh_host_fingerprint",
        new=AsyncMock(return_value="BB:BB:BB"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SSH_HOST_CHANGED"
    assert exc_info.value.detail["fingerprint"] == "BB:BB:BB"
    assert exc_info.value.detail["previous_fingerprint"] == "AA:AA:AA"


async def test_open_session_direct_changed_host_can_be_replaced_with_trust():
    fake_id = str(uuid.uuid4())
    device = _password_device(ssh_host_fingerprint="AA:AA:AA")
    db = _FakeDB(device)

    with (
        patch(
            "backend.routers.terminal.probe_ssh_host_fingerprint",
            new=AsyncMock(return_value="BB:BB:BB"),
        ),
        patch("backend.routers.terminal.create_session", new=AsyncMock(return_value=fake_id)) as mock_create,
        patch("backend.routers.terminal.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), True, db, "admin")

    assert result["session_id"] == fake_id
    assert device.ssh_host_fingerprint == "BB:BB:BB"
    assert db.committed is True
    _, kwargs = mock_create.call_args
    assert kwargs["expected_ssh_host_fingerprint"] == "BB:BB:BB"


async def test_open_session_direct_fingerprint_mismatch_error_maps_to_409():
    device = _password_device(ssh_host_fingerprint="AA:AA:AA")

    with (
        patch(
            "backend.routers.terminal.probe_ssh_host_fingerprint",
            new=AsyncMock(return_value="AA:AA:AA"),
        ),
        patch(
            "backend.routers.terminal.create_session",
            new=AsyncMock(
                side_effect=SSHHostFingerprintMismatchError(
                    expected="AA:AA:AA",
                    presented="CC:CC:CC",
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), False, _FakeDB(device), "admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SSH_HOST_CHANGED"
    assert exc_info.value.detail["fingerprint"] == "CC:CC:CC"
    assert exc_info.value.detail["previous_fingerprint"] == "AA:AA:AA"
