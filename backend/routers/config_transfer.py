"""
routers/config_transfer.py — configuration export / import endpoints.

Export: GET /api/config/export
    Returns a JSON file containing all devices with their secrets decrypted
    in plaintext.  The file is intended for transfer between CloudShell
    instances and must be treated as sensitive — it contains all credentials.

Import: POST /api/config/import
    Accepts the same JSON format produced by the export endpoint.  Each
    device is re-encrypted with the target instance's SECRET_KEY and upserted
    (matched by hostname + port + username; inserted if no match is found).

Both endpoints require a valid JWT (admin only).
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.device import AuthType, ConnectionType, Device
from backend.routers.auth import get_current_user, get_owner_user_id
from backend.services.crypto import (
    decrypt,
    encrypt,
    load_decrypted_key,
    save_encrypted_key,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])

# -- Schemas -------------------------------------------------------------------

EXPORT_FORMAT_VERSION = 1


class ExportedDevice(BaseModel):
    """A single device entry inside an export bundle — credentials in plaintext."""

    name: str
    hostname: str
    port: int
    username: str
    auth_type: AuthType
    connection_type: ConnectionType
    password: Optional[str] = None
    private_key: Optional[str] = None  # PEM string


class ExportBundle(BaseModel):
    """Top-level export document."""

    format_version: int = EXPORT_FORMAT_VERSION
    exported_at: str
    device_count: int
    devices: list[ExportedDevice]


class ImportResult(BaseModel):
    """Summary returned after a successful import."""

    imported: int
    skipped: int
    errors: int
    messages: list[str]


# -- Helpers -------------------------------------------------------------------

async def _build_export_bundle(
    db: AsyncSession,
    keys_dir: str,
    owner_user_id: int | None = None,
) -> ExportBundle:
    """Read all devices from the DB and decrypt their secrets."""
    stmt = select(Device).order_by(Device.name)
    if owner_user_id is not None:
        stmt = stmt.where(Device.owner_user_id == owner_user_id)
    result = await db.execute(stmt)
    devices = result.scalars().all()

    exported: list[ExportedDevice] = []
    for dev in devices:
        password: Optional[str] = None
        private_key: Optional[str] = None

        try:
            if dev.auth_type == AuthType.password and dev.encrypted_password:
                password = decrypt(dev.encrypted_password)
            elif dev.auth_type == AuthType.key and dev.key_filename:
                private_key = load_decrypted_key(dev.key_filename, keys_dir)
        except Exception:
            log.exception(
                "Failed to decrypt credentials for device %s (%s) — omitting secrets",
                dev.id,
                dev.name,
            )

        exported.append(
            ExportedDevice(
                name=dev.name,
                hostname=dev.hostname,
                port=dev.port,
                username=dev.username,
                auth_type=dev.auth_type,
                connection_type=dev.connection_type,
                password=password,
                private_key=private_key,
            )
        )

    return ExportBundle(
        format_version=EXPORT_FORMAT_VERSION,
        exported_at=datetime.now(timezone.utc).isoformat(),
        device_count=len(exported),
        devices=exported,
    )


# -- Routes --------------------------------------------------------------------

@router.get("/export")
async def export_config(
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
) -> Response:
    """
    Export all device configurations as a downloadable JSON file.

    The returned file contains plaintext credentials and must be kept secure.
    """
    settings = get_settings()
    owner_user_id = await get_owner_user_id(db, current_user)
    return await _build_export_response(db, settings.keys_dir, owner_user_id)


@router.post("/import", response_model=ImportResult)
async def import_config(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
) -> ImportResult:
    """
    Import device configurations from a previously exported JSON file.

    Devices are matched by (name, hostname, port, username, connection_type).
    Existing matches are skipped; new devices are inserted with re-encrypted
    credentials.

    The file must be a valid export bundle produced by GET /api/config/export.
    """
    settings = get_settings()

    # -- Parse uploaded JSON ---------------------------------------------------
    try:
        raw = await file.read()
        data = json.loads(raw)
        bundle = ExportBundle.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid export file: {exc}",
        ) from exc

    if bundle.format_version != EXPORT_FORMAT_VERSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported export format version {bundle.format_version}. "
                f"Expected {EXPORT_FORMAT_VERSION}."
            ),
        )

    owner_user_id = await get_owner_user_id(db, current_user)
    return await _process_import_bundle(db, bundle, settings.keys_dir, owner_user_id)


# -- Internal helpers (extracted for testability / coverage) -------------------

async def _build_export_response(
    db: AsyncSession,
    keys_dir: str,
    owner_user_id: int | None = None,
) -> Response:
    """Build the JSON export Response object from the current DB state."""
    bundle = await _build_export_bundle(db, keys_dir, owner_user_id)
    log.info("Config export: %d device(s) exported", bundle.device_count)
    content = bundle.model_dump_json(indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="cloudshell-config.json"',
        },
    )


async def _process_import_bundle(
    db: AsyncSession,
    bundle: ExportBundle,
    keys_dir: str,
    owner_user_id: int | None = None,
) -> ImportResult:
    """
    Persist devices from an already-validated ExportBundle.

    Each device is inserted inside its own savepoint so a single failure does
    not roll back previously-imported entries.
    """
    # -- Fetch existing devices to detect duplicates ---------------------------
    stmt = select(Device)
    if owner_user_id is not None:
        stmt = stmt.where(Device.owner_user_id == owner_user_id)
    result = await db.execute(stmt)
    existing = result.scalars().all()
    # Key: (name, hostname, port, username, connection_type) → device id
    existing_keys: dict[tuple[str, str, int, str, str], int] = {
        (d.name, d.hostname, d.port, d.username, d.connection_type): d.id for d in existing
    }

    imported = 0
    skipped = 0
    errors = 0
    messages: list[str] = []

    for entry in bundle.devices:
        match_key = (entry.name, entry.hostname, entry.port, entry.username, entry.connection_type)
        if match_key in existing_keys:
            msg = (
                f"Skipped '{entry.name}' ({entry.hostname}:{entry.port}) — "
                "already exists (matched by name/hostname/port/username/connection_type)"
            )
            messages.append(msg)
            log.debug("Import: %s", msg)
            skipped += 1
            continue

        try:
            # Use a savepoint so a failure here only rolls back this one device,
            # leaving previously-flushed devices in the session unaffected.
            async with db.begin_nested():
                device = Device(
                    name=entry.name,
                    hostname=entry.hostname,
                    port=entry.port,
                    username=entry.username,
                    auth_type=entry.auth_type,
                    connection_type=entry.connection_type,
                    owner_user_id=owner_user_id,
                )

                if entry.auth_type == AuthType.password:
                    if not entry.password:
                        raise ValueError("password auth_type requires a password")
                    device.encrypted_password = encrypt(entry.password)
                else:
                    if not entry.private_key:
                        raise ValueError("key auth_type requires a private_key")
                    # Flush to get a DB-assigned id before writing the key file
                    db.add(device)
                    await db.flush()
                    device.key_filename = save_encrypted_key(
                        device.id, entry.private_key, keys_dir
                    )

                db.add(device)
                await db.flush()

            imported += 1
            log.info("Import: added device '%s' (%s:%s)", entry.name, entry.hostname, entry.port)

        except Exception as exc:
            errors += 1
            msg = f"Error importing '{entry.name}': {exc}"
            messages.append(msg)
            log.exception("Import: failed for device '%s'", entry.name)
            continue

    await db.commit()

    log.info(
        "Config import complete: imported=%d skipped=%d errors=%d",
        imported,
        skipped,
        errors,
    )

    return ImportResult(
        imported=imported,
        skipped=skipped,
        errors=errors,
        messages=messages,
    )
