"""
models/auth.py — persistence for auth-related state:
  - RevokedToken: JWT deny-list (jti → expiry)
  - AdminCredential: hashed admin password stored in DB
  - AdminTOTPSecret: TOTP secrets for two-factor authentication
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Boolean
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


class AdminTOTPSecret(Base):
    """
    Stores TOTP secrets for two-factor authentication.

    - `username`: primary key (matches AdminCredential username)
    - `secret`: base32-encoded TOTP secret
    - `is_enabled`: whether 2FA is currently active
    - `backup_codes`: JSON list of backup codes (hashed)
    - `created_at`: when 2FA was first set up
    """
    __tablename__ = "admin_totp_secrets"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    secret: Mapped[str] = mapped_column(String(32), nullable=False)  # base32-encoded
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    backup_codes: Mapped[str] = mapped_column(String(512), nullable=True)  # JSON list
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
