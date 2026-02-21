"""
tests/test_sftp_error_paths.py — error-path coverage for the SFTP router.

Covers uncovered lines in backend/routers/sftp.py:
- GET  /{session_id}/list       → 500 on unexpected service exception
- GET  /{session_id}/download   → 500 on unexpected service exception
- POST /{session_id}/upload     → 404 when session is unknown; 500 on error
- POST /{session_id}/delete     → 404 when session is unknown; 500 on error
- POST /{session_id}/rename     → 404 when session is unknown; 500 on error
- POST /{session_id}/mkdir      → 404 when session is unknown; 500 on error
- POST /session/{id}            → 504 on ConnectionLost; 502 on HostKeyNotVerifiable
"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sftp_device_payload(**overrides) -> dict:
    return {
        "name": "sftp-server",
        "hostname": "192.168.1.20",
        "port": 22,
        "username": "sftpuser",
        "auth_type": "password",
        "connection_type": "sftp",
        "password": "s3cr3t",
        **overrides,
    }


def _make_fake_sftp_client() -> MagicMock:
    sftp = MagicMock()
    sftp.readdir = AsyncMock(return_value=[])
    sftp.exit = MagicMock()
    fh = MagicMock()
    fh.read = AsyncMock(return_value=b"data")
    fh.write = AsyncMock()
    fh.close = AsyncMock()
    sftp.open = AsyncMock(return_value=fh)
    sftp.remove = AsyncMock()
    sftp.rmdir = AsyncMock()
    sftp.rename = AsyncMock()
    sftp.mkdir = AsyncMock()
    return sftp


def _make_fake_conn(sftp_client: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.start_sftp_client = AsyncMock(return_value=sftp_client)
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    return conn


async def _open_session(auth_client, sftp, conn) -> str:
    """Helper: open an SFTP session and return its session_id."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        r = await auth_client.post(f"/api/sftp/session/{device_id}")

    assert r.status_code == 200
    return r.json()["session_id"]


# ── POST /api/sftp/session/{device_id} — extra error paths ────────────────────

async def test_open_sftp_session_connection_lost_returns_504(auth_client):
    """asyncssh.ConnectionLost during open must return 504."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch(
            "asyncssh.connect",
            new=AsyncMock(side_effect=asyncssh.ConnectionLost(reason="lost")),
        ),
    ):
        r = await auth_client.post(f"/api/sftp/session/{device_id}")

    assert r.status_code == 504


async def test_open_sftp_session_host_key_not_verifiable_returns_502(auth_client):
    """asyncssh.HostKeyNotVerifiable during open must return 502."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch(
            "asyncssh.connect",
            new=AsyncMock(
                side_effect=asyncssh.HostKeyNotVerifiable(
                    reason="key mismatch"
                )
            ),
        ),
    ):
        r = await auth_client.post(f"/api/sftp/session/{device_id}")

    assert r.status_code == 502


# ── GET /{session_id}/list — 500 path ─────────────────────────────────────────

async def test_list_directory_service_error_returns_500(auth_client):
    """An unexpected exception from list_directory must return 500."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.list_directory",
            new=AsyncMock(side_effect=RuntimeError("disk error")),
        ):
            r = await auth_client.get(f"/api/sftp/{sid}/list", params={"path": "/"})
        assert r.status_code == 500
        assert "disk error" in r.json()["detail"]
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)


# ── GET /{session_id}/download — 500 path ────────────────────────────────────

async def test_download_file_service_error_returns_500(auth_client):
    """An unexpected exception from read_file_bytes must return 500."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.read_file_bytes",
            new=AsyncMock(side_effect=RuntimeError("io error")),
        ):
            r = await auth_client.get(
                f"/api/sftp/{sid}/download", params={"path": "/file.txt"}
            )
        assert r.status_code == 500
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)


# ── POST /{session_id}/upload — error paths ───────────────────────────────────

async def test_upload_unknown_session_returns_404(auth_client):
    """Uploading to an unknown session must return 404."""
    r = await auth_client.post(
        "/api/sftp/no-such-session/upload",
        params={"path": "/uploads"},
        files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
    )
    assert r.status_code == 404


async def test_upload_service_error_returns_500(auth_client):
    """An unexpected exception from write_file_bytes must return 500."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.write_file_bytes",
            new=AsyncMock(side_effect=RuntimeError("write failed")),
        ):
            r = await auth_client.post(
                f"/api/sftp/{sid}/upload",
                params={"path": "/uploads"},
                files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
            )
        assert r.status_code == 500
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)


async def test_upload_path_with_trailing_slash(auth_client):
    """Upload path ending in '/' must still produce a valid remote path."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.write_file_bytes",
            new=AsyncMock(return_value=None),
        ):
            r = await auth_client.post(
                f"/api/sftp/{sid}/upload",
                params={"path": "/uploads/"},
                files={"file": ("myfile.txt", io.BytesIO(b"x"), "text/plain")},
            )
        assert r.status_code == 200
        assert r.json()["uploaded"].endswith("myfile.txt")
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)


# ── POST /{session_id}/delete — error paths ───────────────────────────────────

async def test_delete_unknown_session_returns_404(auth_client):
    """Deleting on an unknown session must return 404."""
    r = await auth_client.post(
        "/api/sftp/no-such-session/delete",
        json={"path": "/tmp/file.txt", "is_dir": False},
    )
    assert r.status_code == 404


async def test_delete_service_error_returns_500(auth_client):
    """An unexpected exception from delete_remote must return 500."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.delete_remote",
            new=AsyncMock(side_effect=RuntimeError("permission denied")),
        ):
            r = await auth_client.post(
                f"/api/sftp/{sid}/delete",
                json={"path": "/protected/file.txt", "is_dir": False},
            )
        assert r.status_code == 500
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)


# ── POST /{session_id}/rename — error paths ───────────────────────────────────

async def test_rename_unknown_session_returns_404(auth_client):
    """Renaming on an unknown session must return 404."""
    r = await auth_client.post(
        "/api/sftp/no-such-session/rename",
        json={"old_path": "/tmp/a.txt", "new_path": "/tmp/b.txt"},
    )
    assert r.status_code == 404


async def test_rename_service_error_returns_500(auth_client):
    """An unexpected exception from rename_remote must return 500."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.rename_remote",
            new=AsyncMock(side_effect=RuntimeError("rename failed")),
        ):
            r = await auth_client.post(
                f"/api/sftp/{sid}/rename",
                json={"old_path": "/tmp/a.txt", "new_path": "/tmp/b.txt"},
            )
        assert r.status_code == 500
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)


# ── POST /{session_id}/mkdir — error paths ────────────────────────────────────

async def test_mkdir_unknown_session_returns_404(auth_client):
    """Creating a directory on an unknown session must return 404."""
    r = await auth_client.post(
        "/api/sftp/no-such-session/mkdir",
        json={"path": "/tmp/newdir"},
    )
    assert r.status_code == 404


async def test_mkdir_service_error_returns_500(auth_client):
    """An unexpected exception from mkdir_remote must return 500."""
    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)
    sid = await _open_session(auth_client, sftp, conn)

    try:
        with patch(
            "backend.routers.sftp.mkdir_remote",
            new=AsyncMock(side_effect=RuntimeError("mkdir failed")),
        ):
            r = await auth_client.post(
                f"/api/sftp/{sid}/mkdir",
                json={"path": "/tmp/newdir"},
            )
        assert r.status_code == 500
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(sid, None)
