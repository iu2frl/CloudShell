import logging
import os
import binascii
from collections.abc import AsyncGenerator
from cryptography.exceptions import InvalidTag
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings
from backend.services.crypto import decrypt_versioned, encrypt_versioned, current_secret_version

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# Import all models here so SQLAlchemy knows about them before create_all()
def _import_models():
    from backend.models import device, auth, audit  # noqa: F401
    _ = device, auth, audit


def get_engine():
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    return create_async_engine(
        f"sqlite+aiosqlite:///{settings.db_path}",
        echo=False,
    )


engine = get_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# -- Column migrations ---------------------------------------------------------
# Each entry is (table, column, sql_type, default_literal).
# If the column is missing it is added with the given DEFAULT so that existing
# rows are backfilled automatically (SQLite respects DEFAULT on ADD COLUMN).
_MIGRATIONS: list[tuple[str, str, str, str]] = [
    ("devices", "connection_type", "VARCHAR(4)", "'ssh'"),
]


async def _run_migrations(conn) -> None:
    """Add any missing columns to existing tables (lightweight ALTER TABLE)."""
    for table, column, col_type, default in _MIGRATIONS:
        # PRAGMA table_info returns one row per column
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        columns = {row[1] for row in result.fetchall()}
        if column not in columns:
            sql = (
                f"ALTER TABLE {table} "
                f"ADD COLUMN {column} {col_type} NOT NULL DEFAULT {default}"
            )
            await conn.execute(text(sql))
            log.info("Migration: added column %s.%s (default=%s)", table, column, default)


async def _encrypt_legacy_totp_secrets(conn) -> None:
    """Normalize TOTP secrets to current versioned encrypted format."""
    result = await conn.execute(text("SELECT username, secret FROM admin_totp_secrets"))
    rows = result.fetchall()
    migrated_count = 0
    target_version = current_secret_version()

    for username, secret in rows:
        if not isinstance(secret, str) or not secret:
            continue

        try:
            plaintext, version = decrypt_versioned(secret)
            if version == target_version:
                continue
            normalized_secret = encrypt_versioned(plaintext, version=target_version)
        except (ValueError, TypeError, binascii.Error, InvalidTag):
            normalized_secret = encrypt_versioned(secret, version=target_version)

        await conn.execute(
            text(
                "UPDATE admin_totp_secrets "
                "SET secret = :secret "
                "WHERE username = :username"
            ),
            {"secret": normalized_secret, "username": username},
        )
        migrated_count += 1

    if migrated_count:
        log.info("Migration: normalized %s TOTP secrets to versioned encryption", migrated_count)


async def init_db():
    """Create all tables on startup, then run incremental column migrations."""
    _import_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
        await _encrypt_legacy_totp_secrets(conn)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
