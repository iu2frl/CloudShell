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
    SSHHostFingerprintUnavailableError,
    close_session,
    get_session_meta,
    probe_ssh_host_fingerprint,
)


# -- Helpers -------------------------------------------------------------------

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


# -- create_session ------------------------------------------------------------

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


# -- close_session -------------------------------------------------------------

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


# -- get_session_meta ----------------------------------------------------------

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


# -- _ws_error -----------------------------------------------------------------

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


# -- probe_ssh_host_fingerprint ------------------------------------------------

class _FakeKey:
    """Tiny key stub returning deterministic public-key bytes."""

    def export_public_key(self) -> bytes:
        return b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey"


class _FakeConnWithServerKey:
    """Connection stub exposing a server host key and close methods."""

    def __init__(self, key: object):
        self._key = key
        self.close = MagicMock()
        self.wait_closed = AsyncMock()

    def get_server_host_key(self) -> object:
        return self._key


async def test_probe_fingerprint_returns_presented_value_on_permission_denied():
    """Probe should still succeed when auth fails after host-key presentation."""

    async def _fake_connect(**kwargs):
        client = kwargs["client_factory"]()
        client.validate_host_public_key("host", "1.2.3.4", 22, _FakeKey())
        raise asyncssh.PermissionDenied(reason="Bad credentials")

    with patch("asyncssh.connect", new=AsyncMock(side_effect=_fake_connect)):
        fingerprint = await probe_ssh_host_fingerprint(
            hostname="127.0.0.1",
            port=22,
            username="alice",
            password="secret",
        )

    assert isinstance(fingerprint, str)
    assert len(fingerprint) > 0


async def test_probe_fingerprint_raises_if_auth_denied_before_host_key_capture():
    """Probe must raise unavailable when no host key was presented."""
    with patch(
        "asyncssh.connect",
        new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="Bad credentials")),
    ):
        with pytest.raises(SSHHostFingerprintUnavailableError):
            await probe_ssh_host_fingerprint(
                hostname="127.0.0.1",
                port=22,
                username="alice",
                password="secret",
            )


async def test_probe_fingerprint_reads_server_key_from_connection_when_callback_not_used():
    """Probe should read host fingerprint directly from the connected session object."""
    conn = _FakeConnWithServerKey(_FakeKey())
    with patch("asyncssh.connect", new=AsyncMock(return_value=conn)):
        fingerprint = await probe_ssh_host_fingerprint(
            hostname="127.0.0.1",
            port=22,
            username="alice",
            password="secret",
        )

    assert isinstance(fingerprint, str)
    assert len(fingerprint) > 0


async def test_create_session_expected_fingerprint_mismatch_raises():
    """create_session must reject connection when presented fingerprint differs."""
    conn = _FakeConnWithServerKey(_FakeKey())
    with patch("asyncssh.connect", new=AsyncMock(return_value=conn)):
        with pytest.raises(ssh_module.SSHHostFingerprintMismatchError):
            await ssh_module.create_session(
                hostname="127.0.0.1",
                port=22,
                username="user",
                password="pass",
                known_hosts=None,
                expected_ssh_host_fingerprint="00:11:22",
            )
    conn.close.assert_called_once()


def test_pinned_fingerprint_client_accepts_matching_key_and_captures_presented():
    """Pinned client validator must accept matching key and capture presented fingerprint."""
    captured: dict[str, str] = {}
    expected = ssh_module._format_ssh_host_fingerprint(_FakeKey())
    client_class = ssh_module._make_pinned_fingerprint_client(expected, captured)
    client = client_class()

    accepted = client.validate_host_public_key("host", "1.2.3.4", 22, _FakeKey())

    assert accepted is True
    assert captured["presented"] == expected


def test_pinned_fingerprint_client_rejects_mismatch():
    """Pinned client validator must reject mismatched host key fingerprints."""

    class _OtherFakeKey:
        def export_public_key(self) -> bytes:
            return b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAnotherKey"

    captured: dict[str, str] = {}
    expected = ssh_module._format_ssh_host_fingerprint(_FakeKey())
    client_class = ssh_module._make_pinned_fingerprint_client(expected, captured)
    client = client_class()

    accepted = client.validate_host_public_key("host", "1.2.3.4", 22, _OtherFakeKey())

    assert accepted is False
    assert captured["presented"] != expected


