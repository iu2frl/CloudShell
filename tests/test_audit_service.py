"""
tests/test_audit_service.py — unit tests for services/audit.py

Tests cover:
- write_audit persists all fields correctly
- write_audit with source_ip stores the IP
- write_audit does not raise on DB failure (fire-and-forget contract)
- prune_old_entries removes only entries older than the cutoff
- prune_old_entries returns the correct deleted count
- get_client_ip extracts IP from X-Forwarded-For (proxy chain)
- get_client_ip extracts IP from X-Real-IP
- get_client_ip falls back to request.client.host
- get_client_ip returns None when no IP information is available
- get_client_ip takes the leftmost entry from X-Forwarded-For chains
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.models.audit import AuditLog
from backend.services.audit import (
    ACTION_LOGIN,
    ACTION_LOGOUT,
    ACTION_PASSWORD_CHANGED,
    ACTION_SESSION_ENDED,
    ACTION_SESSION_STARTED,
    get_client_ip,
    prune_old_entries,
    write_audit,
)


# ── write_audit ───────────────────────────────────────────────────────────────

async def test_write_audit_persists_all_fields(db_session):
    """write_audit inserts a row with the correct username, action, detail, and IP."""
    await write_audit(
        db_session, "alice", ACTION_LOGIN,
        detail="User logged in", source_ip="10.0.0.1",
    )

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.username == "alice"
    assert row.action == ACTION_LOGIN
    assert row.detail == "User logged in"
    assert row.source_ip == "10.0.0.1"
    assert row.timestamp is not None


async def test_write_audit_without_optional_fields(db_session):
    """write_audit works when detail and source_ip are omitted."""
    await write_audit(db_session, "bob", ACTION_LOGOUT)

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].detail is None
    assert rows[0].source_ip is None


async def test_write_audit_timestamp_is_utc(db_session):
    """write_audit stores a timezone-aware UTC timestamp close to now."""
    before = datetime.now(timezone.utc)
    await write_audit(db_session, "carol", ACTION_PASSWORD_CHANGED)
    after = datetime.now(timezone.utc)

    row = (await db_session.execute(select(AuditLog))).scalars().first()
    assert row is not None
    ts = row.timestamp.replace(tzinfo=timezone.utc) if row.timestamp.tzinfo is None else row.timestamp
    assert before <= ts <= after


async def test_write_audit_multiple_entries(db_session):
    """write_audit appends a new row each time; existing rows are untouched."""
    await write_audit(db_session, "dave", ACTION_SESSION_STARTED, detail="dev-box (10.0.0.5:22)")
    await write_audit(db_session, "dave", ACTION_SESSION_ENDED,   detail="dev-box (10.0.0.5:22)")

    rows = (await db_session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    assert len(rows) == 2
    assert rows[0].action == ACTION_SESSION_STARTED
    assert rows[1].action == ACTION_SESSION_ENDED


async def test_write_audit_swallows_db_errors():
    """write_audit must not propagate exceptions — it is fire-and-forget."""
    broken_db = AsyncMock()
    broken_db.add = MagicMock(side_effect=RuntimeError("disk full"))

    # Should not raise
    await write_audit(broken_db, "eve", ACTION_LOGIN)


# ── prune_old_entries ─────────────────────────────────────────────────────────

async def test_prune_removes_old_entries(db_session):
    """prune_old_entries deletes entries older than retention_days."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    new_ts = datetime.now(timezone.utc)

    db_session.add(AuditLog(username="u", action=ACTION_LOGIN, timestamp=old_ts))
    db_session.add(AuditLog(username="u", action=ACTION_LOGIN, timestamp=new_ts))
    await db_session.commit()

    deleted = await prune_old_entries(db_session, retention_days=7)

    assert deleted == 1
    remaining = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(remaining) == 1
    ts = remaining[0].timestamp
    ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    assert (datetime.now(timezone.utc) - ts).days < 7


async def test_prune_keeps_entries_within_retention(db_session):
    """prune_old_entries does not delete entries within the retention window."""
    recent_ts = datetime.now(timezone.utc) - timedelta(days=3)
    db_session.add(AuditLog(username="u", action=ACTION_LOGIN, timestamp=recent_ts))
    await db_session.commit()

    deleted = await prune_old_entries(db_session, retention_days=7)

    assert deleted == 0
    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1


async def test_prune_empty_table_returns_zero(db_session):
    """prune_old_entries on an empty table returns 0 without error."""
    deleted = await prune_old_entries(db_session, retention_days=7)
    assert deleted == 0


async def test_prune_returns_correct_count(db_session):
    """prune_old_entries returns the exact number of rows deleted."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=30)
    for i in range(5):
        db_session.add(AuditLog(username=f"u{i}", action=ACTION_LOGIN, timestamp=old_ts))
    await db_session.commit()

    deleted = await prune_old_entries(db_session, retention_days=7)
    assert deleted == 5


# ── get_client_ip ─────────────────────────────────────────────────────────────

def _make_request(headers: dict, client_host: str | None = None):
    """Build a minimal mock of a FastAPI Request with the given headers."""
    req = MagicMock()
    req.headers = {k.lower(): v for k, v in headers.items()}
    if client_host:
        req.client = MagicMock()
        req.client.host = client_host
    else:
        req.client = None
    return req


def test_get_client_ip_xff_single():
    """X-Forwarded-For with a single address returns that address."""
    req = _make_request({"x-forwarded-for": "1.2.3.4"})
    assert get_client_ip(req) == "1.2.3.4"


def test_get_client_ip_xff_chain():
    """X-Forwarded-For with a proxy chain returns the leftmost (original client)."""
    req = _make_request({"x-forwarded-for": "1.2.3.4, 10.0.0.1, 10.0.0.2"})
    assert get_client_ip(req) == "1.2.3.4"


def test_get_client_ip_xff_with_spaces():
    """X-Forwarded-For entries with surrounding spaces are stripped."""
    req = _make_request({"x-forwarded-for": "  5.6.7.8 , 10.0.0.1"})
    assert get_client_ip(req) == "5.6.7.8"


def test_get_client_ip_x_real_ip():
    """Falls back to X-Real-IP when X-Forwarded-For is absent."""
    req = _make_request({"x-real-ip": "9.10.11.12"})
    assert get_client_ip(req) == "9.10.11.12"


def test_get_client_ip_direct_connection():
    """Falls back to request.client.host when no proxy headers are present."""
    req = _make_request({}, client_host="192.168.1.1")
    assert get_client_ip(req) == "192.168.1.1"


def test_get_client_ip_xff_takes_priority_over_x_real_ip():
    """X-Forwarded-For takes priority over X-Real-IP."""
    req = _make_request({"x-forwarded-for": "1.1.1.1", "x-real-ip": "2.2.2.2"})
    assert get_client_ip(req) == "1.1.1.1"


def test_get_client_ip_no_info_returns_none():
    """Returns None when neither proxy headers nor client info are available."""
    req = _make_request({})
    assert get_client_ip(req) is None


def test_get_client_ip_truncated_to_45_chars():
    """IP strings longer than 45 characters are truncated to fit the DB column."""
    long_ip = "a" * 60
    req = _make_request({"x-forwarded-for": long_ip})
    result = get_client_ip(req)
    assert result is not None
    assert len(result) <= 45


def test_get_client_ip_ipv6():
    """Full IPv6 addresses are accepted and returned verbatim."""
    ipv6 = "2001:db8::1"
    req = _make_request({"x-forwarded-for": ipv6})
    assert get_client_ip(req) == ipv6
