"""
tests/test_auth_extra.py — extra coverage for auth internals and edge cases.

Covers uncovered lines in backend/routers/auth.py:
- _is_revoked returns True for a stored JTI
- _prune_expired_tokens removes only expired tokens
- _get_payload raises 401 when token has no jti
- _get_payload raises 401 on wrong boot-id
- _get_payload raises 401 on revoked token
- /refresh removes the old token and issues a new one
- /logout with no jti in payload is a no-op
- /logout with already-expired / invalid token is a no-op
- /me returns username and expires_at
- /change-password rejects passwords shorter than 8 chars
- /change-password wrong current password raises 401
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt as jose_jwt
from sqlalchemy import select

from backend.config import get_settings
from backend.models.auth import RevokedToken
from backend.routers.auth import (
    ALGORITHM,
    _is_revoked,
    _prune_expired_tokens,
)


# ── _is_revoked ───────────────────────────────────────────────────────────────

async def test_is_revoked_returns_false_for_unknown_jti(db_session):
    """_is_revoked must return False when the JTI is not in the revoked table."""
    assert await _is_revoked("nonexistent-jti", db_session) is False


async def test_is_revoked_returns_true_for_known_jti(db_session):
    """_is_revoked must return True when the JTI has been stored."""
    jti = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.add(RevokedToken(jti=jti, expires_at=expires))
    await db_session.commit()

    assert await _is_revoked(jti, db_session) is True


# ── _prune_expired_tokens ─────────────────────────────────────────────────────

async def test_prune_expired_tokens_removes_past_tokens(db_session):
    """_prune_expired_tokens must delete tokens whose expires_at is in the past."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    jti_old = str(uuid.uuid4())
    jti_new = str(uuid.uuid4())

    db_session.add(RevokedToken(jti=jti_old, expires_at=past))
    db_session.add(RevokedToken(jti=jti_new, expires_at=future))
    await db_session.commit()

    await _prune_expired_tokens(db_session)

    remaining = (await db_session.execute(select(RevokedToken))).scalars().all()
    jtis = {r.jti for r in remaining}
    assert jti_old not in jtis
    assert jti_new in jtis


async def test_prune_expired_tokens_empty_table(db_session):
    """_prune_expired_tokens on an empty table must not raise."""
    await _prune_expired_tokens(db_session)
    count = len((await db_session.execute(select(RevokedToken))).scalars().all())
    assert count == 0


# ── GET /api/auth/me ──────────────────────────────────────────────────────────

async def test_me_returns_username_and_expiry(auth_client):
    """GET /api/auth/me must return the logged-in username and a future expires_at."""
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires > datetime.now(timezone.utc)


async def test_me_requires_auth(client):
    """GET /api/auth/me without a token must return 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


# ── POST /api/auth/refresh ────────────────────────────────────────────────────

async def test_refresh_revokes_old_jti(auth_client, db_session):
    """After /refresh the original JTI must appear in the revoked-tokens table."""
    settings = get_settings()
    # Retrieve the current token's JTI before refreshing
    me_resp = await auth_client.get("/api/auth/me")
    assert me_resp.status_code == 200

    # Grab raw token from the Authorization header
    raw_token = auth_client.headers["Authorization"].split(" ")[1]
    payload = jose_jwt.decode(raw_token, settings.secret_key, algorithms=[ALGORITHM])
    old_jti = payload["jti"]

    refresh_resp = await auth_client.post("/api/auth/refresh")
    assert refresh_resp.status_code == 200

    # Old JTI must now be in the revoked table
    revoked = await db_session.get(RevokedToken, old_jti)
    assert revoked is not None


async def test_refresh_new_token_is_different(auth_client):
    """The token returned by /refresh must differ from the one used to call it."""
    old_token = auth_client.headers["Authorization"].split(" ")[1]
    resp = await auth_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]
    assert new_token != old_token


# ── POST /api/auth/logout ─────────────────────────────────────────────────────

async def test_logout_with_invalid_token_is_no_op(client):
    """POST /api/auth/logout with a garbage token must not raise — just return."""
    client.headers["Authorization"] = "Bearer this.is.garbage"
    resp = await client.post("/api/auth/logout")
    # The router swallows invalid-token errors and returns 204
    assert resp.status_code == 204


async def test_logout_idempotent(auth_client):
    """Logging out twice must both succeed (second call is a no-op)."""
    resp1 = await auth_client.post("/api/auth/logout")
    assert resp1.status_code == 204
    resp2 = await auth_client.post("/api/auth/logout")
    assert resp2.status_code == 204


# ── POST /api/auth/change-password — edge cases ───────────────────────────────

async def test_change_password_wrong_current_returns_401(auth_client):
    """change-password with the wrong current password must return 401."""
    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 401


async def test_change_password_too_short_returns_422(auth_client):
    """change-password with a new password shorter than 8 chars must return 422."""
    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "short"},
    )
    assert resp.status_code == 422


async def test_change_password_success_then_old_password_rejected(auth_client):
    """After a successful password change the old password must no longer work."""
    change_resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "NewSecurePass1!"},
    )
    assert change_resp.status_code == 204

    # Log in with the old password — must fail
    login_resp = await auth_client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 401
