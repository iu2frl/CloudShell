from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Folder(Base):
    """Represents a device organization folder with support for hierarchical nesting."""

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_folder_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("folders.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Self-referential relationship for hierarchical structure
    children: Mapped[list["Folder"]] = relationship(
        "Folder",
        remote_side=[id],
        back_populates="parent",
        foreign_keys=[parent_folder_id],
    )
    parent: Mapped["Folder | None"] = relationship(
        "Folder",
        remote_side=[parent_folder_id],
        back_populates="children",
    )

    # Relationship with devices
    devices: Mapped[list["Device"]] = relationship(
        "Device",
        back_populates="folder",
        cascade="all, delete-orphan",
    )
