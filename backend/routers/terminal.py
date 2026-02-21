import logging
import tempfile
import os

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.device import AuthType, Device
from backend.routers.auth import get_current_user
from backend.services.audit import (
    ACTION_SESSION_ENDED,
    ACTION_SESSION_STARTED,
    write_audit,
)
from backend.services.crypto import decrypt, load_decrypted_key
from backend.services.ssh import _ws_error, close_session, create_session, stream_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/terminal", tags=["terminal"])


@router.post("/session/{device_id}")
async def open_session(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Create an SSH session and return a session_id for WebSocket use."""
    settings = get_settings()
    device: Device | None = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    password = None
    key_path = None
    _tmp_key_file = None  # track temp file for cleanup on error

    if device.auth_type == AuthType.password:
        if device.encrypted_password:
            password = decrypt(device.encrypted_password)
    else:
        if device.key_filename:
            # Decrypt the PEM and write to a secure temp file for asyncssh
            pem = load_decrypted_key(device.key_filename, settings.keys_dir)
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".pem", delete=False, dir="/tmp"
            )
            tmp.write(pem)
            tmp.flush()
            tmp.close()
            os.chmod(tmp.name, 0o600)
            key_path = tmp.name
            _tmp_key_file = tmp.name

    try:
        session_id = await create_session(
            hostname=device.hostname,
            port=device.port,
            username=device.username,
            password=password,
            private_key_path=key_path,
            known_hosts="auto",
        )
    except asyncssh.PermissionDenied:
        raise HTTPException(status_code=401, detail="SSH authentication failed")
    except asyncssh.ConnectionLost:
        raise HTTPException(status_code=504, detail="SSH connection lost")
    except asyncssh.HostKeyNotVerifiable as exc:
        raise HTTPException(status_code=502, detail=f"Host key not verifiable: {exc}")
    except (OSError, asyncssh.Error) as exc:
        raise HTTPException(status_code=502, detail=f"SSH connection failed: {exc}")
    finally:
        # Always remove the temp key file — whether connect succeeded or failed
        if _tmp_key_file:
            try:
                os.unlink(_tmp_key_file)
            except OSError:
                pass

    detail = f"Started session with {device.name} ({device.hostname}:{device.port})"
    await write_audit(db, current_user, ACTION_SESSION_STARTED, detail)

    return {"session_id": session_id}


@router.websocket("/ws/{session_id}")
async def terminal_ws(session_id: str, websocket: WebSocket):
    """WebSocket endpoint — bridges browser ↔ SSH session. Frames are binary."""
    from jose import JWTError, jwt as jose_jwt

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    username = "unknown"
    try:
        settings = get_settings()
        payload = jose_jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username = payload.get("sub", "unknown")
    except JWTError:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    try:
        await stream_session(session_id, websocket)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.error("Unexpected error in terminal WS %s: %s", session_id[:8], exc)
        await _ws_error(websocket, str(exc))
    finally:
        await close_session(session_id)
        from backend.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await write_audit(
                db,
                username,
                ACTION_SESSION_ENDED,
                f"Ended session (session_id={session_id[:8]})",
            )
