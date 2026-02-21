"""
tests/test_audit_api.py — integration tests for the audit log HTTP API.

Tests cover:
- GET /api/audit/logs requires authentication
- GET /api/audit/logs returns empty list when no entries exist
- GET /api/audit/logs returns entries with all expected fields
- GET /api/audit/logs orders entries newest-first
- GET /api/audit/logs pagination: page/page_size parameters
- GET /api/audit/logs pagination: page beyond range returns empty entries
- POST /api/audit/prune requires authentication
- POST /api/audit/prune deletes old entries and reports the count
- POST /api/audit/prune returns retention_days from config
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.audit import AuditLog
from backend.services.audit import ACTION_LOGIN, ACTION_SESSION_STARTED


# ── Authentication guard ──────────────────────────────────────────────────────

async def test_audit_logs_requires_auth(client):
    """Unauthenticated request to /api/audit/logs must return 401."""
    resp = await client.get("/api/audit/logs")
    assert resp.status_code == 401


async def test_audit_prune_requires_auth(client):
    """Unauthenticated request to /api/audit/prune must return 401."""
    resp = await client.post("/api/audit/prune")
    assert resp.status_code == 401


# ── GET /api/audit/logs ───────────────────────────────────────────────────────

async def test_audit_logs_empty(auth_client):
    """The log only contains the LOGIN entry written by the auth_client fixture."""
    resp = await auth_client.get("/api/audit/logs")
    assert resp.status_code == 200
    body = resp.json()
    # auth_client logs in, so exactly one LOGIN entry is expected
    assert body["total"] == 1
    assert body["entries"][0]["action"] == ACTION_LOGIN
    assert body["page"] == 1


async def test_audit_logs_returns_entries(auth_client, db_session):
    """Entries written directly to the DB are returned by the API."""
    # Capture baseline (auth_client login already wrote 1 entry)
    baseline = (await auth_client.get("/api/audit/logs")).json()["total"]

    db_session.add(AuditLog(
        username="admin", action=ACTION_SESSION_STARTED,
        detail="User logged in", source_ip="1.2.3.4",
        timestamp=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    resp = await auth_client.get("/api/audit/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == baseline + 1
    # Newest-first: our entry is at index 0
    entry = body["entries"][0]
    assert entry["username"] == "admin"
    assert entry["action"] == ACTION_SESSION_STARTED
    assert entry["detail"] == "User logged in"
    assert entry["source_ip"] == "1.2.3.4"
    assert "timestamp" in entry


async def test_audit_logs_newest_first(auth_client, db_session):
    """Entries are returned in descending timestamp order (newest first)."""
    now = datetime.now(timezone.utc)
    # Add entries with timestamps older than the fixture LOGIN (now)
    db_session.add(AuditLog(username="u", action="A", timestamp=now - timedelta(minutes=5)))
    db_session.add(AuditLog(username="u", action="B", timestamp=now - timedelta(minutes=1)))
    db_session.add(AuditLog(username="u", action="C", timestamp=now - timedelta(minutes=3)))
    await db_session.commit()

    resp = await auth_client.get("/api/audit/logs")
    assert resp.status_code == 200
    # The LOGIN from auth_client is the newest; then B, C, A in descending order
    actions = [e["action"] for e in resp.json()["entries"]]
    assert actions == [ACTION_LOGIN, "B", "C", "A"]


async def test_audit_logs_pagination_page_size(auth_client, db_session):
    """page_size limits the number of entries returned per request."""
    # auth_client login already wrote 1 entry; add 9 more = 10 total
    now = datetime.now(timezone.utc)
    for i in range(9):
        db_session.add(AuditLog(
            username="u", action=ACTION_LOGIN,
            timestamp=now - timedelta(seconds=i + 1),
        ))
    await db_session.commit()

    resp = await auth_client.get("/api/audit/logs?page=1&page_size=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 10
    assert len(body["entries"]) == 3


async def test_audit_logs_pagination_second_page(auth_client, db_session):
    """Second page returns the correct slice of entries."""
    # auth_client login = 1 entry; add 4 more = 5 total, page_size=3 → page 2 has 2
    now = datetime.now(timezone.utc)
    for i in range(4):
        db_session.add(AuditLog(
            username="u", action=ACTION_LOGIN,
            timestamp=now - timedelta(seconds=i + 1),
        ))
    await db_session.commit()

    resp = await auth_client.get("/api/audit/logs?page=2&page_size=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["entries"]) == 2   # 5 total, 3 on page 1, 2 on page 2


async def test_audit_logs_pagination_beyond_range(auth_client, db_session):
    """A page number beyond the available data returns an empty entries list."""
    # auth_client login = 1 entry; total == 2 after adding one more
    db_session.add(AuditLog(
        username="u", action=ACTION_LOGIN,
        timestamp=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    resp = await auth_client.get("/api/audit/logs?page=99&page_size=50")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["entries"] == []


async def test_audit_logs_source_ip_can_be_null(auth_client, db_session):
    """Entries without a source_ip serialize source_ip as null."""
    db_session.add(AuditLog(
        username="u", action=ACTION_SESSION_STARTED,
        source_ip=None, timestamp=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    resp = await auth_client.get("/api/audit/logs")
    assert resp.status_code == 200
    # Find the SESSION_STARTED entry and confirm its source_ip is null
    entries = resp.json()["entries"]
    target = next(e for e in entries if e["action"] == ACTION_SESSION_STARTED)
    assert target["source_ip"] is None


# ── POST /api/audit/prune ─────────────────────────────────────────────────────

async def test_audit_prune_deletes_old_entries(auth_client, db_session):
    """POST /api/audit/prune removes entries older than AUDIT_RETENTION_DAYS."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=30)
    new_ts = datetime.now(timezone.utc)
    db_session.add(AuditLog(username="u", action=ACTION_LOGIN, timestamp=old_ts))
    db_session.add(AuditLog(username="u", action=ACTION_LOGIN, timestamp=new_ts))
    await db_session.commit()

    resp = await auth_client.post("/api/audit/prune")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 1
    assert body["retention_days"] == 7   # matches AUDIT_RETENTION_DAYS env var in conftest


async def test_audit_prune_preserves_recent_entries(auth_client, db_session):
    """POST /api/audit/prune does not delete entries within the retention window."""
    recent_ts = datetime.now(timezone.utc) - timedelta(days=3)
    db_session.add(AuditLog(username="u", action=ACTION_LOGIN, timestamp=recent_ts))
    await db_session.commit()

    resp = await auth_client.post("/api/audit/prune")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0

    # Both the fixture LOGIN and the recent row must still be present
    resp2 = await auth_client.get("/api/audit/logs")
    assert resp2.json()["total"] == 2


async def test_audit_prune_empty_table(auth_client):
    """POST /api/audit/prune on an empty log returns deleted=0 without error."""
    resp = await auth_client.post("/api/audit/prune")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0
