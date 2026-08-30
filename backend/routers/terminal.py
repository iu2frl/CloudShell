import logging
import tempfile
import os
import secrets
import asyncio
from datetime import datetime, timedelta, timezone

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import AsyncSessionLocal, get_db
from backend.models.device import AuthType, Device
from backend.routers.auth import get_current_user, get_owner_user_id
from backend.services.audit import (
    ACTION_SESSION_ENDED,
    ACTION_SESSION_STARTED,
    get_client_ip,
    write_audit,
)
from backend.services.crypto import decrypt, load_decrypted_key
from backend.services.ssh import (
    SSHHostFingerprintMismatchError,
    SSHHostFingerprintUnavailableError,
    _ws_error,
    close_session,
    create_session,
    get_session_meta,
    probe_ssh_host_fingerprint,
    stream_session,
)
from sqlalchemy import select

log = logging.getLogger(__name__)
router = APIRouter(prefix="/terminal", tags=["terminal"])

_WS_TICKET_TTL_SECONDS = 30
_ws_tickets: dict[str, tuple[str, str, datetime]] = {}
_ws_tickets_lock = asyncio.Lock()


async def _issue_ws_ticket(session_id: str, username: str) -> str:
    ticket = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_WS_TICKET_TTL_SECONDS)
    async with _ws_tickets_lock:
        _ws_tickets[ticket] = (session_id, username, expires_at)
    return ticket


async def _consume_ws_ticket(ticket: str, session_id: str) -> str | None:
    now = datetime.now(timezone.utc)
    async with _ws_tickets_lock:
        for key, (_, _, expiry) in list(_ws_tickets.items()):
            if expiry <= now:
                _ws_tickets.pop(key, None)

        payload = _ws_tickets.pop(ticket, None)
        if not payload:
            return None
        ticket_session_id, username, expiry = payload
        if expiry <= now or ticket_session_id != session_id:
            return None
        return username


@router.post("/ws-ticket/{session_id}")
async def create_ws_ticket(
    session_id: str,
    _: Request,
    current_user: str = Depends(get_current_user),
):
    """Issue a short-lived, single-use ticket for terminal WebSocket auth."""
    _, audit_user, _ = get_session_meta(session_id)
    if not audit_user or audit_user != current_user:
        raise HTTPException(status_code=404, detail="Session not found")

    ticket = await _issue_ws_ticket(session_id, current_user)
    return {"ticket": ticket, "expires_in": _WS_TICKET_TTL_SECONDS}


@router.post("/session/{device_id}")
async def open_session(
    device_id: int,
    request: Request,
    trust_host: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Create an SSH session and return a session_id for WebSocket use."""
    settings = get_settings()
    if isinstance(db, AsyncSession):
        owner_user_id = await get_owner_user_id(db, current_user)
        result = await db.execute(
            select(Device)
            .where(Device.id == device_id)
            .where(Device.owner_user_id == owner_user_id)
        )
        device: Device | None = result.scalar_one_or_none()
    else:
        device = await db.get(Device, device_id)
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

    client_ip = get_client_ip(request)
    device_label = f"{device.name} ({device.hostname}:{device.port})"

    try:
        presented_fingerprint = await probe_ssh_host_fingerprint(
            device.hostname,
            device.port,
            username=device.username,
            password=password,
            private_key_path=key_path,
        )
    except SSHHostFingerprintUnavailableError as exc:
        raise HTTPException(status_code=502, detail=f"SSH host fingerprint unavailable: {exc}") from exc

    pinned_fingerprint = device.ssh_host_fingerprint
    if pinned_fingerprint is None:
        if not trust_host:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SSH_HOST_UNTRUSTED",
                    "fingerprint": presented_fingerprint,
                },
            )
        device.ssh_host_fingerprint = presented_fingerprint
        await db.commit()
    elif pinned_fingerprint != presented_fingerprint:
        if not trust_host:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SSH_HOST_CHANGED",
                    "fingerprint": presented_fingerprint,
                    "previous_fingerprint": pinned_fingerprint,
                },
            )
        device.ssh_host_fingerprint = presented_fingerprint
        await db.commit()

    try:
        session_id = await create_session(
            hostname=device.hostname,
            port=device.port,
            username=device.username,
            password=password,
            private_key_path=key_path,
            known_hosts="auto",
            device_label=device_label,
            cloudshell_user=current_user,
            source_ip=client_ip,
            expected_ssh_host_fingerprint=device.ssh_host_fingerprint,
        )
    except asyncssh.PermissionDenied:
        raise HTTPException(status_code=502, detail="SSH authentication failed")
    except asyncssh.ConnectionLost:
        raise HTTPException(status_code=504, detail="SSH connection lost")
    except asyncssh.HostKeyNotVerifiable as exc:
        raise HTTPException(status_code=502, detail=f"Host key not verifiable: {exc}")
    except SSHHostFingerprintMismatchError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SSH_HOST_CHANGED",
                "fingerprint": exc.presented,
                "previous_fingerprint": exc.expected,
            },
        ) from exc
    except (OSError, asyncssh.Error) as exc:
        raise HTTPException(status_code=502, detail=f"SSH connection failed: {exc}")
    finally:
        # Always remove the temp key file — whether connect succeeded or failed
        if _tmp_key_file:
            try:
                os.unlink(_tmp_key_file)
            except OSError:
                pass

    detail = f"Started session with {device_label}"
    await write_audit(
        db, current_user, ACTION_SESSION_STARTED,
        detail=detail,
        source_ip=client_ip,
    )

    return {"session_id": session_id}


@router.websocket("/ws/{session_id}")
async def terminal_ws(session_id: str, websocket: WebSocket):
    """WebSocket endpoint — bridges browser ↔ SSH session. Frames are binary."""
    ticket = websocket.query_params.get("ticket")

    username = "unknown"
    source_ip: str | None = None

    if not ticket:
        await websocket.close(code=4001)
        return

    consumed_username = await _consume_ws_ticket(ticket, session_id)
    if not consumed_username:
        await websocket.close(code=4001)
        return

    username = consumed_username
    source_ip = get_client_ip(websocket)  # type: ignore[arg-type]

    await websocket.accept()
    try:
        await stream_session(session_id, websocket)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.error("Unexpected error in terminal WS %s: %s", session_id[:8], exc)
        await _ws_error(websocket, str(exc))
    finally:
        # Read stored metadata BEFORE close_session removes the entry
        device_label, audit_user, audit_ip = get_session_meta(session_id)
        # Fall back to token-decoded username if metadata is missing
        if not audit_user:
            audit_user = username
        if not audit_ip:
            audit_ip = source_ip
        await close_session(session_id)
        log.info("Logging SESSION_ENDED for user=%s session=%s", audit_user, session_id[:8])
        async with AsyncSessionLocal() as db:
            await write_audit(
                db,
                audit_user,
                ACTION_SESSION_ENDED,
                detail=f"Ended session with {device_label}" if device_label else f"Ended session (id={session_id[:8]})",
                source_ip=audit_ip,
            )
