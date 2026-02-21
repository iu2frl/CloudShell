"""
tests/test_sftp_service.py — unit tests for backend/services/sftp.py.

Tests cover:
- open_sftp_session: success path (mocked asyncssh)
- open_sftp_session: connection errors propagate
- close_sftp_session: closes connection and SFTP client
- list_directory: returns sorted entries
- list_directory: unknown session raises ValueError
- read_file_bytes: reads data via SFTP
- write_file_bytes: writes data via SFTP
- delete_remote: calls remove or rmdir based on is_dir
- rename_remote: calls SFTP rename
- mkdir_remote: calls SFTP mkdir
- get_sftp_session_meta: returns stored metadata
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from backend.services.sftp import (
    _sftp_sessions,
    close_sftp_session,
    delete_remote,
    get_sftp_session_meta,
    list_directory,
    mkdir_remote,
    open_sftp_session,
    read_file_bytes,
    rename_remote,
    write_file_bytes,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_fake_sftp_entry(name: str, is_dir: bool = False, size: int = 1024) -> MagicMock:
    """Build a mock asyncssh SFTPName object."""
    entry = MagicMock()
    entry.filename = name
    attrs = MagicMock()
    attrs.size = size
    attrs.type = (
        asyncssh.FILEXFER_TYPE_DIRECTORY if is_dir else asyncssh.FILEXFER_TYPE_REGULAR
    )
    attrs.permissions = 0o755
    attrs.mtime = 1700000000
    entry.attrs = attrs
    return entry


def _make_fake_sftp_client(entries: list) -> MagicMock:
    """Return a mock SFTPClient."""
    sftp = MagicMock()
    sftp.readdir = AsyncMock(return_value=entries)
    sftp.exit = MagicMock()

    # File handle returned by open()
    fake_fh = MagicMock()
    fake_fh.read = AsyncMock(return_value=b"file-content")
    fake_fh.write = AsyncMock()
    fake_fh.close = AsyncMock()

    # open() is a coroutine that returns the file handle
    sftp.open = AsyncMock(return_value=fake_fh)

    sftp.remove = AsyncMock()
    sftp.rmdir = AsyncMock()
    sftp.rename = AsyncMock()
    sftp.mkdir = AsyncMock()
    return sftp


def _make_fake_conn(sftp_client: MagicMock) -> MagicMock:
    """Return a mock SSHClientConnection."""
    conn = MagicMock()
    conn.start_sftp_client = AsyncMock(return_value=sftp_client)
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    return conn


# ── open_sftp_session ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_sftp_session_success():
    """open_sftp_session returns a session_id and stores the session."""
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(
            hostname="host",
            port=22,
            username="user",
            device_label="host-label",
            cloudshell_user="admin",
            source_ip="1.2.3.4",
        )

    assert sid in _sftp_sessions
    meta = _sftp_sessions[sid]
    assert meta.device_label == "host-label"
    assert meta.cloudshell_user == "admin"
    assert meta.source_ip == "1.2.3.4"
    # Cleanup
    _sftp_sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_open_sftp_session_propagates_connection_error():
    """SSH connection errors propagate to the caller."""
    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch(
            "asyncssh.connect",
            new=AsyncMock(side_effect=asyncssh.PermissionDenied(reason="bad auth")),
        ),
    ):
        with pytest.raises(asyncssh.PermissionDenied):
            await open_sftp_session(hostname="host", port=22, username="user")


# ── close_sftp_session ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_sftp_session_removes_entry():
    """close_sftp_session removes the session and closes the connection."""
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    await close_sftp_session(sid)

    assert sid not in _sftp_sessions
    sftp.exit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_sftp_session_noop_for_unknown():
    """Closing an unknown session_id should not raise."""
    await close_sftp_session("nonexistent-session-id")


# ── get_sftp_session_meta ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_sftp_session_meta_unknown():
    """Returns empty strings and None for unknown session."""
    label, user, ip = get_sftp_session_meta("no-such-session")
    assert label == ""
    assert user == ""
    assert ip is None


# ── list_directory ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_directory_unknown_session():
    """list_directory raises ValueError for unknown session_id."""
    with pytest.raises(ValueError, match="SFTP session not found"):
        await list_directory("no-session", "/")


@pytest.mark.asyncio
async def test_list_directory_returns_sorted_entries():
    """Directories come before files, entries sorted alphabetically."""
    entries_raw = [
        _make_fake_sftp_entry(".", is_dir=True),
        _make_fake_sftp_entry("..", is_dir=True),
        _make_fake_sftp_entry("zoo.txt", is_dir=False),
        _make_fake_sftp_entry("alpha", is_dir=True),
        _make_fake_sftp_entry("beta.txt", is_dir=False),
    ]
    sftp = _make_fake_sftp_client(entries_raw)
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        result = await list_directory(sid, "/home")
        names = [e["name"] for e in result]
        # "alpha" (dir) before "beta.txt" and "zoo.txt" (files)
        assert names.index("alpha") < names.index("beta.txt")
        assert names.index("alpha") < names.index("zoo.txt")
        # . and .. are filtered out
        assert "." not in names
        assert ".." not in names
    finally:
        _sftp_sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_list_directory_entry_structure():
    """Each entry has the expected keys with correct types."""
    entries_raw = [_make_fake_sftp_entry("readme.txt", size=512)]
    sftp = _make_fake_sftp_client(entries_raw)
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        result = await list_directory(sid, "/")
        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "readme.txt"
        assert entry["size"] == 512
        assert entry["is_dir"] is False
        assert "path" in entry
        assert "permissions" in entry
        assert "modified" in entry
    finally:
        _sftp_sessions.pop(sid, None)


# ── read_file_bytes ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_file_bytes_unknown_session():
    with pytest.raises(ValueError, match="SFTP session not found"):
        await read_file_bytes("no-session", "/etc/passwd")


@pytest.mark.asyncio
async def test_read_file_bytes_returns_content():
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        data = await read_file_bytes(sid, "/etc/passwd")
        assert data == b"file-content"
        sftp.open.assert_called_once_with("/etc/passwd", "rb")
    finally:
        _sftp_sessions.pop(sid, None)


# ── write_file_bytes ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_file_bytes_unknown_session():
    with pytest.raises(ValueError, match="SFTP session not found"):
        await write_file_bytes("no-session", "/tmp/x", b"data")


@pytest.mark.asyncio
async def test_write_file_bytes_calls_open_write():
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        await write_file_bytes(sid, "/tmp/file.txt", b"hello")
        sftp.open.assert_called_once_with("/tmp/file.txt", "wb")
    finally:
        _sftp_sessions.pop(sid, None)


# ── delete_remote ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_remote_file():
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        await delete_remote(sid, "/tmp/file.txt", is_dir=False)
        sftp.remove.assert_called_once_with("/tmp/file.txt")
        sftp.rmdir.assert_not_called()
    finally:
        _sftp_sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_delete_remote_directory():
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        await delete_remote(sid, "/tmp/mydir", is_dir=True)
        sftp.rmdir.assert_called_once_with("/tmp/mydir")
        sftp.remove.assert_not_called()
    finally:
        _sftp_sessions.pop(sid, None)


# ── rename_remote ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rename_remote():
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        await rename_remote(sid, "/old", "/new")
        sftp.rename.assert_called_once_with("/old", "/new")
    finally:
        _sftp_sessions.pop(sid, None)


# ── mkdir_remote ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mkdir_remote():
    sftp = _make_fake_sftp_client([])
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        sid = await open_sftp_session(hostname="host", port=22, username="user")

    try:
        await mkdir_remote(sid, "/tmp/newdir")
        sftp.mkdir.assert_called_once_with("/tmp/newdir")
    finally:
        _sftp_sessions.pop(sid, None)
