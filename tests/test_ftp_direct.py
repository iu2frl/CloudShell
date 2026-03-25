"""
tests/test_ftp_direct.py — direct-call coverage tests for backend/routers/ftp.py
and the one missed line in backend/services/ftp.py.

The ASGI transport used by httpx does NOT propagate Python's sys.settrace into
handler coroutines, so pytest-cov cannot record those lines even when the HTTP
tests pass.  Calling handlers directly keeps the coverage tracer active.

Covers all lines missed by the ASGI-based test suite:
- routers/ftp.py  lines 62-104  (entire open_session body)
- services/ftp.py line 177      (result.sort(...) in list_directory)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from backend.models.device import AuthType, ConnectionType, Device
from backend.routers.ftp import (
    DeleteRequest,
    MkdirRequest,
    RenameRequest,
    close_session,
    delete_path,
    download_file,
    list_dir,
    make_directory,
    open_session,
    rename_path,
    upload_file,
)
from backend.services.ftp import list_directory


# -- Fake helpers --------------------------------------------------------------

class _FakeRequest:
    def __init__(self):
        self.headers = Headers(headers={})
        self.client = None


class _FakeDB:
    def __init__(self, device=None):
        self._device = device
        self.committed = False

    async def get(self, cls, pk):
        return self._device

    async def commit(self):
        self.committed = True


def _make_device(connection_type: ConnectionType = ConnectionType.ftp,
                 encrypted_password: str | None = "enc-pw") -> Device:
    """Build a minimal Device instance for testing."""
    dev = Device(
        name="ftp-srv",
        hostname="192.168.1.30",
        port=21,
        username="ftpuser",
        auth_type=AuthType.password,
        connection_type=connection_type,
    )
    dev.id = 1
    dev.encrypted_password = encrypted_password
    dev.key_filename = None
    return dev


# -- open_session --------------------------------------------------------------

async def test_open_session_device_not_found():
    """open_session raises 404 when the device_id is not in the DB."""
    db = _FakeDB(device=None)
    with pytest.raises(HTTPException) as exc_info:
        await open_session(device_id=99, request=_FakeRequest(), db=db, current_user="admin")
    assert exc_info.value.status_code == 404


async def test_open_session_wrong_connection_type():
    """open_session raises 400 when the device is not FTP/FTPS."""
    dev = _make_device(connection_type=ConnectionType.ssh)
    db = _FakeDB(device=dev)
    with pytest.raises(HTTPException) as exc_info:
        await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")
    assert exc_info.value.status_code == 400
    assert "FTP" in exc_info.value.detail


async def test_open_session_success_ftp():
    """open_session returns a session_id for a plain FTP device."""
    dev = _make_device(connection_type=ConnectionType.ftp)
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.decrypt", return_value="plain-pw"), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock, return_value="sess-1") as mock_open, \
         patch("backend.routers.ftp.write_audit", new_callable=AsyncMock):
        result = await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    assert result == {"session_id": "sess-1"}
    mock_open.assert_awaited_once()
    # use_tls must be False for plain FTP
    _, kwargs = mock_open.call_args
    assert kwargs.get("use_tls") is False


async def test_open_session_success_ftps():
    """open_session passes use_tls=True for an FTPS device."""
    dev = _make_device(connection_type=ConnectionType.ftps)
    db = _FakeDB(device=dev)

    settings = MagicMock()
    settings.ftps_allow_insecure = True

    with patch("backend.routers.ftp.decrypt", return_value="plain-pw"), \
         patch("backend.routers.ftp.get_settings", return_value=settings), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock, return_value="sess-2") as mock_open, \
         patch("backend.routers.ftp.write_audit", new_callable=AsyncMock):
        result = await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    assert result == {"session_id": "sess-2"}
    _, kwargs = mock_open.call_args
    assert kwargs.get("use_tls") is True


async def test_open_session_no_encrypted_password():
    """open_session passes password=None when the device has no encrypted_password."""
    dev = _make_device(connection_type=ConnectionType.ftp, encrypted_password=None)
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock, return_value="sess-3") as mock_open, \
         patch("backend.routers.ftp.write_audit", new_callable=AsyncMock):
        await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    _, kwargs = mock_open.call_args
    assert kwargs.get("password") is None


async def test_open_session_permission_error_raises_502():
    """open_session raises 502 (not 401) when the FTP service raises PermissionError, to avoid forcing logout."""
    dev = _make_device()
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock,
               side_effect=PermissionError("bad creds")):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    assert exc_info.value.status_code == 502
    assert "authentication failed" in exc_info.value.detail.lower()


async def test_open_session_connection_refused_raises_502():
    """open_session raises 502 when the FTP service raises ConnectionRefusedError."""
    dev = _make_device()
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock,
               side_effect=ConnectionRefusedError("port closed")):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    assert exc_info.value.status_code == 502
    assert "refused" in exc_info.value.detail.lower()


async def test_open_session_oserror_raises_502():
    """open_session raises 502 when the FTP service raises an OSError."""
    dev = _make_device()
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock,
               side_effect=OSError("network unreachable")):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    assert exc_info.value.status_code == 502
    assert "failed" in exc_info.value.detail.lower()


async def test_open_session_generic_exception_raises_502():
    """open_session raises 502 for any unexpected exception from the FTP service."""
    dev = _make_device()
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock,
               side_effect=RuntimeError("unexpected")):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    assert exc_info.value.status_code == 502


async def test_open_session_writes_ftp_audit_label():
    """open_session audit detail includes 'FTP' (not 'FTPS') for plain FTP."""
    dev = _make_device(connection_type=ConnectionType.ftp)
    db = _FakeDB(device=dev)

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock, return_value="s"), \
         patch("backend.routers.ftp.write_audit", new_callable=AsyncMock) as mock_audit:
        await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    detail = mock_audit.call_args.kwargs.get("detail", "")
    assert "FTPS" not in detail
    assert "FTP" in detail


async def test_open_session_writes_ftps_audit_label():
    """open_session audit detail includes 'FTPS' for an FTPS device."""
    dev = _make_device(connection_type=ConnectionType.ftps)
    db = _FakeDB(device=dev)

    settings = MagicMock()
    settings.ftps_allow_insecure = True

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.get_settings", return_value=settings), \
         patch("backend.routers.ftp.open_ftp_session", new_callable=AsyncMock, return_value="s"), \
         patch("backend.routers.ftp.write_audit", new_callable=AsyncMock) as mock_audit:
        await open_session(device_id=1, request=_FakeRequest(), db=db, current_user="admin")

    detail = mock_audit.call_args.kwargs.get("detail", "")
    assert "FTPS" in detail


# -- services/ftp.py — list_directory sort (line 177) -------------------------

async def test_list_directory_sort_dirs_before_files():
    """list_directory returns directories before files, sorted by name, and skips dot entries."""
    import backend.services.ftp as ftp_svc

    fake_client = MagicMock()

    def _path(name: str):
        """Return a MagicMock that behaves like PurePosixPath with .name == name."""
        m = MagicMock()
        m.name = name
        return m

    async def _fake_list(path, recursive=False):
        yield _path("beta.txt"), {"type": "file", "size": "10", "modify": "20240101000000"}
        yield _path("alpha"), {"type": "dir", "size": "0", "modify": "20240101000000"}
        yield _path("gamma.txt"), {"type": "file", "size": "5", "modify": "20240101000000"}
        # FTP servers yield "." and ".." — these must be skipped (covers the continue branch)
        yield _path("."), {"type": "dir", "size": "0", "modify": "20240101000000"}
        yield _path(".."), {"type": "dir", "size": "0", "modify": "20240101000000"}

    fake_client.list = _fake_list
    fake_entry = ftp_svc._FtpSession(client=fake_client, device_label="test")
    session_id = "sort-test-session"

    # Insert directly into the live session store; use try/finally to clean up
    # even if the autouse fixture from test_ftp_service.py is in play.
    ftp_svc._ftp_sessions[session_id] = fake_entry
    try:
        entries = await list_directory(session_id, "/")
    finally:
        ftp_svc._ftp_sessions.pop(session_id, None)

    names = [e["name"] for e in entries]
    # dot entries must be filtered out
    assert "." not in names
    assert ".." not in names
    # 'alpha' dir must come first, then files alphabetically
    assert names[0] == "alpha"
    assert names[1] == "beta.txt"
    assert names[2] == "gamma.txt"
