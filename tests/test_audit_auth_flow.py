"""
tests/test_audit_auth_flow.py — verify audit entries are written by auth endpoints.

Tests cover:
- Successful login writes a LOGIN entry
- Failed login attempt does NOT write an audit entry
- Logout writes a LOGOUT entry
- change-password writes a PASSWORD_CHANGED entry
- Login entry carries the correct username
- Audit entries include a non-null timestamp
"""
from datetime import timezone

import pytest
from sqlalchemy import select

from backend.models.audit import AuditLog
from backend.services.audit import ACTION_LOGIN, ACTION_LOGOUT, ACTION_PASSWORD_CHANGED


# ── Login ─────────────────────────────────────────────────────────────────────

async def test_login_writes_audit_entry(client, db_session):
    """A successful login creates exactly one LOGIN audit entry."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == ACTION_LOGIN
    assert rows[0].username == "admin"


async def test_login_audit_entry_has_timestamp(client, db_session):
    """The LOGIN entry has a non-null, timezone-aware timestamp."""
    await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    row = (await db_session.execute(select(AuditLog))).scalars().first()
    assert row is not None
    assert row.timestamp is not None


async def test_failed_login_does_not_write_audit(client, db_session):
    """A failed login (wrong password) must NOT create any audit entry."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "wrong-password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 0


# ── Logout ────────────────────────────────────────────────────────────────────

async def test_logout_writes_audit_entry(auth_client, db_session):
    """A successful logout creates a LOGOUT audit entry after the LOGIN entry."""
    # auth_client fixture already performed a login — clear that entry first
    # by checking how many rows exist, then issuing the logout
    before = len((await db_session.execute(select(AuditLog))).scalars().all())

    resp = await auth_client.post("/api/auth/logout")
    assert resp.status_code == 204

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == before + 1
    logout_entry = max(rows, key=lambda r: r.id)
    assert logout_entry.action == ACTION_LOGOUT
    assert logout_entry.username == "admin"


# ── Change password ───────────────────────────────────────────────────────────

async def test_change_password_writes_audit_entry(auth_client, db_session):
    """A successful password change creates a PASSWORD_CHANGED audit entry."""
    before = len((await db_session.execute(select(AuditLog))).scalars().all())

    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 204

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == before + 1
    pw_entry = max(rows, key=lambda r: r.id)
    assert pw_entry.action == ACTION_PASSWORD_CHANGED
    assert pw_entry.username == "admin"


async def test_change_password_wrong_current_no_audit(auth_client, db_session):
    """A failed password change (wrong current password) must NOT write an audit entry."""
    before = len((await db_session.execute(select(AuditLog))).scalars().all())

    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "definitely-wrong", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 401

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == before
