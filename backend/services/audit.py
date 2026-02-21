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

log = logging.getLogger(__name__)

# ── Action constants ──────────────────────────────────────────────────────────

ACTION_LOGIN = "LOGIN"
ACTION_LOGOUT = "LOGOUT"
ACTION_PASSWORD_CHANGED = "PASSWORD_CHANGED"
ACTION_SESSION_STARTED = "SESSION_STARTED"
ACTION_SESSION_ENDED = "SESSION_ENDED"


# ── IP extraction ─────────────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str | None:
    """Return the real client IP, honouring proxy headers.

    Priority (highest first):
      1. X-Forwarded-For  — leftmost entry is the original client when set by
                            a trusted proxy chain (Nginx, Traefik, Caddy, etc.)
      2. X-Real-IP        — single-value header set by some proxies
      3. request.client   — direct TCP peer (the immediate caller)

    The value is truncated to 45 characters to fit both IPv4 and IPv6 addresses
    (including IPv4-mapped IPv6 like ::ffff:1.2.3.4).
    """
    xff: str | None = request.headers.get("x-forwarded-for")
    if xff:
        # "client, proxy1, proxy2" — take the leftmost (original client)
        ip = xff.split(",")[0].strip()
        return ip[:45] if ip else None

    xri: str | None = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:45]

    if request.client:
        return request.client.host[:45]

    return None


# ── Write helpers ─────────────────────────────────────────────────────────────

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
