"""
services/audit.py — Helpers for writing and querying audit log entries.

Action constants follow the naming convention:
  LOGIN, LOGOUT, PASSWORD_CHANGED, SESSION_STARTED, SESSION_ENDED
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit import AuditLog
from backend.services.rate_limit import _get_client_ip

log = logging.getLogger(__name__)

# -- Action constants ----------------------------------------------------------

ACTION_LOGIN = "LOGIN"
ACTION_LOGOUT = "LOGOUT"
ACTION_PASSWORD_CHANGED = "PASSWORD_CHANGED"
ACTION_SESSION_STARTED = "SESSION_STARTED"
ACTION_SESSION_ENDED = "SESSION_ENDED"
ACTION_2FA_SETUP_INITIATED = "2FA_SETUP_INITIATED"
ACTION_2FA_SETUP_RESET = "2FA_SETUP_RESET"
ACTION_2FA_ENABLED = "2FA_ENABLED"
ACTION_2FA_DISABLED = "2FA_DISABLED"
ACTION_2FA_VERIFICATION_FAILED = "2FA_VERIFICATION_FAILED"
ACTION_2FA_FAILED = "2FA_FAILED"
ACTION_BACKUP_CODE_USED = "BACKUP_CODE_USED"
ACTION_BACKUP_CODE_LOW = "BACKUP_CODE_LOW"


# -- IP extraction -------------------------------------------------------------

def get_client_ip(request: Request) -> str | None:
    """Return client IP using the same trusted-proxy rules as rate limiting.

    Forwarded headers are honoured only when the direct peer is configured in
    ``TRUSTED_PROXIES``; otherwise, the direct peer address is used.
    """
    ip = _get_client_ip(request)
    if ip == "unknown":
        return None
    return ip[:45]


# -- Write helpers -------------------------------------------------------------

async def write_audit(
    db: AsyncSession,
    username: str,
    action: str,
    detail: str | None = None,
    source_ip: str | None = None,
) -> None:
    """Insert a new audit log entry and commit immediately.

    Errors are logged but never propagated — audit logging must not break
    normal application flow.
    """
    try:
        entry = AuditLog(
            username=username,
            action=action,
            detail=detail,
            source_ip=source_ip,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(entry)
        await db.commit()
        log.debug(
            "Audit: user=%s action=%s ip=%s detail=%s",
            username, action, source_ip, detail,
        )
    except (OSError, ValueError, RuntimeError):  # pylint: disable=broad-except
        log.exception("Failed to write audit log entry (user=%s, action=%s)", username, action)


async def prune_old_entries(db: AsyncSession, retention_days: int) -> int:
    """Delete audit entries older than *retention_days* days.

    Returns the number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(
        delete(AuditLog).where(AuditLog.timestamp < cutoff)
    )
    await db.commit()
    deleted: int = result.rowcount  # type: ignore[assignment]
    if deleted:
        log.info("Pruned %d audit log entries older than %d days", deleted, retention_days)
    return deleted
