"""
tests/test_ftp_service.py — unit tests for services/ftp.py.

Tests cover:
- open_ftp_session: session is stored, plain FTP path
- open_ftp_session: FTPS path (ssl context is created)
- close_ftp_session: session is removed, quit is called
- get_ftp_session / get_ftp_session_meta helpers
- list_directory: entries are returned, filtered and sorted
- _parse_ftp_mtime: valid and edge-case timestamps
- read_file_bytes: streams assembled correctly
- write_file_bytes: stream write is called with data
- delete_remote: file and directory paths
- rename_remote / mkdir_remote
- unknown session → ValueError for all operations
"""
from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.services.ftp as ftp_service
from backend.services.ftp import (
    _parse_ftp_mtime,
    close_ftp_session,
    delete_remote,
    get_ftp_session,
    get_ftp_session_meta,
    list_directory,
    mkdir_remote,
    open_ftp_session,
    read_file_bytes,
    rename_remote,
    write_file_bytes,
)


# -- Helpers -------------------------------------------------------------------


def _make_fake_client() -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock()
    client.login = AsyncMock()
    client.quit = AsyncMock()

    async def _fake_list(path, recursive=False):
        yield PurePosixPath("/subdir"), {"type": "dir", "size": "0", "modify": "20230601000000"}
        yield PurePosixPath("/file.txt"), {"type": "file", "size": "1024", "modify": "20230601120000"}

    client.list = _fake_list

    fake_dl = MagicMock()
    fake_dl.__aenter__ = AsyncMock(return_value=fake_dl)
    fake_dl.__aexit__ = AsyncMock(return_value=False)

    async def _iter():
        yield b"chunk1"
        yield b"chunk2"

    fake_dl.iter_by_block = _iter
    client.download_stream = MagicMock(return_value=fake_dl)

    fake_ul = MagicMock()
    fake_ul.__aenter__ = AsyncMock(return_value=fake_ul)
    fake_ul.__aexit__ = AsyncMock(return_value=False)
    fake_ul.write = AsyncMock()
    client.upload_stream = MagicMock(return_value=fake_ul)

    client.remove_file = AsyncMock()
    client.remove_directory = AsyncMock()
    client.rename = AsyncMock()
    client.make_directory = AsyncMock()
    client.upgrade_to_tls = AsyncMock()

    ssl_obj = MagicMock()
    ssl_obj.getpeercert.return_value = b"fake-cert-der"
    writer = MagicMock()
    writer.get_extra_info.return_value = ssl_obj
    stream = MagicMock()
    stream.writer = writer
    client.stream = stream

    return client


@pytest.fixture(autouse=True)
def _clean_sessions():
    """Ensure the session store is clean before and after each test."""
    ftp_service._ftp_sessions.clear()
    yield
    ftp_service._ftp_sessions.clear()


# -- open_ftp_session ----------------------------------------------------------


@pytest.mark.asyncio
async def test_open_ftp_session_plain():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session(
            hostname="ftp.example.com",
            port=21,
            username="user",
            password="pass",
            use_tls=False,
            device_label="My FTP",
            cloudshell_user="admin",
            source_ip="127.0.0.1",
        )
    assert sid in ftp_service._ftp_sessions
    fake.connect.assert_awaited_once_with("ftp.example.com", 21)
    fake.login.assert_awaited_once_with("user", "pass")


@pytest.mark.asyncio
async def test_open_ftp_session_ftps():
    """FTPS must connect plain, then call upgrade_to_tls (explicit TLS / AUTH TLS)."""
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session(
            hostname="ftp.example.com",
            port=21,
            username="user",
            password="pass",
            use_tls=True,
        )
    assert sid in ftp_service._ftp_sessions
    # Plain connect must be called first (no ssl= wrapping at socket level)
    fake.connect.assert_awaited_once_with("ftp.example.com", 21)
    # AUTH TLS upgrade must happen before login
    fake.upgrade_to_tls.assert_awaited_once()
    fake.login.assert_awaited_once_with("user", "pass")


@pytest.mark.asyncio
async def test_open_ftp_session_ftps_thumbprint_mismatch_raises():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        with pytest.raises(ftp_service.FTPSCertificateMismatchError):
            await open_ftp_session(
                hostname="ftp.example.com",
                port=21,
                username="user",
                password="pass",
                use_tls=True,
                expected_ftps_thumbprint="AA:BB:CC",
            )


@pytest.mark.asyncio
async def test_open_ftp_session_anonymous():
    """username=None should fall back to 'anonymous'."""
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session(
            hostname="ftp.example.com",
            port=21,
            username="",
            password=None,
        )
    assert sid in ftp_service._ftp_sessions
    fake.login.assert_awaited_once_with("anonymous", "")


# -- close_ftp_session ---------------------------------------------------------


@pytest.mark.asyncio
async def test_close_ftp_session_removes_entry():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")
    assert sid in ftp_service._ftp_sessions
    await close_ftp_session(sid)
    assert sid not in ftp_service._ftp_sessions
    fake.quit.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_ftp_session_unknown_is_noop():
    """Closing a non-existent session must not raise."""
    await close_ftp_session("non-existent-id")


