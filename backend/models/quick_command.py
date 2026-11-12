from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class QuickCommand(Base):
    """Quick commands configured per-user per-device, stored as JSON."""

    __tablename__ = "quick_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON array of {id, label, command} objects (max 8, labels ≤24 chars, commands ≤160 chars)
    commands_json: Mapped[str] = mapped_column(String(4096), nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
