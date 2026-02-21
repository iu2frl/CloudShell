"""
tests/test_ssh_known_hosts.py — unit tests for the known_hosts / accept-new
policy in services/ssh.py.

Covers:
- _known_hosts_path returns None when DATA_DIR is unset (line 52-53)
- _known_hosts_path creates the file and returns its path when DATA_DIR is set (lines 54-57)
- _known_hosts_path returns the path for an already-existing file (no double-create)
- _make_accept_new_client: new host key is accepted and persisted (lines 93-102)
- _make_accept_new_client: known host with matching key is accepted (lines 79-87)
- _make_accept_new_client: known host with mismatching key is rejected (lines 88-92)
- _make_accept_new_client: read_known_hosts exception falls back to empty trusted list
- create_session with known_hosts="auto" and a DATA_DIR uses the accept-new client (lines 137-145)
- create_session with known_hosts="auto" and no DATA_DIR disables host-key checking (line 152)
- stream_session: session not found sends error and closes with 4004 (lines 171-174)
"""
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from backend.services import ssh as ssh_module
from backend.services.ssh import _known_hosts_path, _make_accept_new_client


# ── _known_hosts_path ─────────────────────────────────────────────────────────

def test_known_hosts_path_no_data_dir(monkeypatch):
    """_known_hosts_path must return None when DATA_DIR is not set."""
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert _known_hosts_path() is None


def test_known_hosts_path_creates_file(monkeypatch, tmp_path):
    """_known_hosts_path must create an empty known_hosts file and return its path."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    path = _known_hosts_path()
    assert path is not None
    assert os.path.isfile(path)
    assert path == os.path.join(str(tmp_path), "known_hosts")


def test_known_hosts_path_existing_file_not_truncated(monkeypatch, tmp_path):
    """_known_hosts_path must not truncate an existing known_hosts file."""
    kh = tmp_path / "known_hosts"
    kh.write_text("existing content\n")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _known_hosts_path()
    assert kh.read_text() == "existing content\n"


# ── _make_accept_new_client ───────────────────────────────────────────────────

def _make_mock_key(export_value: str = "ssh-rsa AAAA... host") -> MagicMock:
    """Return a mock asyncssh.SSHKey whose export_public_key returns bytes."""
    key = MagicMock(spec=asyncssh.SSHKey)
    key.export_public_key.return_value = export_value.encode()
    return key


def test_accept_new_client_persists_new_host(tmp_path):
    """validate_host_public_key must write a new host entry and return True."""
    kh_path = str(tmp_path / "known_hosts")
    open(kh_path, "w").close()

    ClientClass = _make_accept_new_client(kh_path)
    client_instance = ClientClass()

    mock_key = _make_mock_key("ssh-rsa AAAA_new_key host1")

    with patch("asyncssh.read_known_hosts") as mock_read:
        # Simulate no existing entries for this host
        mock_hosts = MagicMock()
        mock_hosts.match.return_value = ([], [], [])
        mock_read.return_value = mock_hosts

        result = client_instance.validate_host_public_key(
            "newhost.example.com", "1.2.3.4", 22, mock_key
        )

    assert result is True
    content = open(kh_path).read()
    assert "newhost.example.com" in content


def test_accept_new_client_accepts_matching_known_host(tmp_path):
    """validate_host_public_key must return True when the key matches a known entry."""
    kh_path = str(tmp_path / "known_hosts")
    open(kh_path, "w").close()

    ClientClass = _make_accept_new_client(kh_path)
    client_instance = ClientClass()

    key_bytes = b"ssh-rsa AAAA_known_key host2"
    mock_key = _make_mock_key(key_bytes.decode())

    # Build a mock stored key that matches
    stored_key = MagicMock(spec=asyncssh.SSHKey)
    stored_key.export_public_key.return_value = key_bytes

    with patch("asyncssh.read_known_hosts") as mock_read:
        mock_hosts = MagicMock()
        mock_hosts.match.return_value = ([stored_key], [], [])
        mock_read.return_value = mock_hosts

        result = client_instance.validate_host_public_key(
            "knownhost.example.com", "5.6.7.8", 22, mock_key
        )

    assert result is True


def test_accept_new_client_rejects_mismatched_known_host(tmp_path):
    """validate_host_public_key must return False when the key does not match."""
    kh_path = str(tmp_path / "known_hosts")
    open(kh_path, "w").close()

    ClientClass = _make_accept_new_client(kh_path)
    client_instance = ClientClass()

    # The presented key differs from the stored one
    presented_key = _make_mock_key("ssh-rsa AAAA_different_key host3")

    stored_key = MagicMock(spec=asyncssh.SSHKey)
    stored_key.export_public_key.return_value = b"ssh-rsa AAAA_stored_key host3"

    with patch("asyncssh.read_known_hosts") as mock_read:
        mock_hosts = MagicMock()
        mock_hosts.match.return_value = ([stored_key], [], [])
        mock_read.return_value = mock_hosts

        result = client_instance.validate_host_public_key(
            "stricthost.example.com", "9.10.11.12", 22, presented_key
        )

    assert result is False


def test_accept_new_client_read_exception_falls_back_to_new_host(tmp_path):
    """If read_known_hosts raises, the host is treated as new and accepted."""
    kh_path = str(tmp_path / "known_hosts")
    open(kh_path, "w").close()

    ClientClass = _make_accept_new_client(kh_path)
    client_instance = ClientClass()
    mock_key = _make_mock_key("ssh-rsa AAAA_exc_key host4")

    with patch("asyncssh.read_known_hosts", side_effect=Exception("parse error")):
        result = client_instance.validate_host_public_key(
            "errorhost.example.com", "2.2.2.2", 22, mock_key
        )

    assert result is True


# ── create_session with known_hosts="auto" ────────────────────────────────────

async def test_create_session_auto_with_data_dir_uses_accept_new(monkeypatch, tmp_path):
    """With DATA_DIR set, known_hosts='auto' must pass a client_factory to asyncssh.connect."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()

    captured: dict = {}

    async def fake_connect(**kwargs):
        captured.update(kwargs)
        return mock_conn

    with patch("asyncssh.connect", side_effect=fake_connect):
        session_id = await ssh_module.create_session(
            hostname="127.0.0.1",
            port=22,
            username="user",
            known_hosts="auto",
        )

    try:
        assert "client_factory" in captured
        assert captured["known_hosts"] is None  # validation delegated to client
    finally:
        ssh_module._sessions.pop(session_id, None)


