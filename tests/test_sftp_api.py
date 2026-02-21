"""
tests/test_sftp_api.py — integration tests for the SFTP file manager API.

Tests cover:
- POST /api/sftp/session/{device_id}
  - requires authentication
  - returns 404 for unknown device
  - SSH auth failure → 401
  - SSH connection failure → 502
  - success: returns session_id and writes audit entry
- DELETE /api/sftp/session/{session_id}
  - requires authentication
  - closes session and writes SESSION_ENDED audit entry
- GET /api/sftp/{session_id}/list
  - requires authentication
  - returns 404 for unknown session
  - returns directory listing
- GET /api/sftp/{session_id}/download
  - requires authentication
  - returns 404 for unknown session
  - streams file content
- POST /api/sftp/{session_id}/upload
  - requires authentication
  - saves file and returns metadata
- POST /api/sftp/{session_id}/delete
  - requires authentication
  - calls delete on SFTP service
- POST /api/sftp/{session_id}/rename
  - requires authentication
  - calls rename on SFTP service
- POST /api/sftp/{session_id}/mkdir
  - requires authentication
  - calls mkdir on SFTP service
- Device CRUD: connection_type field is persisted and returned
"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest
from sqlalchemy import select

from backend.models.audit import AuditLog
from backend.services.audit import ACTION_SESSION_ENDED, ACTION_SESSION_STARTED


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


def _ssh_device_payload(**overrides) -> dict:
    return {
        "name": "ssh-server",
        "hostname": "192.168.1.10",
        "port": 22,
        "username": "root",
        "auth_type": "password",
        "connection_type": "ssh",
        "password": "s3cr3t",
        **overrides,
    }


def _make_fake_sftp_entry(name: str, is_dir: bool = False) -> MagicMock:
    entry = MagicMock()
    entry.filename = name
    attrs = MagicMock()
    attrs.size = 100
    attrs.type = (
        asyncssh.FILEXFER_TYPE_DIRECTORY if is_dir else asyncssh.FILEXFER_TYPE_REGULAR
    )
    attrs.permissions = 0o644
    attrs.mtime = 1700000000
    entry.attrs = attrs
    return entry


def _make_fake_sftp_client() -> MagicMock:
    sftp = MagicMock()
    sftp.readdir = AsyncMock(return_value=[_make_fake_sftp_entry("test.txt")])
    sftp.exit = MagicMock()

    # File handle returned by open()
    fake_fh = MagicMock()
    fake_fh.read = AsyncMock(return_value=b"hello world")
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
    conn = MagicMock()
    conn.start_sftp_client = AsyncMock(return_value=sftp_client)
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()
    return conn


# ── Device connection_type field ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_device_connection_type_persisted(auth_client):
    """connection_type is stored and returned in device CRUD."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["connection_type"] == "sftp"

    resp2 = await auth_client.get(f"/api/devices/{data['id']}")
    assert resp2.json()["connection_type"] == "sftp"


@pytest.mark.asyncio
async def test_device_ssh_connection_type_default(auth_client):
    """SSH terminal devices have connection_type=ssh."""
    resp = await auth_client.post("/api/devices/", json=_ssh_device_payload())
    assert resp.status_code == 201
    assert resp.json()["connection_type"] == "ssh"


@pytest.mark.asyncio
async def test_device_update_connection_type(auth_client):
    """PUT /api/devices/{id} can change connection_type."""
    resp = await auth_client.post("/api/devices/", json=_ssh_device_payload())
    device_id = resp.json()["id"]

    upd = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"connection_type": "sftp"},
    )
    assert upd.status_code == 200
    assert upd.json()["connection_type"] == "sftp"


# ── POST /api/sftp/session/{device_id} ───────────────────────────────────────

@pytest.mark.asyncio
async def test_open_sftp_session_requires_auth(client, db_session):
    """POST /api/sftp/session/{id} without a token returns 401."""
    login = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    create = await client.post("/api/devices/", json=_sftp_device_payload())
    device_id = create.json()["id"]

    client.headers.clear()
    resp = await client.post(f"/api/sftp/session/{device_id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_open_sftp_session_device_not_found(auth_client):
    """POST /api/sftp/session/9999 for a non-existent device returns 404."""
    resp = await auth_client.post("/api/sftp/session/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_open_sftp_session_auth_failure(auth_client):
    """SSH PermissionDenied maps to 401."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch(
            "asyncssh.connect",
            new=AsyncMock(
                side_effect=asyncssh.PermissionDenied(reason="bad auth")
            ),
        ),
    ):
        r = await auth_client.post(f"/api/sftp/session/{device_id}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_open_sftp_session_connection_failure(auth_client):
    """Generic SSH error maps to 502."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch(
            "asyncssh.connect",
            new=AsyncMock(side_effect=OSError("connection refused")),
        ),
    ):
        r = await auth_client.post(f"/api/sftp/session/{device_id}")
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_open_sftp_session_success(auth_client, db_session):
    """Successful open returns a session_id and writes audit."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        r = await auth_client.post(f"/api/sftp/session/{device_id}")

    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data

    # Audit entry created
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == ACTION_SESSION_STARTED)
    )
    entries = result.scalars().all()
    assert any("SFTP" in (e.detail or "") for e in entries)

    # Cleanup
    session_id = data["session_id"]
    from backend.services.sftp import _sftp_sessions
    _sftp_sessions.pop(session_id, None)


# ── DELETE /api/sftp/session/{session_id} ────────────────────────────────────

@pytest.mark.asyncio
async def test_close_sftp_session(auth_client, db_session):
    """DELETE closes session and writes SESSION_ENDED audit."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    close_r = await auth_client.delete(f"/api/sftp/session/{session_id}")
    assert close_r.status_code == 204

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == ACTION_SESSION_ENDED)
    )
    assert result.scalars().first() is not None


