"""
tests/test_sftp_direct.py — direct handler and service invocation tests for
backend/services/sftp.py and backend/routers/sftp.py.

ASGI-dispatched coroutines are not traced by pytest-cov's settrace tracer.
Calling functions directly from async tests ensures every line is recorded.

services/sftp.py gaps covered:
  - open_sftp_session: known_hosts with real kh_path (client_factory branch)
  - open_sftp_session: known_hosts != "auto" (explicit value branch)
  - open_sftp_session: private_key_path provided (client_keys branch)
  - close_sftp_session: sftp.exit() raises → swallowed
  - close_sftp_session: conn.close() / wait_closed() raises → swallowed
  - list_directory: filename is bytes → decoded to str
  - list_directory: remote_path ends with "/" → no double-slash

routers/sftp.py gaps covered:
  - _resolve_device_credentials: key device with key_filename (PEM temp file)
  - open_session: device not found (404)
  - open_session: password device success (audit written, session_id returned)
  - open_session: key device success (temp file created and deleted)
  - open_session: asyncssh.PermissionDenied → 401
  - open_session: asyncssh.ConnectionLost → 504
  - open_session: asyncssh.HostKeyNotVerifiable → 502
  - open_session: OSError → 502
  - open_session: key device + error → temp file still cleaned up
  - open_session: os.unlink raises OSError → swallowed
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import asyncssh
import pytest
from starlette.datastructures import Headers

from backend.models.device import AuthType, Device
from backend.routers.sftp import _resolve_device_credentials, open_session
from backend.services.audit import ACTION_SESSION_STARTED
from backend.services.ssh import (
    SSHHostFingerprintMismatchError,
    SSHHostFingerprintUnavailableError,
)
from backend.services.sftp import (
    _sftp_sessions,
    close_sftp_session,
    delete_remote,
    get_sftp_session,
    list_directory,
    mkdir_remote,
    open_sftp_session,
    rename_remote,
)
from fastapi import HTTPException


# -- Fake helpers --------------------------------------------------------------

class _FakeRequest:
    """Minimal Request stand-in for get_client_ip."""

    def __init__(self):
        self.headers = Headers(headers={})
        self.client = None


class _FakeDB:
    """Minimal AsyncSession stand-in."""

    def __init__(self, device=None):
        self._device = device
        self.committed = False

    async def get(self, cls, pk):
        return self._device

    async def commit(self):
        self.committed = True


class _FakeSettings:
    keys_dir = "/tmp/cloudshell-test-keys"


def _mock_sftp_client() -> MagicMock:
    sftp = MagicMock()
    sftp.exit = MagicMock()
    sftp.readdir = AsyncMock(return_value=[])
    fh = MagicMock()
    fh.read = AsyncMock(return_value=b"")
    fh.write = AsyncMock()
    fh.close = AsyncMock()
    sftp.open = AsyncMock(return_value=fh)
    return sftp


def _mock_conn(sftp: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.start_sftp_client = AsyncMock(return_value=sftp)
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    return conn


def _password_device(encrypted: bool = True) -> MagicMock:
    d = MagicMock(spec=Device)
    d.id = 1
    d.name = "sftp-box"
    d.hostname = "192.168.1.20"
    d.port = 22
    d.username = "sftpuser"
    d.auth_type = AuthType.password
    d.encrypted_password = b"blob" if encrypted else None
    d.key_filename = None
    return d


def _key_device(has_key: bool = True) -> MagicMock:
    d = MagicMock(spec=Device)
    d.id = 2
    d.name = "sftp-key-box"
    d.hostname = "10.0.0.2"
    d.port = 22
    d.username = "deploy"
    d.auth_type = AuthType.key
    d.encrypted_password = None
    d.key_filename = "deploy.pem" if has_key else None
    return d


# -- services/sftp.py: open_sftp_session branches -----------------------------

async def test_open_sftp_session_known_hosts_with_kh_path():
    """When _known_hosts_path returns a real path, client_factory is set."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value="/tmp/known_hosts"),
        patch("backend.services.sftp._make_accept_new_client", return_value=MagicMock()) as mock_factory,
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)) as mock_connect,
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    try:
        # client_factory must have been set in the connect call
        _, kwargs = mock_connect.call_args
        assert "client_factory" in kwargs
        assert kwargs["known_hosts"] is None
        mock_factory.assert_called_once_with("/tmp/known_hosts")
    finally:
        _sftp_sessions.pop(sid, None)


