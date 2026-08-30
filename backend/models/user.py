"""User identity records used for ownership scoping."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class User(Base):
    """Represents a CloudShell user identity."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_provider", "provider_issuer", "provider_subject", name="uq_users_provider_subject"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    provider_issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )