import enum
from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AuthType(str, enum.Enum):
    password = "password"
    key = "key"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_type: Mapped[AuthType] = mapped_column(SAEnum(AuthType), nullable=False)
    # AES-256-GCM encrypted, base64-encoded
    encrypted_password: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # filename inside keys_dir
    key_filename: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