async def test_create_session_auto_without_data_dir_disables_host_checking(monkeypatch):
    """With no DATA_DIR, known_hosts='auto' must set known_hosts=None (trust-all)."""
    monkeypatch.delenv("DATA_DIR", raising=False)

    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()

    captured: dict = {}

    async def fake_connect(**kwargs):
        captured.update(kwargs)
        return mock_conn

    with patch("asyncssh.connect", side_effect=fake_connect):
        session_id = await ssh_module.create_session(
            hostname="127.0.0.1",
            port=22,
            username="user",
            known_hosts="auto",
        )

    try:
        assert "client_factory" not in captured
        assert captured["known_hosts"] is None
    finally:
        ssh_module._sessions.pop(session_id, None)


async def test_create_session_explicit_known_hosts_path(tmp_path):
    """Passing a file path for known_hosts must forward it directly to asyncssh."""
    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.wait_closed = AsyncMock()

    kh_path = str(tmp_path / "known_hosts")
    open(kh_path, "w").close()

    captured: dict = {}

    async def fake_connect(**kwargs):
        captured.update(kwargs)
        return mock_conn

    with patch("asyncssh.connect", side_effect=fake_connect):
        session_id = await ssh_module.create_session(
            hostname="127.0.0.1",
            port=22,
            username="user",
            known_hosts=kh_path,
        )

    try:
        assert captured["known_hosts"] == kh_path
    finally:
        ssh_module._sessions.pop(session_id, None)


# ── stream_session — session not found ───────────────────────────────────────

async def test_stream_session_not_found_closes_4004():
    """stream_session must send an error frame and close with code 4004 for unknown IDs."""
    ws = MagicMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()

    await ssh_module.stream_session("00000000-0000-0000-0000-000000000000", ws)

    ws.close.assert_called_once_with(code=4004)
    ws.send_bytes.assert_called_once()
    error_frame: bytes = ws.send_bytes.call_args[0][0]
    assert b"Session not found" in error_frame
