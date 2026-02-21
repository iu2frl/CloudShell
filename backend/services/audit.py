"""
services/audit.py — Helpers for writing and querying audit log entries.

Action constants follow the naming convention:
  LOGIN, LOGOUT, PASSWORD_CHANGED, SESSION_STARTED, SESSION_ENDED
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit import AuditLog

log = logging.getLogger(__name__)

# ── Action constants ──────────────────────────────────────────────────────────

ACTION_LOGIN = "LOGIN"
ACTION_LOGOUT = "LOGOUT"
ACTION_PASSWORD_CHANGED = "PASSWORD_CHANGED"
ACTION_SESSION_STARTED = "SESSION_STARTED"
ACTION_SESSION_ENDED = "SESSION_ENDED"


# ── Write helpers ─────────────────────────────────────────────────────────────

async def write_audit(
    db: AsyncSession,
    username: str,
    action: str,
    detail: str | None = None,
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
            timestamp=datetime.now(timezone.utc),
        )
        db.add(entry)
        await db.commit()
        log.debug("Audit: user=%s action=%s detail=%s", username, action, detail)
    except Exception:  # noqa: BLE001
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