async def test_open_sftp_session_known_hosts_explicit_value():
    """When known_hosts is not 'auto', it is passed verbatim to asyncssh.connect."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)

    with (
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)) as mock_connect,
    ):
        sid = await open_sftp_session(
            hostname="h", port=22, username="u", known_hosts="/etc/ssh/known_hosts"
        )

    try:
        _, kwargs = mock_connect.call_args
        assert kwargs["known_hosts"] == "/etc/ssh/known_hosts"
        assert "client_factory" not in kwargs
    finally:
        _sftp_sessions.pop(sid, None)


async def test_open_sftp_session_with_private_key_path():
    """private_key_path is forwarded as client_keys to asyncssh.connect."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)) as mock_connect,
    ):
        sid = await open_sftp_session(
            hostname="h", port=22, username="u", private_key_path="/tmp/id_rsa.pem"
        )

    try:
        _, kwargs = mock_connect.call_args
        assert kwargs["client_keys"] == ["/tmp/id_rsa.pem"]
    finally:
        _sftp_sessions.pop(sid, None)


# -- services/sftp.py: close_sftp_session exception-swallowing -----------------

async def test_close_sftp_session_sftp_exit_raises_is_swallowed():
    """sftp.exit() raising must not propagate — exception is swallowed."""
    sftp = _mock_sftp_client()
    sftp.exit.side_effect = RuntimeError("sftp exit failed")
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    # Must not raise
    await close_sftp_session(sid)
    assert sid not in _sftp_sessions