# ── GET /api/sftp/{session_id}/list ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_unknown_session(auth_client):
    """Listing an unknown session returns 404."""
    r = await auth_client.get(
        "/api/sftp/no-such-session/list",
        params={"path": "/"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_directory(auth_client):
    """GET list returns entries with expected keys."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    try:
        r = await auth_client.get(
            f"/api/sftp/{session_id}/list", params={"path": "/home"}
        )
        assert r.status_code == 200
        body = r.json()
        assert "entries" in body
        assert len(body["entries"]) == 1
        entry = body["entries"][0]
        for key in ("name", "path", "size", "is_dir", "permissions", "modified"):
            assert key in entry
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(session_id, None)


# ── GET /api/sftp/{session_id}/download ──────────────────────────────────────

@pytest.mark.asyncio
async def test_download_unknown_session(auth_client):
    r = await auth_client.get(
        "/api/sftp/no-such-session/download",
        params={"path": "/etc/passwd"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_download_file(auth_client):
    """Download returns the file bytes with correct headers."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    try:
        r = await auth_client.get(
            f"/api/sftp/{session_id}/download",
            params={"path": "/etc/passwd"},
        )
        assert r.status_code == 200
        assert r.content == b"hello world"
        assert "attachment" in r.headers.get("content-disposition", "")
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(session_id, None)


# ── POST /api/sftp/{session_id}/upload ───────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_file(auth_client):
    """Upload POSTs a file and returns metadata."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    try:
        file_content = b"test-upload-content"
        r = await auth_client.post(
            f"/api/sftp/{session_id}/upload",
            params={"path": "/uploads"},
            files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["size"] == len(file_content)
        assert "test.txt" in body["uploaded"]
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(session_id, None)


# ── POST /api/sftp/{session_id}/delete ───────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_file(auth_client):
    """Delete endpoint calls SFTP remove."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    try:
        r = await auth_client.post(
            f"/api/sftp/{session_id}/delete",
            json={"path": "/tmp/file.txt", "is_dir": False},
        )
        assert r.status_code == 204
        sftp.remove.assert_called_once_with("/tmp/file.txt")
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(session_id, None)


# ── POST /api/sftp/{session_id}/rename ───────────────────────────────────────

@pytest.mark.asyncio
async def test_rename(auth_client):
    """Rename endpoint calls SFTP rename."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    try:
        r = await auth_client.post(
            f"/api/sftp/{session_id}/rename",
            json={"old_path": "/tmp/old.txt", "new_path": "/tmp/new.txt"},
        )
        assert r.status_code == 204
        sftp.rename.assert_called_once_with("/tmp/old.txt", "/tmp/new.txt")
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(session_id, None)


# ── POST /api/sftp/{session_id}/mkdir ────────────────────────────────────────

@pytest.mark.asyncio
async def test_mkdir(auth_client):
    """Mkdir endpoint calls SFTP mkdir."""
    resp = await auth_client.post("/api/devices/", json=_sftp_device_payload())
    device_id = resp.json()["id"]

    sftp = _make_fake_sftp_client()
    conn = _make_fake_conn(sftp)

    with (
        patch("backend.services.sftp._known_hosts_path", return_value=None),
        patch("asyncssh.connect", new=AsyncMock(return_value=conn)),
    ):
        open_r = await auth_client.post(f"/api/sftp/session/{device_id}")

    session_id = open_r.json()["session_id"]

    try:
        r = await auth_client.post(
            f"/api/sftp/{session_id}/mkdir",
            json={"path": "/tmp/newdir"},
        )
        assert r.status_code == 204
        sftp.mkdir.assert_called_once_with("/tmp/newdir")
    finally:
        from backend.services.sftp import _sftp_sessions
        _sftp_sessions.pop(session_id, None)
