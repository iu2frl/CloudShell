"""
tests/test_database_migration.py — tests for the incremental column migration
in database.py::_run_migrations.

Covers:
- Legacy database (no connection_type column): migration adds the column and
  existing rows default to 'ssh'.
- Fresh database (column already present): migration is a no-op.
- Multiple calls are idempotent.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database import _run_migrations, _MIGRATIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _make_engine():
    """Return an in-memory async SQLite engine."""
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_adds_missing_column():
    """
    On a legacy database that has a 'devices' table without 'connection_type',
    _run_migrations adds the column and existing rows get the default value 'ssh'.
    """
    engine = await _make_engine()
    async with engine.begin() as conn:
        # Simulate a pre-migration devices table (no connection_type)
        await conn.execute(text(
            "CREATE TABLE devices ("
            "  id INTEGER PRIMARY KEY,"
            "  name VARCHAR(128) NOT NULL,"
            "  hostname VARCHAR(253) NOT NULL,"
            "  port INTEGER,"
            "  username VARCHAR(128) NOT NULL,"
            "  auth_type VARCHAR(8) NOT NULL,"
            "  encrypted_password VARCHAR(512),"
            "  key_filename VARCHAR(256),"
            "  created_at DATETIME,"
            "  updated_at DATETIME"
            ")"
        ))
        # Insert a legacy row
        await conn.execute(text(
            "INSERT INTO devices (id, name, hostname, port, username, auth_type) "
            "VALUES (1, 'old-server', '10.0.0.1', 22, 'root', 'password')"
        ))

        # Run the migration
        await _run_migrations(conn)

        # Column must now exist
        result = await conn.execute(text("PRAGMA table_info(devices)"))
        col_names = {row[1] for row in result.fetchall()}
        assert "connection_type" in col_names

        # Existing row must have been backfilled with 'ssh'
        row = await conn.execute(
            text("SELECT connection_type FROM devices WHERE id = 1")
        )
        value = row.scalar()
        assert value == "ssh", f"Expected 'ssh', got {value!r}"

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_noop_when_column_exists():
    """
    When 'connection_type' already exists, _run_migrations must not raise and
    must not change existing values.
    """
    engine = await _make_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE devices ("
            "  id INTEGER PRIMARY KEY,"
            "  name VARCHAR(128) NOT NULL,"
            "  hostname VARCHAR(253) NOT NULL,"
            "  port INTEGER,"
            "  username VARCHAR(128) NOT NULL,"
            "  auth_type VARCHAR(8) NOT NULL,"
            "  connection_type VARCHAR(4) NOT NULL DEFAULT 'ssh',"
            "  encrypted_password VARCHAR(512),"
            "  key_filename VARCHAR(256),"
            "  created_at DATETIME,"
            "  updated_at DATETIME"
            ")"
        ))
        await conn.execute(text(
            "INSERT INTO devices (id, name, hostname, port, username, auth_type, connection_type) "
            "VALUES (1, 'new-server', '10.0.0.2', 22, 'admin', 'password', 'sftp')"
        ))

        # Should be a no-op — must not raise, must not overwrite 'sftp'
        await _run_migrations(conn)

        row = await conn.execute(
            text("SELECT connection_type FROM devices WHERE id = 1")
        )
        value = row.scalar()
        assert value == "sftp", f"Expected 'sftp' to be unchanged, got {value!r}"

    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_idempotent():
    """Calling _run_migrations twice on the same connection must not raise."""
    engine = await _make_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE devices ("
            "  id INTEGER PRIMARY KEY,"
            "  name VARCHAR(128) NOT NULL,"
            "  hostname VARCHAR(253) NOT NULL,"
            "  port INTEGER,"
            "  username VARCHAR(128) NOT NULL,"
            "  auth_type VARCHAR(8) NOT NULL"
            ")"
        ))

        # First call adds the column; second call must be a no-op
        await _run_migrations(conn)
        await _run_migrations(conn)

        result = await conn.execute(text("PRAGMA table_info(devices)"))
        col_names = {row[1] for row in result.fetchall()}
        assert "connection_type" in col_names

    await engine.dispose()


@pytest.mark.asyncio
async def test_migrations_table_covers_all_entries():
    """
    Every entry in _MIGRATIONS references a real column name and a non-empty
    default — a basic sanity guard against typos.
    """
    for table, column, col_type, default in _MIGRATIONS:
        assert table, "table name must not be empty"
        assert column, "column name must not be empty"
        assert col_type, "col_type must not be empty"
        assert default, "default must not be empty"