@pytest.mark.asyncio
async def test_close_ftp_session_quit_exception_is_swallowed():
    """quit() raising must NOT propagate — the session must still be removed."""
    fake = _make_fake_client()
    fake.quit = AsyncMock(side_effect=OSError("server closed connection"))
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")
    assert sid in ftp_service._ftp_sessions
    await close_ftp_session(sid)          # must not raise
    assert sid not in ftp_service._ftp_sessions


# -- Session metadata helpers --------------------------------------------------


@pytest.mark.asyncio
async def test_get_ftp_session_meta():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session(
            "host", 21, "u", "p",
            device_label="dev", cloudshell_user="admin", source_ip="1.2.3.4",
        )
    label, user, ip = get_ftp_session_meta(sid)
    assert label == "dev"
    assert user == "admin"
    assert ip == "1.2.3.4"


def test_get_ftp_session_meta_unknown():
    label, user, ip = get_ftp_session_meta("bad-id")
    assert label == ""
    assert user == ""
    assert ip is None


def test_get_ftp_session_unknown():
    assert get_ftp_session("bad-id") is None


# -- list_directory ------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_directory_returns_sorted_entries():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")

    entries = await list_directory(sid, "/")
    # Directories should come first
    assert entries[0]["is_dir"] is True
    assert entries[0]["name"] == "subdir"
    assert entries[1]["is_dir"] is False
    assert entries[1]["name"] == "file.txt"
    assert entries[1]["size"] == 1024


@pytest.mark.asyncio
async def test_list_directory_unknown_session():
    with pytest.raises(ValueError, match="FTP session not found"):
        await list_directory("no-such-session", "/")


# -- _parse_ftp_mtime ----------------------------------------------------------


def test_parse_ftp_mtime_valid():
    ts = _parse_ftp_mtime("20240101120000")
    assert ts > 0


def test_parse_ftp_mtime_empty():
    assert _parse_ftp_mtime("") == 0


def test_parse_ftp_mtime_short():
    assert _parse_ftp_mtime("2024") == 0


def test_parse_ftp_mtime_invalid():
    assert _parse_ftp_mtime("XXXXXXXXXXXXXX") == 0


def test_parse_ftp_mtime_overflow():
    """Month 99 triggers a ValueError inside datetime() → returns 0."""
    assert _parse_ftp_mtime("20249901000000") == 0


# -- read_file_bytes -----------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_bytes_assembles_chunks():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")

    data = await read_file_bytes(sid, "/file.txt")
    assert data == b"chunk1chunk2"


@pytest.mark.asyncio
async def test_read_file_bytes_unknown_session():
    with pytest.raises(ValueError, match="FTP session not found"):
        await read_file_bytes("no-such-session", "/file.txt")


# -- write_file_bytes ----------------------------------------------------------


@pytest.mark.asyncio
async def test_write_file_bytes_calls_stream_write():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")

    await write_file_bytes(sid, "/upload.txt", b"payload")
    # The stream write() should have been called with our data
    upload_stream_ctx = fake.upload_stream.return_value
    upload_stream_ctx.write.assert_awaited_once_with(b"payload")


@pytest.mark.asyncio
async def test_write_file_bytes_unknown_session():
    with pytest.raises(ValueError, match="FTP session not found"):
        await write_file_bytes("no-such-session", "/x.txt", b"data")


# -- delete_remote -------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_file():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")
    await delete_remote(sid, "/test.txt", is_dir=False)
    fake.remove_file.assert_awaited_once_with("/test.txt")


@pytest.mark.asyncio
async def test_delete_directory():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")
    await delete_remote(sid, "/mydir", is_dir=True)
    fake.remove_directory.assert_awaited_once_with("/mydir")


@pytest.mark.asyncio
async def test_delete_unknown_session():
    with pytest.raises(ValueError, match="FTP session not found"):
        await delete_remote("no-such-session", "/x", is_dir=False)


# -- rename_remote -------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_remote():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")
    await rename_remote(sid, "/old.txt", "/new.txt")
    fake.rename.assert_awaited_once_with("/old.txt", "/new.txt")


@pytest.mark.asyncio
async def test_rename_unknown_session():
    with pytest.raises(ValueError, match="FTP session not found"):
        await rename_remote("no-such-session", "/a", "/b")


# -- mkdir_remote --------------------------------------------------------------


@pytest.mark.asyncio
async def test_mkdir_remote():
    fake = _make_fake_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake):
        sid = await open_ftp_session("host", 21, "u", "p")
    await mkdir_remote(sid, "/newdir")
    fake.make_directory.assert_awaited_once_with("/newdir")


@pytest.mark.asyncio
async def test_mkdir_unknown_session():
    with pytest.raises(ValueError, match="FTP session not found"):
        await mkdir_remote("no-such-session", "/newdir")
