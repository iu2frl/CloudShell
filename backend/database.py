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
    from backend.models import device, auth, audit, folder, user  # noqa: F401
    _ = device, auth, audit, folder, user


def get_engine():
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    return create_async_engine(
        f"sqlite+aiosqlite:///{settings.db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )


engine = get_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# -- Column migrations ---------------------------------------------------------
# Each entry is (table, column, sql_type, default_literal, nullable).
# If the column is missing it is added with the given DEFAULT so that existing
# rows are backfilled automatically (SQLite respects DEFAULT on ADD COLUMN).
_MIGRATIONS: list[tuple[str, str, str, str, bool]] = [
    ("devices", "connection_type", "VARCHAR(4)", "'ssh'", False),
    ("devices", "ssh_host_fingerprint", "VARCHAR(128)", "NULL", True),
    ("devices", "ftps_cert_thumbprint", "VARCHAR(128)", "NULL", True),
    ("devices", "folder_id", "INTEGER", "NULL", True),
    ("devices", "owner_user_id", "INTEGER", "NULL", True),
    ("folders", "owner_user_id", "INTEGER", "NULL", True),
]


async def _run_migrations(conn) -> None:
    """Add any missing columns to existing tables (lightweight ALTER TABLE)."""
    for table, column, col_type, default, nullable in _MIGRATIONS:
        # PRAGMA table_info returns one row per column
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        columns = {row[1] for row in result.fetchall()}
        if column not in columns:
            nullable_sql = "" if nullable else "NOT NULL "
            sql = (
                f"ALTER TABLE {table} "
                f"ADD COLUMN {column} {col_type} {nullable_sql}DEFAULT {default}"
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


async def _ensure_user_ownership_backfill(conn) -> None:
    """Ensure legacy rows receive an owner mapped to the configured admin user."""
    settings = get_settings()
    username = settings.admin_user

    await conn.execute(
        text(
            """
            INSERT INTO users (username, auth_provider, provider_issuer, provider_subject, is_admin, created_at, updated_at)
            VALUES (:username, 'local', NULL, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(username) DO UPDATE SET
                is_admin = 1,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"username": username},
    )

    result = await conn.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": username},
    )
    admin_row = result.fetchone()
    if not admin_row:
        return
    admin_user_id = admin_row[0]

    await conn.execute(
        text(
            "UPDATE devices SET owner_user_id = :owner_user_id WHERE owner_user_id IS NULL"
        ),
        {"owner_user_id": admin_user_id},
    )
    await conn.execute(
        text(
            "UPDATE folders SET owner_user_id = :owner_user_id WHERE owner_user_id IS NULL"
        ),
        {"owner_user_id": admin_user_id},
    )


async def init_db():
    """Create all tables on startup, then run incremental column migrations."""
    _import_models()
    async with engine.begin() as conn:
        # Enable foreign keys for SQLite
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
        await _encrypt_legacy_totp_secrets(conn)
        await _ensure_user_ownership_backfill(conn)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
