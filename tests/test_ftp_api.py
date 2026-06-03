"""
tests/test_ftp_api.py — integration tests for the FTP/FTPS file manager API.

Tests cover:
- POST /api/ftp/session/{device_id}
  - requires authentication
  - returns 404 for unknown device
  - returns 400 for non-FTP device
  - auth failure -> 401 / connection failure -> 502
  - success: returns session_id and writes audit entry
- DELETE /api/ftp/session/{session_id}
  - requires authentication
  - closes session and writes SESSION_ENDED audit entry
- GET /api/ftp/{session_id}/list
  - requires authentication
  - returns 404 for unknown session
  - returns directory listing
- GET /api/ftp/{session_id}/download
  - requires authentication
  - streams file content
- POST /api/ftp/{session_id}/upload
  - requires authentication
  - saves file and returns metadata
- POST /api/ftp/{session_id}/delete
  - requires authentication
  - calls delete on FTP service
- POST /api/ftp/{session_id}/rename
  - requires authentication
  - calls rename on FTP service
- POST /api/ftp/{session_id}/mkdir
  - requires authentication
  - calls mkdir on FTP service
- FTPS connection type is accepted
"""
import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from backend.models.audit import AuditLog
from backend.services.audit import ACTION_SESSION_ENDED, ACTION_SESSION_STARTED


# -- Helpers -------------------------------------------------------------------