async def test_probe_fingerprint_connection_made_captures_server_key():
    """Probe must capture fingerprint via connection_made when server key is available there."""

    async def _fake_connect(**kwargs):
        client = kwargs["client_factory"]()
        conn = _FakeConnWithServerKey(_FakeKey())
        client.connection_made(conn)
        raise asyncssh.PermissionDenied(reason="Bad credentials")

    with patch("asyncssh.connect", new=AsyncMock(side_effect=_fake_connect)):
        fingerprint = await probe_ssh_host_fingerprint(
            hostname="127.0.0.1",
            port=22,
            username="alice",
            password="secret",
        )

    assert isinstance(fingerprint, str)
    assert len(fingerprint) > 0


async def test_probe_fingerprint_connection_made_handles_get_key_exception():
    """Probe must handle exceptions from connection.get_server_host_key in connection_made."""

    class _ConnRaisesKey:
        def get_server_host_key(self):
            raise RuntimeError("no key")

    async def _fake_connect(**kwargs):
        client = kwargs["client_factory"]()
        client.connection_made(_ConnRaisesKey())
        raise asyncssh.PermissionDenied(reason="Bad credentials")

    with patch("asyncssh.connect", new=AsyncMock(side_effect=_fake_connect)):
        with pytest.raises(SSHHostFingerprintUnavailableError):
            await probe_ssh_host_fingerprint(
                hostname="127.0.0.1",
                port=22,
                username="alice",
                password="secret",
            )


async def test_probe_fingerprint_sets_client_keys_when_private_key_path_provided():
    """Probe must forward private_key_path as client_keys in connect kwargs."""
    conn = _FakeConnWithServerKey(_FakeKey())
    captured_kwargs: dict = {}

    async def _fake_connect(**kwargs):
        captured_kwargs.update(kwargs)
        return conn

    with patch("asyncssh.connect", new=AsyncMock(side_effect=_fake_connect)):
        await probe_ssh_host_fingerprint(
            hostname="127.0.0.1",
            port=22,
            username="alice",
            private_key_path="/tmp/id_ed25519",
        )

    assert captured_kwargs["client_keys"] == ["/tmp/id_ed25519"]


async def test_probe_fingerprint_raises_if_connection_key_lookup_throws():
    """Probe must raise unavailable when post-connect key lookup raises and no fingerprint captured."""

    class _ConnNoKey:
        def close(self):
            return None

        async def wait_closed(self):
            return None

        def get_server_host_key(self):
            raise RuntimeError("no server key")

    with patch("asyncssh.connect", new=AsyncMock(return_value=_ConnNoKey())):
        with pytest.raises(SSHHostFingerprintUnavailableError):
            await probe_ssh_host_fingerprint(
                hostname="127.0.0.1",
                port=22,
                username="alice",
                password="secret",
            )


async def test_create_session_reraises_host_key_not_verifiable():
    """create_session must re-raise HostKeyNotVerifiable from asyncssh.connect."""
    with patch(
        "asyncssh.connect",
        new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable(reason="mismatch")),
    ):
        with pytest.raises(asyncssh.HostKeyNotVerifiable):
            await ssh_module.create_session(
                hostname="127.0.0.1",
                port=22,
                username="user",
                password="pass",
                known_hosts=None,
            )


async def test_probe_fingerprint_host_key_not_verifiable_without_capture_raises_unavailable():
    """HostKeyNotVerifiable in probe path must end as unavailable when no fingerprint is captured."""
    with patch(
        "asyncssh.connect",
        new=AsyncMock(side_effect=asyncssh.HostKeyNotVerifiable(reason="mismatch")),
    ):
        with pytest.raises(SSHHostFingerprintUnavailableError):
            await probe_ssh_host_fingerprint(
                hostname="127.0.0.1",
                port=22,
                username="alice",
                password="secret",
            )


async def test_probe_fingerprint_oserror_without_capture_raises_unavailable():
    """OSError in probe path must map to SSHHostFingerprintUnavailableError when nothing was captured."""
    with patch("asyncssh.connect", new=AsyncMock(side_effect=OSError("network down"))):
        with pytest.raises(SSHHostFingerprintUnavailableError):
            await probe_ssh_host_fingerprint(
                hostname="127.0.0.1",
                port=22,
                username="alice",
                password="secret",
            )
