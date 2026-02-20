import logging
import os

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.device import AuthType, Device
from backend.routers.auth import get_current_user
from backend.services.crypto import decrypt
from backend.services.ssh import _ws_error, close_session, create_session, stream_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/terminal", tags=["terminal"])


@router.post("/session/{device_id}")
async def open_session(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Create an SSH session and return a session_id for WebSocket use."""
    settings = get_settings()
    device: Device | None = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    password = None
    key_path = None

    if device.auth_type == AuthType.password:
        if device.encrypted_password:
            password = decrypt(device.encrypted_password)
    else:
        if device.key_filename:
            key_path = os.path.join(settings.keys_dir, device.key_filename)

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

    return {"session_id": session_id}


@router.websocket("/ws/{session_id}")
async def terminal_ws(session_id: str, websocket: WebSocket):
    """WebSocket endpoint — bridges browser ↔ SSH session. Frames are binary."""
    from jose import JWTError, jwt as jose_jwt

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return
    try:
        settings = get_settings()
        jose_jwt.decode(token, settings.secret_key, algorithms=["HS256"])
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