def _ftp_device_payload(**overrides) -> dict:
    return {
        "name": "ftp-server",
        "hostname": "192.168.1.30",
        "port": 21,
        "username": "ftpuser",
        "auth_type": "password",
        "connection_type": "ftp",
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


def _make_fake_ftp_client() -> MagicMock:
    """Return a minimal aioftp Client mock that covers all tested operations."""
    client = MagicMock()

    # connect / login / quit are coroutines
    client.connect = AsyncMock()
    client.login = AsyncMock()
    client.quit = AsyncMock()

    # list() yields (path, info) tuples — simulate a single file entry
    async def _fake_list(path, recursive=False):
        from pathlib import PurePosixPath
        yield PurePosixPath("/test.txt"), {
            "type": "file",
            "size": "42",
            "modify": "20240101120000",
        }

    client.list = _fake_list

    # download_stream / upload_stream are async context managers
    fake_dl_stream = MagicMock()
    fake_dl_stream.__aenter__ = AsyncMock(return_value=fake_dl_stream)
    fake_dl_stream.__aexit__ = AsyncMock(return_value=False)

    async def _iter_by_block():
        yield b"hello ftp"

    fake_dl_stream.iter_by_block = _iter_by_block
    client.download_stream = MagicMock(return_value=fake_dl_stream)

    fake_ul_stream = MagicMock()
    fake_ul_stream.__aenter__ = AsyncMock(return_value=fake_ul_stream)
    fake_ul_stream.__aexit__ = AsyncMock(return_value=False)
    fake_ul_stream.write = AsyncMock()
    client.upload_stream = MagicMock(return_value=fake_ul_stream)

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


# -- Session open --------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_ftp_session_requires_auth(client):
    resp = await client.post("/api/ftp/session/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_open_ftp_session_device_not_found(auth_client):
    resp = await auth_client.post("/api/ftp/session/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_open_ftp_session_wrong_connection_type(auth_client):
    """A device with connection_type='ssh' must return 400 when opened as FTP."""
    resp = await auth_client.post("/api/devices/", json=_ssh_device_payload())
    assert resp.status_code == 201
    device_id = resp.json()["id"]

    resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    assert resp.status_code == 400
    assert "not configured as FTP" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_open_ftp_session_connection_error(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    assert resp.status_code == 201
    device_id = resp.json()["id"]

    with patch(
        "backend.services.ftp.aioftp.Client",
        return_value=MagicMock(
            connect=AsyncMock(side_effect=OSError("Connection refused")),
            login=AsyncMock(),
            quit=AsyncMock(),
        ),
    ):
        resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_open_ftp_session_success_writes_audit(auth_client, db_session):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    assert resp.status_code == 201
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        resp = await auth_client.post(f"/api/ftp/session/{device_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    session_id = data["session_id"]

    # Audit entry must exist
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == ACTION_SESSION_STARTED)
    )
    entries = result.scalars().all()
    assert any("FTP" in (e.detail or "") for e in entries)

    # Cleanup
    with patch("backend.services.ftp._ftp_sessions", {}):
        pass
    return session_id


@pytest.mark.asyncio
async def test_open_ftps_session_success(auth_client):
    payload = _ftp_device_payload(connection_type="ftps", port=21)
    resp = await auth_client.post("/api/devices/", json=payload)
    assert resp.status_code == 201
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        challenge = await auth_client.post(f"/api/ftp/session/{device_id}")
        assert challenge.status_code == 409
        assert challenge.json()["detail"]["code"] == "FTPS_CERT_UNTRUSTED"

        resp = await auth_client.post(f"/api/ftp/session/{device_id}?trust_cert=true")

    assert resp.status_code == 200
    assert "session_id" in resp.json()


@pytest.mark.asyncio
async def test_open_ftps_session_changed_cert_requires_confirmation(auth_client):
    payload = _ftp_device_payload(connection_type="ftps", port=21)
    resp = await auth_client.post("/api/devices/", json=payload)
    assert resp.status_code == 201
    device_id = resp.json()["id"]

    await auth_client.put(
        f"/api/devices/{device_id}",
        json={"ftps_cert_thumbprint": "AA:BB:CC"},
    )

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        challenge = await auth_client.post(f"/api/ftp/session/{device_id}")
        assert challenge.status_code == 409
        assert challenge.json()["detail"]["code"] == "FTPS_CERT_CHANGED"


# -- Session close -------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_ftp_session_requires_auth(client):
    resp = await client.delete("/api/ftp/session/abc-123")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_close_ftp_session_success_writes_audit(auth_client, db_session):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.delete(f"/api/ftp/session/{session_id}")
    assert resp.status_code == 204

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == ACTION_SESSION_ENDED)
    )
    assert result.scalars().first() is not None


# -- Directory listing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_dir_requires_auth(client):
    resp = await client.get("/api/ftp/abc-123/list")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_dir_unknown_session(auth_client):
    resp = await auth_client.get("/api/ftp/no-such-session/list?path=/")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_dir_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.get(f"/api/ftp/{session_id}/list?path=/")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert any(e["name"] == "test.txt" for e in data["entries"])

    await auth_client.delete(f"/api/ftp/session/{session_id}")


# -- Download ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_requires_auth(client):
    resp = await client.get("/api/ftp/abc-123/download?path=/test.txt")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_download_unknown_session(auth_client):
    resp = await auth_client.get("/api/ftp/no-such-session/download?path=%2Ftest.txt")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.get(
        f"/api/ftp/{session_id}/download?path=%2Ftest.txt"
    )
    assert resp.status_code == 200
    assert resp.content == b"hello ftp"
    assert "attachment" in resp.headers.get("content-disposition", "")

    await auth_client.delete(f"/api/ftp/session/{session_id}")


# -- Upload --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    resp = await client.post(
        "/api/ftp/abc-123/upload?path=/",
        files={"file": ("hello.txt", io.BytesIO(b"data"), "text/plain")},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.post(
        f"/api/ftp/{session_id}/upload?path=/",
        files={"file": ("hello.txt", io.BytesIO(b"uploaded data"), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["uploaded"].endswith("hello.txt")
    assert data["size"] == len(b"uploaded data")
    status = await _wait_for_upload(auth_client, session_id, data["upload_id"])
    assert status["status"] == "completed"

    await auth_client.delete(f"/api/ftp/session/{session_id}")


# -- Delete --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_requires_auth(client):
    resp = await client.post(
        "/api/ftp/abc-123/delete", json={"path": "/test.txt", "is_dir": False}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_file_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.post(
        f"/api/ftp/{session_id}/delete",
        json={"path": "/test.txt", "is_dir": False},
    )
    assert resp.status_code == 204
    fake_client.remove_file.assert_awaited_once_with("/test.txt")

    await auth_client.delete(f"/api/ftp/session/{session_id}")


@pytest.mark.asyncio
async def test_delete_dir_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    # Override list to return empty directory so recursive delete finishes fast
    async def _empty_list(path, recursive=False):
        return
        yield  # noqa: unreachable - makes this an async generator

    fake_client.list = _empty_list
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.post(
        f"/api/ftp/{session_id}/delete",
        json={"path": "/mydir", "is_dir": True},
    )
    assert resp.status_code == 200
    delete_id = resp.json()["delete_id"]
    status = await _wait_for_delete(auth_client, session_id, delete_id)
    assert status["status"] == "completed"
    assert status["deleted_items"] == 1
    fake_client.remove_directory.assert_awaited_once_with("/mydir")

    await auth_client.delete(f"/api/ftp/session/{session_id}")


# -- Rename --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_requires_auth(client):
    resp = await client.post(
        "/api/ftp/abc-123/rename",
        json={"old_path": "/a.txt", "new_path": "/b.txt"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rename_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.post(
        f"/api/ftp/{session_id}/rename",
        json={"old_path": "/a.txt", "new_path": "/b.txt"},
    )
    assert resp.status_code == 204
    fake_client.rename.assert_awaited_once_with("/a.txt", "/b.txt")

    await auth_client.delete(f"/api/ftp/session/{session_id}")


# -- Mkdir ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mkdir_requires_auth(client):
    resp = await client.post("/api/ftp/abc-123/mkdir", json={"path": "/newdir"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mkdir_success(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    fake_client = _make_fake_ftp_client()
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    session_id = open_resp.json()["session_id"]

    resp = await auth_client.post(
        f"/api/ftp/{session_id}/mkdir", json={"path": "/newdir"}
    )
    assert resp.status_code == 204
    fake_client.make_directory.assert_awaited_once_with("/newdir")

    await auth_client.delete(f"/api/ftp/session/{session_id}")


# -- Device CRUD: ftp / ftps connection types persisted -----------------------


@pytest.mark.asyncio
async def test_device_ftp_connection_type_persisted(auth_client):
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    assert resp.status_code == 201
    device = resp.json()
    assert device["connection_type"] == "ftp"


@pytest.mark.asyncio
async def test_device_ftps_connection_type_persisted(auth_client):
    payload = _ftp_device_payload(connection_type="ftps", name="ftps-server")
    resp = await auth_client.post("/api/devices/", json=payload)
    assert resp.status_code == 201
    device = resp.json()
    assert device["connection_type"] == "ftps"


# -- Session open: specific exception branches ---------------------------------


@pytest.mark.asyncio
async def test_open_ftp_session_permission_error_returns_502(auth_client):
    """PermissionError (wrong credentials) must map to HTTP 502 (not 401, to avoid forcing logout)."""
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    with patch(
        "backend.services.ftp.aioftp.Client",
        return_value=MagicMock(
            connect=AsyncMock(side_effect=PermissionError("Login incorrect")),
            login=AsyncMock(),
            quit=AsyncMock(),
            upgrade_to_tls=AsyncMock(),
        ),
    ):
        resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    assert resp.status_code == 502
    assert "authentication failed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_open_ftp_session_connection_refused_returns_502(auth_client):
    """ConnectionRefusedError must map to HTTP 502."""
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]

    with patch(
        "backend.services.ftp.aioftp.Client",
        return_value=MagicMock(
            connect=AsyncMock(side_effect=ConnectionRefusedError("Connection refused")),
            login=AsyncMock(),
            quit=AsyncMock(),
            upgrade_to_tls=AsyncMock(),
        ),
    ):
        resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    assert resp.status_code == 502
    assert "refused" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_close_session_unknown_id_uses_fallback_audit_message(auth_client, db_session):
    """Closing an unknown session_id should still write an audit entry using
    the fallback 'id=…' format rather than a device label."""
    from sqlalchemy import select
    from backend.models.audit import AuditLog
    from backend.services.audit import ACTION_SESSION_ENDED

    resp = await auth_client.delete("/api/ftp/session/unknown-session-id")
    assert resp.status_code == 204

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == ACTION_SESSION_ENDED)
    )
    entry = result.scalars().first()
    assert entry is not None
    assert "unknown-" in (entry.detail or "")


# -- File operation 500 error paths --------------------------------------------

async def _open_session(auth_client, fake_client) -> str:
    """Helper: create a device and open a session with the given fake client."""
    resp = await auth_client.post("/api/devices/", json=_ftp_device_payload())
    device_id = resp.json()["id"]
    with patch("backend.services.ftp.aioftp.Client", return_value=fake_client):
        open_resp = await auth_client.post(f"/api/ftp/session/{device_id}")
    return open_resp.json()["session_id"]


async def _wait_for_upload(auth_client, session_id: str, upload_id: str) -> dict:
    """Poll upload status until completion or failure."""
    for _ in range(100):
        status_resp = await auth_client.get(
            f"/api/ftp/{session_id}/upload/{upload_id}"
        )
        if status_resp.status_code == 200:
            status = status_resp.json()
            if status.get("status") in ("completed", "failed"):
                return status
        await asyncio.sleep(0.05)
    raise AssertionError("Upload did not complete in time")


async def _wait_for_delete(auth_client, session_id: str, delete_id: str) -> dict:
    """Poll delete status until completion or failure."""
    for _ in range(100):
        status_resp = await auth_client.get(
            f"/api/ftp/{session_id}/delete/{delete_id}"
        )
        if status_resp.status_code == 200:
            status = status_resp.json()
            if status.get("status") in ("completed", "failed"):
                return status
        await asyncio.sleep(0.05)
    raise AssertionError("Delete did not complete in time")


@pytest.mark.asyncio
async def test_list_dir_generic_error_returns_500(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.list_directory", side_effect=RuntimeError("boom")):
        resp = await auth_client.get(f"/api/ftp/{sid}/list?path=/")
    assert resp.status_code == 500
    assert "Directory listing failed" in resp.json()["detail"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_download_generic_error_returns_500(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.read_file_bytes", side_effect=RuntimeError("boom")):
        resp = await auth_client.get(f"/api/ftp/{sid}/download?path=%2Ftest.txt")
    assert resp.status_code == 500
    assert "Download failed" in resp.json()["detail"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_upload_generic_error_returns_500(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.write_file_bytes", side_effect=RuntimeError("boom")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/upload?path=/",
            files={"file": ("f.txt", io.BytesIO(b"data"), "text/plain")},
        )
    assert resp.status_code == 200
    status = await _wait_for_upload(auth_client, sid, resp.json()["upload_id"])
    assert status["status"] == "failed"
    assert "boom" in status["error"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_upload_with_trailing_slash_path(auth_client):
    """When path ends with '/', the remote path must be path + filename."""
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    resp = await auth_client.post(
        f"/api/ftp/{sid}/upload?path=%2Fsome%2Fdir%2F",
        files={"file": ("hello.txt", io.BytesIO(b"data"), "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["uploaded"] == "/some/dir/hello.txt"
    status = await _wait_for_upload(auth_client, sid, resp.json()["upload_id"])
    assert status["status"] == "completed"

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_delete_generic_error_returns_500(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.delete_remote", side_effect=RuntimeError("boom")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/delete", json={"path": "/x.txt", "is_dir": False}
        )
    assert resp.status_code == 500
    assert "Delete failed" in resp.json()["detail"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_rename_generic_error_returns_500(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.rename_remote", side_effect=RuntimeError("boom")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/rename", json={"old_path": "/a.txt", "new_path": "/b.txt"}
        )
    assert resp.status_code == 500
    assert "Rename failed" in resp.json()["detail"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_mkdir_generic_error_returns_500(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.mkdir_remote", side_effect=RuntimeError("boom")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/mkdir", json={"path": "/newdir"}
        )
    assert resp.status_code == 500
    assert "Mkdir failed" in resp.json()["detail"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


# -- File operation ValueError (404) paths -------------------------------------


@pytest.mark.asyncio
async def test_list_dir_value_error_returns_404(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.list_directory", side_effect=ValueError("no such path")):
        resp = await auth_client.get(f"/api/ftp/{sid}/list?path=/missing")
    assert resp.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_download_value_error_returns_404(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.read_file_bytes", side_effect=ValueError("no such file")):
        resp = await auth_client.get(f"/api/ftp/{sid}/download?path=%2Fmissing.txt")
    assert resp.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_upload_value_error_returns_404(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.write_file_bytes", side_effect=ValueError("no such dir")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/upload?path=/missing",
            files={"file": ("f.txt", io.BytesIO(b"d"), "text/plain")},
        )
    assert resp.status_code == 200
    status = await _wait_for_upload(auth_client, sid, resp.json()["upload_id"])
    assert status["status"] == "failed"
    assert "no such dir" in status["error"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_delete_value_error_returns_404(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.delete_remote", side_effect=ValueError("no such file")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/delete", json={"path": "/missing.txt", "is_dir": False}
        )
    assert resp.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_rename_value_error_returns_404(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.rename_remote", side_effect=ValueError("no such file")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/rename", json={"old_path": "/missing.txt", "new_path": "/x.txt"}
        )
    assert resp.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_mkdir_value_error_returns_404(auth_client):
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.mkdir_remote", side_effect=ValueError("no such parent")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/mkdir", json={"path": "/missing/newdir"}
        )
    assert resp.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")


# -- Upload status eviction ---------------------------------------------------


@pytest.mark.asyncio
async def test_upload_status_evicted_after_ttl(auth_client):
    """Completed uploads are removed from _upload_status after TTL expires."""
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    resp = await auth_client.post(
        f"/api/ftp/{sid}/upload?path=/",
        files={"file": ("f.txt", io.BytesIO(b"data"), "text/plain")},
    )
    upload_id = resp.json()["upload_id"]
    status = await _wait_for_upload(auth_client, sid, upload_id)
    assert status["status"] == "completed"

    # Still accessible right after completion
    check = await auth_client.get(f"/api/ftp/{sid}/upload/{upload_id}")
    assert check.status_code == 200

    # Simulate TTL expiry by backdating completed_at
    from backend.routers.ftp import _upload_status, _UPLOAD_STATUS_TTL
    _upload_status[upload_id]["completed_at"] -= _UPLOAD_STATUS_TTL + 1

    # Next poll triggers eviction
    check = await auth_client.get(f"/api/ftp/{sid}/upload/{upload_id}")
    assert check.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")


# -- Delete background / recursive -------------------------------------------


@pytest.mark.asyncio
async def test_delete_dir_recursive_via_api(auth_client):
    """Directory delete runs in background and reports item count."""
    fake = _make_fake_ftp_client()

    # Tree: /parent/ -> child/ + file_a.txt; /parent/child/ -> (empty)
    from pathlib import PurePosixPath

    async def _tree_list(path, recursive=False):
        if path == "/parent":
            yield PurePosixPath("file_a.txt"), {"type": "file", "size": "10"}
            yield PurePosixPath("child"), {"type": "dir", "size": "0"}
        # /parent/child yields nothing (empty)

    fake.list = _tree_list
    sid = await _open_session(auth_client, fake)

    resp = await auth_client.post(
        f"/api/ftp/{sid}/delete", json={"path": "/parent", "is_dir": True},
    )
    assert resp.status_code == 200
    delete_id = resp.json()["delete_id"]

    status = await _wait_for_delete(auth_client, sid, delete_id)
    assert status["status"] == "completed"
    # file_a.txt + child/ + parent/ = 3 items
    assert status["deleted_items"] == 3

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_delete_dir_error_returns_failed_status(auth_client):
    """Background directory delete that fails reports error via status."""
    fake = _make_fake_ftp_client()
    sid = await _open_session(auth_client, fake)

    with patch("backend.routers.ftp.delete_remote", side_effect=RuntimeError("disk full")):
        resp = await auth_client.post(
            f"/api/ftp/{sid}/delete", json={"path": "/mydir", "is_dir": True},
        )
    assert resp.status_code == 200
    status = await _wait_for_delete(auth_client, sid, resp.json()["delete_id"])
    assert status["status"] == "failed"
    assert "disk full" in status["error"]

    await auth_client.delete(f"/api/ftp/session/{sid}")


@pytest.mark.asyncio
async def test_delete_status_evicted_after_ttl(auth_client):
    """Completed deletes are removed from _delete_status after TTL expires."""
    fake = _make_fake_ftp_client()

    async def _empty_list(path, recursive=False):
        return
        yield  # noqa: unreachable

    fake.list = _empty_list
    sid = await _open_session(auth_client, fake)

    resp = await auth_client.post(
        f"/api/ftp/{sid}/delete", json={"path": "/mydir", "is_dir": True},
    )
    delete_id = resp.json()["delete_id"]
    status = await _wait_for_delete(auth_client, sid, delete_id)
    assert status["status"] == "completed"

    # Still accessible right after completion
    check = await auth_client.get(f"/api/ftp/{sid}/delete/{delete_id}")
    assert check.status_code == 200

    # Simulate TTL expiry
    from backend.routers.ftp import _delete_status, _UPLOAD_STATUS_TTL
    _delete_status[delete_id]["completed_at"] -= _UPLOAD_STATUS_TTL + 1

    check = await auth_client.get(f"/api/ftp/{sid}/delete/{delete_id}")
    assert check.status_code == 404

    await auth_client.delete(f"/api/ftp/session/{sid}")
