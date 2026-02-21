from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.device import AuthType, ConnectionType, Device
from backend.routers.auth import get_current_user
from backend.services.crypto import (
    delete_key_file,
    encrypt,
    save_encrypted_key,
)

router = APIRouter(prefix="/devices", tags=["devices"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class DeviceCreate(BaseModel):
    name: str
    hostname: str
    port: int = 22
    username: str
    auth_type: AuthType
    connection_type: ConnectionType = ConnectionType.ssh
    password: Optional[str] = None
    private_key: Optional[str] = None  # PEM string


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    auth_type: Optional[AuthType] = None
    connection_type: Optional[ConnectionType] = None
    password: Optional[str] = None
    private_key: Optional[str] = None


class DeviceOut(BaseModel):
    id: int
    name: str
    hostname: str
    port: int
    username: str
    auth_type: AuthType
    connection_type: ConnectionType
    key_filename: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _store_key(device_id: int, pem: str, keys_dir: str) -> str:
    """Encrypt and save a PEM key; returns the stored filename."""
    return save_encrypted_key(device_id, pem, keys_dir)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    result = await db.execute(select(Device).order_by(Device.name))
    return result.scalars().all()


@router.post("/", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from backend.config import get_settings
    settings = get_settings()

    device = Device(
        name=payload.name,
        hostname=payload.hostname,
        port=payload.port,
        username=payload.username,
        auth_type=payload.auth_type,
        connection_type=payload.connection_type,
    )
    if payload.auth_type == AuthType.password:
        if not payload.password:
            raise HTTPException(status_code=400, detail="password required")
        device.encrypted_password = encrypt(payload.password)
    else:
        if not payload.private_key:
            raise HTTPException(status_code=400, detail="private_key required")
        # Save key after we have an id — flush first to get id
        db.add(device)
        await db.flush()
        device.key_filename = _store_key(device.id, payload.private_key, settings.keys_dir)

    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.put("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from backend.config import get_settings
    settings = get_settings()

    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    for field in ("name", "hostname", "port", "username", "auth_type", "connection_type"):
        val = getattr(payload, field)
        if val is not None:
            setattr(device, field, val)

    if payload.password is not None:
        device.encrypted_password = encrypt(payload.password)
    if payload.private_key is not None:
        device.key_filename = _store_key(device.id, payload.private_key, settings.keys_dir)

    device.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from backend.config import get_settings
    settings = get_settings()

    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Remove encrypted key file from disk before deleting the DB record
    if device.key_filename:
        delete_key_file(device.key_filename, settings.keys_dir)

    await db.delete(device)
    await db.commit()
