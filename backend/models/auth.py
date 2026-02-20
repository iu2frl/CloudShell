"""
models/auth.py — persistence for auth-related state:
  - RevokedToken: JWT deny-list (jti → expiry)
  - AdminCredential: hashed admin password stored in DB
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class RevokedToken(Base):
    """
    Stores revoked JWT IDs (jti).  Rows whose `expires_at` has passed
    can be pruned safely — an expired token is invalid regardless.
    """
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AdminCredential(Base):
    """
    Single-row table.  Stores the bcrypt hash of the admin password so it
    can be changed at runtime without restarting the container.

    `username` is the primary key (supports future multi-admin, but today
    there is always exactly one row matching settings.admin_user).
    """
    __tablename__ = "admin_credentials"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
