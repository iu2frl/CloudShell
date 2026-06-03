"""
tests/test_devices_direct.py — direct-call coverage tests for backend/routers/devices.py.

The ASGI transport used by httpx does NOT propagate Python's sys.settrace into
the handler coroutines it spawns, so pytest-cov cannot record those lines even
when the HTTP tests pass. Calling the handler functions directly keeps the
coverage tracer active throughout.

Covers all lines missed by the ASGI-based test suite:
- list_devices:    line 75  (return result.scalars().all())
- create_device:   line 105 (HTTPException – password missing)
                   lines 109-110 (key path: db.add + db.flush)
                   lines 120-122 (success path: commit + refresh + return)
- update_device:   lines 136-152 (full handler body)
- delete_device:   lines 165-173 (full handler body)
"""
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from backend.models.device import AuthType, ConnectionType, Device
from backend.routers.devices import (
    DeviceCreate,
    DeviceUpdate,
    create_device,
    delete_device,
    get_device,
    list_devices,
    update_device,
)
from backend.services.crypto import generate_key_pair


# -- Fake helpers --------------------------------------------------------------

class _FakeDB:
    """Minimal AsyncSession duck-type that records calls for assertions."""

    def __init__(self, device=None, device_list=None):
        self._device = device
        self._device_list = device_list or []
        self.added = []
        self.deleted = []
        self.committed = False
        self.flushed = False
        self.refreshed = []

    async def get(self, cls, pk):
        return self._device

    async def execute(self, stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = self._device_list
        return mock_result

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True
        # Assign a fake id so _store_key receives an integer
        for obj in self.added:
            if not getattr(obj, "id", None):
                obj.id = 999

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)


# -- list_devices --------------------------------------------------------------

async def test_list_devices_direct_empty():
    """list_devices returns an empty list when no devices exist."""
    db = _FakeDB(device_list=[])
    result = await list_devices(db=db, _="admin")
    assert result == []


async def test_list_devices_direct_returns_items():
    """list_devices returns the list produced by the DB query."""
    dev1 = MagicMock(spec=Device)
    dev2 = MagicMock(spec=Device)
    db = _FakeDB(device_list=[dev1, dev2])
    result = await list_devices(db=db, _="admin")
    assert result == [dev1, dev2]


# -- create_device – password path --------------------------------------------

async def test_create_device_password_missing_raises_400():
    """create_device with auth_type=password but no password must raise HTTP 400."""
    payload = DeviceCreate(
        name="srv",
        hostname="1.2.3.4",
        port=22,
        username="root",
        auth_type=AuthType.password,
        password=None,
    )
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await create_device(payload=payload, db=db, _="admin")
    assert exc_info.value.status_code == 400
    assert "password" in exc_info.value.detail


async def test_create_device_password_success():
    """create_device with a valid password commits and refreshes the device."""
    payload = DeviceCreate(
        name="srv",
        hostname="1.2.3.4",
        port=22,
        username="root",
        auth_type=AuthType.password,
        password="s3cr3t",
    )
    db = _FakeDB()

    with patch("backend.routers.devices.encrypt", return_value="enc-pw"):
        device = await create_device(payload=payload, db=db, _="admin")

    assert db.committed
    assert device in db.refreshed


async def test_create_device_key_missing_raises_400():
    """create_device with auth_type=key but no private_key must raise HTTP 400."""
    payload = DeviceCreate(
        name="srv",
        hostname="1.2.3.4",
        port=22,
        username="deploy",
        auth_type=AuthType.key,
        private_key=None,
    )
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await create_device(payload=payload, db=db, _="admin")
    assert exc_info.value.status_code == 400
    assert "private_key" in exc_info.value.detail


async def test_create_device_key_success():
    """create_device with a valid PEM key flushes to get an id, stores the key, then commits."""
    pem, _ = generate_key_pair()
    payload = DeviceCreate(
        name="key-srv",
        hostname="10.0.0.1",
        port=22,
        username="deploy",
        auth_type=AuthType.key,
        private_key=pem,
    )
    db = _FakeDB()

    with tempfile.TemporaryDirectory() as keys_dir:
        with patch("backend.config.get_settings") as mock_settings:
            mock_settings.return_value.keys_dir = keys_dir
            device = await create_device(payload=payload, db=db, _="admin")

    # flush must have been called to obtain the DB id before storing the key
    assert db.flushed
    assert db.committed
    assert device in db.refreshed
    assert device.key_filename is not None


# -- get_device ----------------------------------------------------------------

async def test_get_device_not_found():
    """get_device raises HTTP 404 when the device does not exist in the DB."""
    db = _FakeDB(device=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_device(device_id=1, db=db, _="admin")
    assert exc_info.value.status_code == 404


async def test_get_device_found():
    """get_device returns the device when it exists."""
    dev = MagicMock(spec=Device)
    db = _FakeDB(device=dev)
    result = await get_device(device_id=1, db=db, _="admin")
    assert result is dev


# -- update_device -------------------------------------------------------------

async def test_update_device_not_found():
    """update_device raises HTTP 404 when the device does not exist."""
    db = _FakeDB(device=None)
    payload = DeviceUpdate(name="new-name")
    with pytest.raises(HTTPException) as exc_info:
        await update_device(device_id=99, payload=payload, db=db, _="admin")
    assert exc_info.value.status_code == 404


async def test_update_device_scalar_fields():
    """update_device updates simple scalar fields on the device."""
    dev = Device(
        name="old",
        hostname="1.1.1.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 1
    db = _FakeDB(device=dev)
    payload = DeviceUpdate(name="new-name", port=2222)

    device = await update_device(device_id=1, payload=payload, db=db, _="admin")

    assert device.name == "new-name"
    assert device.port == 2222
    assert db.committed


async def test_update_device_folder_id():
    """update_device validates and sets folder_id when provided."""
    dev = Device(
        name="old",
        hostname="1.1.1.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 1
    db = _FakeDB(device=dev)
    payload = DeviceUpdate(folder_id=123)

    with patch("backend.routers.devices.validate_folder_exists", new=AsyncMock()) as mock_validate:
        device = await update_device(device_id=1, payload=payload, db=db, _="admin")

    mock_validate.assert_awaited_once_with(db, 123)
    assert device.folder_id == 123
    assert db.committed


async def test_update_device_password():
    """update_device encrypts and stores a new password when provided."""
    dev = Device(
        name="srv",
        hostname="1.1.1.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 1
    db = _FakeDB(device=dev)
    payload = DeviceUpdate(password="new-secret")

    with patch("backend.routers.devices.encrypt", return_value="enc-new") as mock_enc:
        device = await update_device(device_id=1, payload=payload, db=db, _="admin")

    mock_enc.assert_called_once_with("new-secret")
    assert device.encrypted_password == "enc-new"
    assert db.committed


async def test_update_device_private_key():
    """update_device stores a new encrypted key file when private_key is provided."""
    pem, _ = generate_key_pair()
    dev = Device(
        name="key-srv",
        hostname="10.0.0.1",
        port=22,
        username="deploy",
        auth_type=AuthType.key,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 42
    db = _FakeDB(device=dev)
    payload = DeviceUpdate(private_key=pem)

    with tempfile.TemporaryDirectory() as keys_dir:
        with patch("backend.config.get_settings") as mock_settings:
            mock_settings.return_value.keys_dir = keys_dir
            device = await update_device(device_id=42, payload=payload, db=db, _="admin")

    assert device.key_filename is not None
    assert db.committed


async def test_update_device_commits_and_refreshes():
    """update_device always commits and refreshes even with no field changes."""
    dev = Device(
        name="srv",
        hostname="1.1.1.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 1
    db = _FakeDB(device=dev)
    payload = DeviceUpdate()  # no fields set

    device = await update_device(device_id=1, payload=payload, db=db, _="admin")

    assert db.committed
    assert device in db.refreshed


async def test_update_device_normalizes_fingerprint_fields():
    """update_device strips whitespace and normalizes empty trust fingerprints to None."""
    dev = Device(
        name="srv",
        hostname="1.1.1.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 1
    db = _FakeDB(device=dev)
    payload = DeviceUpdate(
        ssh_host_fingerprint=" 11:22:33 ",
        ftps_cert_thumbprint="   ",
    )

    device = await update_device(device_id=1, payload=payload, db=db, _="admin")

    assert device.ssh_host_fingerprint == "11:22:33"
    assert device.ftps_cert_thumbprint is None
    assert db.committed


# -- delete_device -------------------------------------------------------------

async def test_delete_device_not_found():
    """delete_device raises HTTP 404 when the device does not exist."""
    db = _FakeDB(device=None)
    with pytest.raises(HTTPException) as exc_info:
        await delete_device(device_id=99, db=db, _="admin")
    assert exc_info.value.status_code == 404


async def test_delete_device_password_device():
    """delete_device removes a password-based device without touching the filesystem."""
    dev = Device(
        name="srv",
        hostname="1.1.1.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 1
    dev.key_filename = None
    db = _FakeDB(device=dev)

    with patch("backend.routers.devices.delete_key_file") as mock_del:
        await delete_device(device_id=1, db=db, _="admin")

    mock_del.assert_not_called()
    assert dev in db.deleted
    assert db.committed


async def test_delete_device_key_device_removes_key_file():
    """delete_device calls delete_key_file when the device has a key_filename."""
    dev = Device(
        name="key-srv",
        hostname="10.0.0.1",
        port=22,
        username="deploy",
        auth_type=AuthType.key,
        connection_type=ConnectionType.ssh,
    )
    dev.id = 42
    dev.key_filename = "key_42.enc"
    db = _FakeDB(device=dev)

    with tempfile.TemporaryDirectory() as keys_dir:
        with patch("backend.config.get_settings") as mock_settings, \
             patch("backend.routers.devices.delete_key_file") as mock_del:
            mock_settings.return_value.keys_dir = keys_dir
            await delete_device(device_id=42, db=db, _="admin")

    mock_del.assert_called_once_with("key_42.enc", keys_dir)
    assert dev in db.deleted
    assert db.committed
