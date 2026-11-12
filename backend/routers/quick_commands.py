"""
routers/quick_commands.py — per-user, per-device quick commands endpoint.

GET  /api/quick_commands/{device_id}   Returns the stored quick-command JSON array.
PUT  /api/quick_commands/{device_id}   Upserts the quick-command JSON array for the caller's device.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.quick_command import QuickCommand
from backend.routers.auth import get_current_user, get_owner_user_id

log = logging.getLogger(__name__)

router = APIRouter(prefix="/quick_commands", tags=["quick_commands"])


# -- Schemas -------------------------------------------------------------------

class CommandsPayload(BaseModel):
    """Array of {id, label, command} objects as returned/stored in the DB."""

    commands: list[dict]


# -- Routes --------------------------------------------------------------------

@router.get("/{device_id}")
async def get_quick_commands(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """Return the quick-commands JSON array for the authenticated user's device."""
    owner_user_id = await get_owner_user_id(db, _)
    result = await db.execute(
        select(QuickCommand)
        .where(QuickCommand.device_id == device_id)
        .where(QuickCommand.owner_user_id == owner_user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {"commands": []}
    try:
        commands = json.loads(row.commands_json)
    except Exception:
        commands = []
    return {"commands": commands}


@router.put("/{device_id}")
async def save_quick_commands(
    device_id: int,
    payload: CommandsPayload,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    """Upsert the quick-commands JSON array for the authenticated user's device."""
    owner_user_id = await get_owner_user_id(db, _)

    # Verify the device belongs to this user before saving
    from backend.models.device import Device
    result = await db.execute(
        select(Device).where(Device.id == device_id).where(Device.owner_user_id == owner_user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Device not found")

    commands_json = json.dumps(payload.commands, ensure_ascii=False)

    result = await db.execute(
        select(QuickCommand)
        .where(QuickCommand.device_id == device_id)
        .where(QuickCommand.owner_user_id == owner_user_id)
    )
    row = result.scalar_one_or_none()

    if row:
        row.commands_json = commands_json
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = QuickCommand(
            owner_user_id=owner_user_id,
            device_id=device_id,
            commands_json=commands_json,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return {"commands": payload.commands}