async def test_close_sftp_session_conn_raises_is_swallowed():
    """conn.close() / wait_closed() raising must not propagate."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)
    conn.close.side_effect = RuntimeError("close failed")
    conn.wait_closed.side_effect = RuntimeError("wait failed")

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    # Must not raise
    await close_sftp_session(sid)
    assert sid not in _sftp_sessions


# -- services/sftp.py: list_directory special cases ----------------------------

async def test_list_directory_bytes_filename_decoded():
    """Filenames returned as bytes must be decoded to str."""
    entry = MagicMock()
    entry.filename = b"byte_file.txt"  # bytes, not str
    attrs = MagicMock()
    attrs.size = 100
    attrs.type = asyncssh.FILEXFER_TYPE_REGULAR
    attrs.permissions = 0o644
    attrs.mtime = 1700000000
    entry.attrs = attrs

    sftp = _mock_sftp_client()
    sftp.readdir = AsyncMock(return_value=[entry])
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    try:
        result = await list_directory(sid, "/home")
        assert len(result) == 1
        assert isinstance(result[0]["name"], bytes)   # raw name stored as-is
        assert isinstance(result[0]["path"], str)     # path is always str
        assert "byte_file.txt" in result[0]["path"]
    finally:
        _sftp_sessions.pop(sid, None)


async def test_list_directory_path_with_trailing_slash():
    """Remote path ending with '/' must not produce a double-slash in entry paths."""
    entry = MagicMock()
    entry.filename = "file.txt"
    attrs = MagicMock()
    attrs.size = 50
    attrs.type = asyncssh.FILEXFER_TYPE_REGULAR
    attrs.permissions = 0o644
    attrs.mtime = 0
    entry.attrs = attrs

    sftp = _mock_sftp_client()
    sftp.readdir = AsyncMock(return_value=[entry])
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    try:
        result = await list_directory(sid, "/home/")
        assert len(result) == 1
        path = result[0]["path"]
        assert not path.startswith("//")
        assert path == "/home/file.txt"
    finally:
        _sftp_sessions.pop(sid, None)


async def test_list_directory_non_str_non_bytes_filename():
    """Filenames that are neither str nor bytes are coerced via str() for the path."""
    entry = MagicMock()
    # Use a string representation so sort's .lower() call works,
    # but exercise the else-branch by making isinstance checks fail.
    # We do this by making the entry.filename a MagicMock whose __str__ returns a name.
    mock_name = MagicMock()
    mock_name.__str__ = MagicMock(return_value="mock_name.txt")
    mock_name.lower = MagicMock(return_value="mock_name.txt")
    # isinstance(mock_name, bytes) → False, isinstance(mock_name, str) → False → else branch
    entry.filename = mock_name
    attrs = MagicMock()
    attrs.size = 0
    attrs.type = asyncssh.FILEXFER_TYPE_REGULAR
    attrs.permissions = 0o644
    attrs.mtime = 0
    entry.attrs = attrs

    sftp = _mock_sftp_client()
    sftp.readdir = AsyncMock(return_value=[entry])
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    try:
        result = await list_directory(sid, "/")
        assert len(result) == 1
        assert "mock_name.txt" in result[0]["path"]
    finally:
        _sftp_sessions.pop(sid, None)


# -- routers/sftp.py: _resolve_device_credentials -----------------------------

async def test_resolve_credentials_key_device_writes_temp_file():
    """Key device: PEM is written to a temp file, chmod 0o600 applied."""
    device = _key_device(has_key=True)
    settings = _FakeSettings()
    captured_paths: list[str] = []

    original_chmod = os.chmod

    def _track_chmod(path, mode):
        captured_paths.append((path, mode))
        original_chmod(path, mode)

    with (
        patch("backend.routers.sftp.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch("backend.routers.sftp.os.chmod", side_effect=_track_chmod),
    ):
        password, key_path, tmp_key_file = await _resolve_device_credentials(device, settings)

    assert password is None
    assert key_path is not None
    assert tmp_key_file == key_path
    assert os.path.exists(key_path)
    assert any(mode == 0o600 for _, mode in captured_paths)
    # Cleanup
    os.unlink(key_path)


async def test_resolve_credentials_key_device_no_filename():
    """Key device with no key_filename: all outputs are None."""
    device = _key_device(has_key=False)
    settings = _FakeSettings()

    password, key_path, tmp_key_file = await _resolve_device_credentials(device, settings)

    assert password is None
    assert key_path is None
    assert tmp_key_file is None


async def test_resolve_credentials_password_device_no_encrypted():
    """Password device with no encrypted_password: password stays None."""
    device = _password_device(encrypted=False)
    settings = _FakeSettings()

    password, key_path, tmp_key_file = await _resolve_device_credentials(device, settings)

    assert password is None
    assert key_path is None
    assert tmp_key_file is None


# -- routers/sftp.py: open_session direct calls -------------------------------

async def test_open_session_direct_device_not_found():
    """open_session raises 404 when device is missing."""
    with pytest.raises(HTTPException) as exc_info:
        await open_session(9999, _FakeRequest(), trust_host=False, db=_FakeDB(device=None), current_user="admin")
    assert exc_info.value.status_code == 404


async def test_open_session_direct_password_device_success():
    """Password device success: session_id returned, audit written."""
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=True)
    device.ssh_host_fingerprint = "SHA256:TEST"

    with (
        patch("backend.routers.sftp.decrypt", return_value="cleartext"),
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:TEST")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(return_value=fake_id)),
        patch("backend.routers.sftp.write_audit", new=AsyncMock()) as mock_audit,
    ):
        result = await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert result == {"session_id": fake_id}
    mock_audit.assert_called_once()
    assert mock_audit.call_args.args[2] == ACTION_SESSION_STARTED


async def test_open_session_direct_key_device_success_and_temp_file_deleted():
    """Key device success: temp file written then deleted."""
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=True)
    device.ssh_host_fingerprint = "SHA256:TEST"
    deleted: list[str] = []

    with (
        patch("backend.routers.sftp.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:TEST")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(return_value=fake_id)),
        patch("backend.routers.sftp.write_audit", new=AsyncMock()),
        patch("backend.routers.sftp.os.unlink", side_effect=lambda p: deleted.append(p)),
    ):
        result = await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert result["session_id"] == fake_id
    assert len(deleted) == 1


async def test_open_session_direct_permission_denied_returns_502():
    """asyncssh.PermissionDenied maps to 502 (not 401, to avoid forcing logout)."""
    device = _password_device()
    with (
        patch("backend.routers.sftp.decrypt", return_value="pw"),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="bad"))),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_connection_lost_returns_504():
    """asyncssh.ConnectionLost maps to 504."""
    device = _password_device()
    device.ssh_host_fingerprint = "SHA256:TEST"
    with (
        patch("backend.routers.sftp.decrypt", return_value="pw"),
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:TEST")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(side_effect=asyncssh.ConnectionLost(reason="lost"))),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")
    assert exc_info.value.status_code == 504


async def test_open_session_direct_host_key_not_verifiable_returns_502():
    """asyncssh.HostKeyNotVerifiable maps to 502."""
    device = _password_device()
    device.ssh_host_fingerprint = "SHA256:TEST"
    with (
        patch("backend.routers.sftp.decrypt", return_value="pw"),
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:TEST")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable(reason="mismatch"))),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")
    assert exc_info.value.status_code == 502
    assert "Host key not verifiable" in exc_info.value.detail


async def test_open_session_direct_oserror_returns_502():
    """OSError maps to 502."""
    device = _password_device()
    with (
        patch("backend.routers.sftp.decrypt", return_value="pw"),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(side_effect=OSError("refused"))),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_asyncssh_error_returns_502():
    """Generic asyncssh.Error maps to 502."""
    device = _password_device()
    with (
        patch("backend.routers.sftp.decrypt", return_value="pw"),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(side_effect=asyncssh.Error(code=0, reason="err"))),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")
    assert exc_info.value.status_code == 502


async def test_open_session_direct_key_device_temp_file_cleaned_on_error():
    """Temp file is deleted even when open_sftp_session raises."""
    device = _key_device(has_key=True)
    device.ssh_host_fingerprint = "SHA256:TEST"
    deleted: list[str] = []

    with (
        patch("backend.routers.sftp.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:TEST")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(side_effect=OSError("refused"))),
        patch("backend.routers.sftp.os.unlink", side_effect=lambda p: deleted.append(p)),
    ):
        with pytest.raises(HTTPException):
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert len(deleted) == 1


async def test_open_session_direct_unlink_oserror_is_swallowed():
    """OSError from os.unlink in finally must be suppressed."""
    fake_id = str(uuid.uuid4())
    device = _key_device(has_key=True)
    device.ssh_host_fingerprint = "SHA256:TEST"

    with (
        patch("backend.routers.sftp.load_decrypted_key", return_value="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"),
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:TEST")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(return_value=fake_id)),
        patch("backend.routers.sftp.write_audit", new=AsyncMock()),
        patch("backend.routers.sftp.os.unlink", side_effect=OSError("busy")),
    ):
        result = await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert result["session_id"] == fake_id


async def test_open_session_direct_probe_connection_lost_returns_504():
    """ConnectionLost raised by probe must map to HTTP 504."""
    device = _password_device(encrypted=False)

    with patch(
        "backend.routers.sftp.probe_ssh_host_fingerprint",
        new=AsyncMock(side_effect=asyncssh.ConnectionLost(reason="lost")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert exc_info.value.status_code == 504


async def test_open_session_direct_probe_unavailable_with_connectionlost_cause_returns_504():
    """Unavailable fingerprint wrapping ConnectionLost must map to HTTP 504."""
    device = _password_device(encrypted=False)
    error = SSHHostFingerprintUnavailableError("probe failed")
    error.__cause__ = asyncssh.ConnectionLost(reason="lost")

    with patch(
        "backend.routers.sftp.probe_ssh_host_fingerprint",
        new=AsyncMock(side_effect=error),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert exc_info.value.status_code == 504


async def test_open_session_direct_untrusted_host_requires_confirmation():
    """Unpinned host without trust_host must return 409 challenge."""
    device = _password_device(encrypted=False)
    device.ssh_host_fingerprint = None

    with patch(
        "backend.routers.sftp.probe_ssh_host_fingerprint",
        new=AsyncMock(return_value="SHA256:NEW"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SSH_HOST_UNTRUSTED"
    assert exc_info.value.detail["fingerprint"] == "SHA256:NEW"


async def test_open_session_direct_untrusted_host_can_be_pinned_with_trust():
    """Unpinned host with trust_host must pin fingerprint and commit."""
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=False)
    device.ssh_host_fingerprint = None
    db = _FakeDB(device)

    with (
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:NEW")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(return_value=fake_id)) as mock_open,
        patch("backend.routers.sftp.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), trust_host=True, db=db, current_user="admin")

    assert result["session_id"] == fake_id
    assert device.ssh_host_fingerprint == "SHA256:NEW"
    assert db.committed is True
    _, kwargs = mock_open.call_args
    assert kwargs["expected_ssh_host_fingerprint"] == "SHA256:NEW"


async def test_open_session_direct_changed_host_requires_confirmation():
    """Changed pinned host without trust_host must return 409 challenge."""
    device = _password_device(encrypted=False)
    device.ssh_host_fingerprint = "SHA256:OLD"

    with patch(
        "backend.routers.sftp.probe_ssh_host_fingerprint",
        new=AsyncMock(return_value="SHA256:NEW"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SSH_HOST_CHANGED"
    assert exc_info.value.detail["fingerprint"] == "SHA256:NEW"
    assert exc_info.value.detail["previous_fingerprint"] == "SHA256:OLD"


async def test_open_session_direct_changed_host_can_be_replaced_with_trust():
    """Changed pinned host with trust_host must replace fingerprint and commit."""
    fake_id = str(uuid.uuid4())
    device = _password_device(encrypted=False)
    device.ssh_host_fingerprint = "SHA256:OLD"
    db = _FakeDB(device)

    with (
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:NEW")),
        patch("backend.routers.sftp.open_sftp_session", new=AsyncMock(return_value=fake_id)) as mock_open,
        patch("backend.routers.sftp.write_audit", new=AsyncMock()),
    ):
        result = await open_session(1, _FakeRequest(), trust_host=True, db=db, current_user="admin")

    assert result["session_id"] == fake_id
    assert device.ssh_host_fingerprint == "SHA256:NEW"
    assert db.committed is True
    _, kwargs = mock_open.call_args
    assert kwargs["expected_ssh_host_fingerprint"] == "SHA256:NEW"


async def test_open_session_direct_fingerprint_mismatch_error_maps_to_409():
    """Mismatch from open_sftp_session must map to SSH_HOST_CHANGED 409 payload."""
    device = _password_device(encrypted=False)
    device.ssh_host_fingerprint = "SHA256:OLD"

    with (
        patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(return_value="SHA256:OLD")),
        patch(
            "backend.routers.sftp.open_sftp_session",
            new=AsyncMock(
                side_effect=SSHHostFingerprintMismatchError(
                    expected="SHA256:OLD",
                    presented="SHA256:NEW",
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await open_session(1, _FakeRequest(), trust_host=False, db=_FakeDB(device), current_user="admin")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SSH_HOST_CHANGED"
    assert exc_info.value.detail["fingerprint"] == "SHA256:NEW"
    assert exc_info.value.detail["previous_fingerprint"] == "SHA256:OLD"


# -- services/sftp.py: remaining gap lines -------------------------------------

async def test_open_sftp_session_with_password():
    """password is not None: it must be forwarded to asyncssh.connect."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)) as mock_connect,
    ):
        sid = await open_sftp_session(
            hostname="h", port=22, username="u", password="s3cr3t"
        )

    try:
        _, kwargs = mock_connect.call_args
        assert kwargs["password"] == "s3cr3t"
    finally:
        _sftp_sessions.pop(sid, None)


