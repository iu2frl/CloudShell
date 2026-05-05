"""
routers/ftp.py — REST endpoints for FTP/FTPS file manager sessions.

Session lifecycle
-----------------
POST /ftp/session/{device_id}    → open FTP/FTPS session, returns session_id
GET  /ftp/{session_id}/list      → list directory contents
GET  /ftp/{session_id}/download  → download a file
POST /ftp/{session_id}/upload    → upload a file (multipart form)
POST /ftp/{session_id}/delete    → delete a file
POST /ftp/{session_id}/rename    → rename / move
POST /ftp/{session_id}/mkdir     → create directory
DELETE /ftp/{session_id}         → close session
"""
import logging
import os
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.device import ConnectionType, Device
from backend.routers.auth import get_current_user
from backend.services.audit import (
    ACTION_SESSION_ENDED,
    ACTION_SESSION_STARTED,
    get_client_ip,
    write_audit,
)
from backend.services.crypto import decrypt
from backend.services.ftp import (
    FTPSCertificateMismatchError,
    FTPSCertificateUnavailableError,
    close_ftp_session,
    delete_remote,
    get_ftp_session_meta,
    list_directory,
    mkdir_remote,
    open_ftp_session,
    probe_ftps_thumbprint,
    read_file_bytes,
    rename_remote,
    write_file_bytes,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ftp", tags=["ftp"])

# Track active uploads for UI feedback
_upload_status: dict[str, dict] = {}


async def _perform_upload(
    session_id: str,
    remote_path: str,
    data: bytes,
    filename: str,
    upload_id: str,
) -> None:
    """Background task to perform FTP upload and track status."""
    try:
        file_size_mb = len(data) / (1024 * 1024)
        log.info(
            "FTP background upload starting: %s (%.2f MB), upload_id=%s, session=%s",
            filename,
            file_size_mb,
            upload_id,
            session_id[:8],
        )
        _upload_status[upload_id] = {
            "status": "uploading",
            "filename": filename,
            "size_bytes": len(data),
            "size_mb": file_size_mb,
        }
        
        await write_file_bytes(session_id, remote_path, data)
        
        _upload_status[upload_id] = {
            "status": "completed",
            "filename": filename,
            "size_bytes": len(data),
            "size_mb": file_size_mb,
        }
        log.info(
            "FTP background upload completed: %s (%.2f MB), upload_id=%s, session=%s",
            filename,
            file_size_mb,
            upload_id,
            session_id[:8],
        )
    except Exception as exc:
        log.error(
            "FTP background upload failed: %s, error=%s, upload_id=%s, session=%s",
            filename,
            exc,
            upload_id,
            session_id[:8],
        )
        _upload_status[upload_id] = {
            "status": "failed",
            "filename": filename,
            "error": str(exc),
        }


# -- Session management --------------------------------------------------------


@router.post("/session/{device_id}")
async def open_session(
    device_id: int,
    request: Request,
    trust_cert: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Open an FTP/FTPS session for a device and return a session_id."""
    device: Device | None = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.connection_type not in (ConnectionType.ftp, ConnectionType.ftps):
        raise HTTPException(
            status_code=400,
            detail="Device is not configured as FTP/FTPS",
        )

    password: str | None = None
    if device.encrypted_password:
        password = decrypt(device.encrypted_password)

    use_tls = device.connection_type == ConnectionType.ftps
    client_ip = get_client_ip(request)
    device_label = f"{device.name} ({device.hostname}:{device.port})"
    expected_thumbprint: str | None = None

    if use_tls:
        try:
            presented_thumbprint = await probe_ftps_thumbprint(device.hostname, device.port)
        except FTPSCertificateUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"FTPS certificate unavailable: {exc}") from exc

        pinned_thumbprint = device.ftps_cert_thumbprint
        if pinned_thumbprint is None:
            if not trust_cert:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "FTPS_CERT_UNTRUSTED",
                        "thumbprint": presented_thumbprint,
                    },
                )
            device.ftps_cert_thumbprint = presented_thumbprint
            await db.commit()
        elif pinned_thumbprint != presented_thumbprint:
            if not trust_cert:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "FTPS_CERT_CHANGED",
                        "thumbprint": presented_thumbprint,
                        "previous_thumbprint": pinned_thumbprint,
                    },
                )
            device.ftps_cert_thumbprint = presented_thumbprint
            await db.commit()

        expected_thumbprint = device.ftps_cert_thumbprint

    try:
        session_id = await open_ftp_session(
            hostname=device.hostname,
            port=device.port,
            username=device.username,
            password=password,
            use_tls=use_tls,
            device_label=device_label,
            cloudshell_user=current_user,
            source_ip=client_ip,
            expected_ftps_thumbprint=expected_thumbprint,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=502, detail=f"FTP authentication failed: {exc}") from exc
    except ConnectionRefusedError as exc:
        raise HTTPException(status_code=502, detail=f"FTP connection refused: {exc}") from exc
    except FTPSCertificateMismatchError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FTPS_CERT_CHANGED",
                "thumbprint": exc.presented,
                "previous_thumbprint": exc.expected,
            },
        ) from exc
    except (OSError, Exception) as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"FTP connection failed: {exc}") from exc

    await write_audit(
        db,
        current_user,
        ACTION_SESSION_STARTED,
        detail=f"Started FTP{'S' if use_tls else ''} session with {device_label}",
        source_ip=client_ip,
    )
    return {"session_id": session_id}


@router.delete("/session/{session_id}", status_code=204)
async def close_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Close an FTP/FTPS session."""
    device_label, audit_user, audit_ip = get_ftp_session_meta(session_id)
    await close_ftp_session(session_id)
    await write_audit(
        db,
        audit_user or current_user,
        ACTION_SESSION_ENDED,
        detail=(
            f"Ended FTP session with {device_label}"
            if device_label
            else f"Ended FTP session (id={session_id[:8]})"
        ),
        source_ip=audit_ip,
    )


# -- File operations -----------------------------------------------------------


@router.get("/{session_id}/list")
async def list_dir(
    session_id: str,
    path: str = "/",
    _: str = Depends(get_current_user),
):
    """List directory contents at the given remote path."""
    log.debug(
        "FTP list directory request: path=%s, session=%s",
        path,
        session_id[:8],
    )
    
    try:
        entries = await list_directory(session_id, path)
        log.info(
            "FTP list directory successful: path=%s, entries=%d, session=%s",
            path,
            len(entries),
            session_id[:8],
        )
    except ValueError as exc:
        log.error(
            "FTP list directory failed (session not found): path=%s, session=%s",
            path,
            session_id[:8],
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error(
            "FTP list directory failed: path=%s, error=%s, session=%s",
            path,
            exc,
            session_id[:8],
        )
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
    
    log.debug(
        "FTP download request: filename=%s, path=%s, session=%s",
        filename,
        remote_path,
        session_id[:8],
    )
    
    try:
        data = await read_file_bytes(session_id, remote_path)
    except ValueError as exc:
        log.error(
            "FTP download failed (session not found): path=%s, session=%s",
            remote_path,
            session_id[:8],
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error(
            "FTP download failed: path=%s, error=%s, session=%s",
            remote_path,
            exc,
            session_id[:8],
        )
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


@router.post("/{session_id}/upload")
async def upload_file(
    session_id: str,
    path: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    _: str = Depends(get_current_user),
):
    """
    Upload a file to the remote server (returns immediately, processes in background).

    ``path`` is the target directory; the remote file will be placed at
    ``{path}/{file.filename}``.
    
    Returns upload_id for status tracking via GET /ftp/{session_id}/upload/{upload_id}
    """
    import uuid
    
    target_dir = unquote(path)
    if target_dir.endswith("/"):
        remote_path = target_dir + (file.filename or "upload")
    else:
        remote_path = target_dir + "/" + (file.filename or "upload")

    upload_id = str(uuid.uuid4())

    log.debug(
        "FTP upload request: filename=%s, target_path=%s, upload_id=%s, session=%s",
        file.filename,
        remote_path,
        upload_id[:8],
        session_id[:8],
    )

    # Read file into memory
    data = await file.read()
    file_size_mb = len(data) / (1024 * 1024)
    log.info(
        "FTP upload file buffered: filename=%s, size=%s bytes (%.2f MB), upload_id=%s, session=%s",
        file.filename,
        len(data),
        file_size_mb,
        upload_id[:8],
        session_id[:8],
    )
    
    # Schedule background upload
    background_tasks.add_task(
        _perform_upload,
        session_id=session_id,
        remote_path=remote_path,
        data=data,
        filename=file.filename or "upload",
        upload_id=upload_id,
    )
    
    # Return immediately with upload_id
    return {
        "upload_id": upload_id,
        "filename": file.filename or "upload",
        "size_bytes": len(data),
        "size_mb": file_size_mb,
        "status": "queued",
    }


@router.get("/{session_id}/upload/{upload_id}")
async def get_upload_status(
    session_id: str,
    upload_id: str,
    _: str = Depends(get_current_user),
):
    """Check status of a background upload."""
    status_info = _upload_status.get(upload_id)
    if not status_info:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id[:8]} not found")
    return status_info


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
    log.debug(
        "FTP delete request: path=%s, is_dir=%s, session=%s",
        body.path,
        body.is_dir,
        session_id[:8],
    )
    
    try:
        await delete_remote(session_id, body.path, body.is_dir)
    except ValueError as exc:
        log.error(
            "FTP delete failed (session not found): path=%s, session=%s",
            body.path,
            session_id[:8],
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error(
            "FTP delete failed: path=%s, error=%s, session=%s",
            body.path,
            exc,
            session_id[:8],
        )
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
    log.debug(
        "FTP rename request: old_path=%s, new_path=%s, session=%s",
        body.old_path,
        body.new_path,
        session_id[:8],
    )
    
    try:
        await rename_remote(session_id, body.old_path, body.new_path)
    except ValueError as exc:
        log.error(
            "FTP rename failed (session not found): old_path=%s, new_path=%s, session=%s",
            body.old_path,
            body.new_path,
            session_id[:8],
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error(
            "FTP rename failed: old_path=%s, new_path=%s, error=%s, session=%s",
            body.old_path,
            body.new_path,
            exc,
            session_id[:8],
        )
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
    log.debug(
        "FTP mkdir request: path=%s, session=%s",
        body.path,
        session_id[:8],
    )
    
    try:
        await mkdir_remote(session_id, body.path)
    except ValueError as exc:
        log.error(
            "FTP mkdir failed (session not found): path=%s, session=%s",
            body.path,
            session_id[:8],
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error(
            "FTP mkdir failed: path=%s, error=%s, session=%s",
            body.path,
            exc,
            session_id[:8],
        )
        raise HTTPException(status_code=500, detail=f"Mkdir failed: {exc}")
