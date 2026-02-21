"""
routers/audit.py — Audit log API

Endpoints
---------
GET  /api/audit/logs     Return paginated audit log entries (newest first)
POST /api/audit/prune    Manually trigger retention pruning
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.audit import AuditLog
from backend.routers.auth import get_current_user
from backend.services.audit import prune_old_entries

log = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    timestamp: str  # ISO-8601 UTC
    username: str
    action: str
    source_ip: str | None
    detail: str | None

    class Config:
        from_attributes = True


class AuditLogPage(BaseModel):
    total: int
    page: int
    page_size: int
    entries: list[AuditLogEntry]


class PruneResult(BaseModel):
    deleted: int
    retention_days: int


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/logs", response_model=AuditLogPage)
async def list_audit_logs(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(50, ge=1, le=500, description="Entries per page"),
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return audit log entries, newest first, with pagination."""
    offset = (page - 1) * page_size

    count_stmt = text("SELECT COUNT(*) FROM audit_logs")
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar_one()

    rows_result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.scalars().all()

    entries = [
        AuditLogEntry(
            id=row.id,
            timestamp=row.timestamp.isoformat(),
            username=row.username,
            action=row.action,
            source_ip=row.source_ip,
            detail=row.detail,
        )
        for row in rows
    ]

    return AuditLogPage(total=total, page=page, page_size=page_size, entries=entries)


@router.post("/prune", response_model=PruneResult)
async def trigger_prune(
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger retention pruning using the configured policy."""
    settings = get_settings()
    deleted = await prune_old_entries(db, settings.audit_retention_days)
    return PruneResult(deleted=deleted, retention_days=settings.audit_retention_days)