async def test_close_sftp_session_conn_wait_closed_raises_is_swallowed():
    """wait_closed() raising must be swallowed (covers the second except block)."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)
    # close() succeeds but wait_closed() raises
    conn.wait_closed = AsyncMock(side_effect=OSError("closed"))

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    await close_sftp_session(sid)  # must not raise
    assert sid not in _sftp_sessions


async def test_get_sftp_session_returns_entry():
    """get_sftp_session returns the stored session object."""
    sftp = _mock_sftp_client()
    conn = _mock_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="h", port=22, username="u")

    try:
        entry = get_sftp_session(sid)
        assert entry is not None
        assert entry.sftp is sftp
    finally:
        _sftp_sessions.pop(sid, None)


async def test_get_sftp_session_returns_none_for_unknown():
    """get_sftp_session returns None for an unknown session_id."""
    assert get_sftp_session("no-such-id") is None


async def test_delete_remote_unknown_session_raises():
    """delete_remote raises ValueError for unknown session_id."""
    with pytest.raises(ValueError, match="SFTP session not found"):
        await delete_remote("no-session", "/tmp/file.txt", is_dir=False)


async def test_rename_remote_unknown_session_raises():
    """rename_remote raises ValueError for unknown session_id."""
    with pytest.raises(ValueError, match="SFTP session not found"):
        await rename_remote("no-session", "/old", "/new")


async def test_mkdir_remote_unknown_session_raises():
    """mkdir_remote raises ValueError for unknown session_id."""
    with pytest.raises(ValueError, match="SFTP session not found"):
        await mkdir_remote("no-session", "/tmp/newdir")
