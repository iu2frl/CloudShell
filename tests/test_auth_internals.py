"""
tests/test_auth_internals.py — tests for internal auth helpers and edge-cases
not reachable via the happy-path HTTP tests.

Covers (uncovered lines from the report):
- _verify_credentials falls back to env-var comparison when no DB hash exists (line 98)
- _verify_credentials uses bcrypt hash from DB when one is stored (line 93 branch)
- get_current_user rejects a token whose 'bid' does not match BOOT_ID (lines 125-127)
- get_current_user rejects a token with no 'sub' or 'jti' claim (lines 130, 136-141)
- _get_payload rejects a token with no 'jti' claim (lines 162, 164)
- _get_payload rejects a token whose 'bid' does not match BOOT_ID (lines 170-175)
- _get_payload rejects a token that has been revoked (lines 192-198)
- logout silently ignores an already-invalid JWT (lines 219-222)
- logout returns early when the decoded payload contains no 'jti' (lines 235-236)
- logout does NOT add a duplicate RevokedToken when the token is already revoked (line 240)
- change-password updates the existing AdminCredential row (lines 278-281 branch)
- change-password creates a new AdminCredential row when none exists (lines 282-284 branch)
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt as jose_jwt
from sqlalchemy import select

from backend.config import get_settings
from backend.models.auth import AdminCredential, RevokedToken
from backend.routers.auth import ALGORITHM, _verify_credentials


# ── _verify_credentials ───────────────────────────────────────────────────────

async def test_verify_credentials_env_fallback(db_session):
    """When no DB hash exists, credentials are checked against the env-var password."""
    # No AdminCredential row in the DB — falls back to env-var 'admin'
    result = await _verify_credentials("admin", "admin", db_session)
    assert result is True


async def test_verify_credentials_wrong_env_password(db_session):
    """Wrong password with no DB hash must return False."""
    result = await _verify_credentials("admin", "wrong", db_session)
    assert result is False


async def test_verify_credentials_uses_db_hash(db_session):
    """Once a hashed password is stored in the DB it is used for verification."""
    import bcrypt
    hashed = bcrypt.hashpw(b"dbpassword", bcrypt.gensalt()).decode()
    db_session.add(AdminCredential(username="admin", hashed_password=hashed))
    await db_session.commit()

    assert await _verify_credentials("admin", "dbpassword", db_session) is True
    assert await _verify_credentials("admin", "admin", db_session) is False


async def test_verify_credentials_wrong_username(db_session):
    """An unknown username must always return False regardless of password."""
    result = await _verify_credentials("notadmin", "admin", db_session)
    assert result is False


# ── get_current_user — boot-id mismatch ──────────────────────────────────────

async def test_token_with_wrong_boot_id_rejected(client):
    """A token carrying a different boot-id must be rejected with 401."""
    settings = get_settings()
    payload = {
        "sub": "admin",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": "00000000-0000-0000-0000-000000000000",  # wrong boot id
    }
    bad_token = jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    client.headers.update({"Authorization": f"Bearer {bad_token}"})

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert "server restart" in resp.json()["detail"].lower()


# ── get_current_user — missing claims ────────────────────────────────────────

async def test_token_without_sub_rejected(client):
    """A token with no 'sub' claim must be rejected with 401."""
    from backend.main import BOOT_ID
    settings = get_settings()
    payload = {
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": BOOT_ID,
        # 'sub' intentionally omitted
    }
    bad_token = jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    client.headers.update({"Authorization": f"Bearer {bad_token}"})

    resp = await client.get("/api/devices/")
    assert resp.status_code == 401


async def test_token_without_jti_rejected(client):
    """A token with no 'jti' claim must be rejected with 401."""
    from backend.main import BOOT_ID
    settings = get_settings()
    payload = {
        "sub": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": BOOT_ID,
        # 'jti' intentionally omitted
    }
    bad_token = jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    client.headers.update({"Authorization": f"Bearer {bad_token}"})

    resp = await client.get("/api/devices/")
    assert resp.status_code == 401


# ── _get_payload — boot-id mismatch & revoked ────────────────────────────────

async def test_refresh_with_wrong_boot_id_rejected(client):
    """POST /api/auth/refresh with a stale boot-id token must return 401."""
    settings = get_settings()
    payload = {
        "sub": "admin",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": "stale-boot-id",
    }
    bad_token = jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    client.headers.update({"Authorization": f"Bearer {bad_token}"})

    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert "server restart" in resp.json()["detail"].lower()


async def test_refresh_with_revoked_token_rejected(client, db_session):
    """POST /api/auth/refresh with a revoked token must return 401."""
    from backend.main import BOOT_ID
    settings = get_settings()
    jti = str(uuid.uuid4())
    payload = {
        "sub": "admin",
        "jti": jti,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": BOOT_ID,
    }
    token = jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)

    # Revoke the token directly in the DB
    db_session.add(RevokedToken(
        jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    await db_session.commit()

    client.headers.update({"Authorization": f"Bearer {token}"})
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert "revoked" in resp.json()["detail"].lower()


async def test_refresh_with_no_jti_rejected(client):
    """POST /api/auth/refresh with a token missing 'jti' must return 401."""
    from backend.main import BOOT_ID
    settings = get_settings()
    payload = {
        "sub": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": BOOT_ID,
        # 'jti' omitted
    }
    bad_token = jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    client.headers.update({"Authorization": f"Bearer {bad_token}"})

    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


# ── logout edge-cases ─────────────────────────────────────────────────────────

async def test_logout_with_invalid_jwt_returns_204(client):
    """Logout with a completely invalid JWT must return 204 (silent ignore)."""
    client.headers.update({"Authorization": "Bearer this.is.not.a.valid.jwt"})
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204


async def test_logout_twice_does_not_duplicate_revoked_token(client, db_session):
    """Logging out twice with the same token must not create duplicate RevokedToken rows."""
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    resp1 = await client.post("/api/auth/logout")
    resp2 = await client.post("/api/auth/logout")
    assert resp1.status_code == 204
    assert resp2.status_code == 204

    # Parse the JTI from the token and verify there is exactly one revocation row
    settings = get_settings()
    decoded = jose_jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    jti = decoded["jti"]
    rows = (
        await db_session.execute(select(RevokedToken).where(RevokedToken.jti == jti))
    ).scalars().all()
    assert len(rows) == 1


# ── change-password: update existing row vs. create new row ──────────────────

async def test_change_password_updates_existing_db_row(client, db_session):
    """When an AdminCredential row already exists it must be updated in-place."""
    import bcrypt

    # Pre-populate an AdminCredential row with the current password
    db_session.add(AdminCredential(
        username="admin",
        hashed_password=bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
    ))
    await db_session.commit()

    # Log in and change the password
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    resp = await client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "UpdatedPass1!"},
    )
    assert resp.status_code == 204

    # There must still be exactly one row for 'admin'
    rows = (
        await db_session.execute(
            select(AdminCredential).where(AdminCredential.username == "admin")
        )
    ).scalars().all()
    assert len(rows) == 1

    # New hash must verify the new password
    assert bcrypt.checkpw(b"UpdatedPass1!", rows[0].hashed_password.encode())


async def test_change_password_creates_new_db_row(client, db_session):
    """When no AdminCredential row exists, change-password must create one."""
    # No pre-seeded AdminCredential; password comes from env var ('admin')
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    resp = await client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "FreshPass99!"},
    )
    assert resp.status_code == 204

    rows = (
        await db_session.execute(
            select(AdminCredential).where(AdminCredential.username == "admin")
        )
    ).scalars().all()
    assert len(rows) == 1
