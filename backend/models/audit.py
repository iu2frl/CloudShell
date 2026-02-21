"""
models/audit.py — Audit log entries stored in SQLite.

Each row records a single user action with a UTC timestamp, the username,
the action performed, the originating IP address, and optional detail
(e.g. target device / hostname).
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AuditLog(Base):
    """Immutable audit log entry."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
