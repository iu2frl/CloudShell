"""
routers/sftp.py — REST endpoints for SFTP file manager sessions.

Session lifecycle
─────────────────
POST /sftp/session/{device_id}   → open SFTP session, returns session_id
GET  /sftp/{session_id}/list     → list directory contents
GET  /sftp/{session_id}/download → download a file
POST /sftp/{session_id}/upload   → upload a file (multipart form)
POST /sftp/{session_id}/delete   → delete file or directory
POST /sftp/{session_id}/rename   → rename / move
POST /sftp/{session_id}/mkdir    → create directory
DELETE /sftp/{session_id}        → close session
"""
import logging
import os
import tempfile
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.device import AuthType, Device
from backend.routers.auth import get_current_user
from backend.services.audit import (
    ACTION_SESSION_ENDED,
    ACTION_SESSION_STARTED,
    get_client_ip,
    write_audit,
)
from backend.services.crypto import decrypt, load_decrypted_key
from backend.services.sftp import (
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

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sftp", tags=["sftp"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_device_credentials(
    device: Device,
    settings,
) -> tuple[str | None, str | None, str | None]:
    """
    Return (password, key_path, tmp_key_file) for a device.

    ``tmp_key_file`` is a temp path that the caller must delete after use.
    """
    password: str | None = None
    key_path: str | None = None
    tmp_key_file: str | None = None

    if device.auth_type == AuthType.password:
        if device.encrypted_password:
            password = decrypt(device.encrypted_password)
    else:
        if device.key_filename:
            pem = load_decrypted_key(device.key_filename, settings.keys_dir)
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".pem", delete=False, dir="/tmp"
            )
            tmp.write(pem)
            tmp.flush()
            tmp.close()
            os.chmod(tmp.name, 0o600)
            key_path = tmp.name
            tmp_key_file = tmp.name

    return password, key_path, tmp_key_file


# ── Session management ────────────────────────────────────────────────────────

@router.post("/session/{device_id}")
async def open_session(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Open an SFTP session for a device and return a session_id."""
    import asyncssh

    settings = get_settings()
    device: Device | None = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    password, key_path, tmp_key_file = await _resolve_device_credentials(device, settings)
    client_ip = get_client_ip(request)
    device_label = f"{device.name} ({device.hostname}:{device.port})"

    try:
        session_id = await open_sftp_session(
            hostname=device.hostname,
            port=device.port,
            username=device.username,
            password=password,
            private_key_path=key_path,
            known_hosts="auto",
            device_label=device_label,
            cloudshell_user=current_user,
            source_ip=client_ip,
        )
    except asyncssh.PermissionDenied:
        raise HTTPException(status_code=401, detail="SSH authentication failed")
    except asyncssh.ConnectionLost:
        raise HTTPException(status_code=504, detail="SSH connection lost")
    except asyncssh.HostKeyNotVerifiable as exc:
        raise HTTPException(status_code=502, detail=f"Host key not verifiable: {exc}")
    except (OSError, asyncssh.Error) as exc:
        raise HTTPException(status_code=502, detail=f"SFTP connection failed: {exc}")
    finally:
        if tmp_key_file:
            try:
                os.unlink(tmp_key_file)
            except OSError:
                pass

    await write_audit(
        db,
        current_user,
        ACTION_SESSION_STARTED,
        detail=f"Started SFTP session with {device_label}",
        source_ip=client_ip,
    )
    return {"session_id": session_id}


@router.delete("/session/{session_id}", status_code=204)
async def close_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Close an SFTP session."""
    device_label, audit_user, audit_ip = get_sftp_session_meta(session_id)
    await close_sftp_session(session_id)
    await write_audit(
        db,
        audit_user or current_user,
        ACTION_SESSION_ENDED,
        detail=f"Ended SFTP session with {device_label}" if device_label else f"Ended SFTP session (id={session_id[:8]})",
        source_ip=audit_ip,
    )


# ── File operations ───────────────────────────────────────────────────────────

@router.get("/{session_id}/list")
async def list_dir(
    session_id: str,
    path: str = "/",
    _: str = Depends(get_current_user),
):
    """List directory contents at the given remote path."""
    try:
        entries = await list_directory(session_id, path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Directory listing failed: {exc}")
    return {"path": path, "entries": entries}


@router.get("/{session_id}/download")
async def download_file(
    session_id: str,
    path: str,
    _: str = Depends(get_current_user),
):
    """Download a remote file.  ``path`` must be URL-encoded."""
    remote_path = unquote(path)
    filename = os.path.basename(remote_path)
    try:
        data = await read_file_bytes(session_id, remote_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class UploadResponse(BaseModel):
    """Response model for file upload."""

    uploaded: str
    size: int


@router.post("/{session_id}/upload", response_model=UploadResponse)
async def upload_file(
    session_id: str,
    path: str,
    file: UploadFile = File(...),
    _: str = Depends(get_current_user),
):
    """
    Upload a file to the remote server.

    ``path`` is the target directory; the remote file will be placed at
    ``{path}/{file.filename}``.
    """
    target_dir = unquote(path)
    if target_dir.endswith("/"):
        remote_path = target_dir + (file.filename or "upload")
    else:
        remote_path = target_dir + "/" + (file.filename or "upload")

    data = await file.read()
    try:
        await write_file_bytes(session_id, remote_path, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")

    log.info(
        "SFTP uploaded %s bytes to %s (session %s)",
        len(data), remote_path, session_id[:8],
    )
    return UploadResponse(uploaded=remote_path, size=len(data))


class DeleteRequest(BaseModel):
    """Request body for delete operation."""

    path: str
    is_dir: bool = False


@router.post("/{session_id}/delete", status_code=204)
async def delete_path(
    session_id: str,
    body: DeleteRequest,
    _: str = Depends(get_current_user),
):
    """Delete a remote file or directory."""
    try:
        await delete_remote(session_id, body.path, body.is_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")


class RenameRequest(BaseModel):
    """Request body for rename operation."""

    old_path: str
    new_path: str


@router.post("/{session_id}/rename", status_code=204)
async def rename_path(
    session_id: str,
    body: RenameRequest,
    _: str = Depends(get_current_user),
):
    """Rename or move a remote path."""
    try:
        await rename_remote(session_id, body.old_path, body.new_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Rename failed: {exc}")


class MkdirRequest(BaseModel):
    """Request body for mkdir operation."""

    path: str


@router.post("/{session_id}/mkdir", status_code=204)
async def make_directory(
    session_id: str,
    body: MkdirRequest,
    _: str = Depends(get_current_user),
):
    """Create a remote directory."""
    try:
        await mkdir_remote(session_id, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Mkdir failed: {exc}")
