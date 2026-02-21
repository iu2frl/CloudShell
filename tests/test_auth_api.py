"""
tests/test_auth_api.py — integration tests for the authentication HTTP API.

Tests cover:
- POST /api/auth/token  (login)
  - successful login returns a valid token
  - wrong password returns 401
  - wrong username returns 401
  - response contains access_token, token_type, expires_at
  - token_type is 'bearer'
  - expires_at is in the future
- POST /api/auth/refresh
  - valid token is refreshed with a new token
  - refreshed token grants access
  - old token is revoked after refresh
  - expired / missing token returns 401
- POST /api/auth/logout
  - successful logout returns 204
  - token is invalidated after logout
  - unauthenticated logout returns 401
- GET /api/auth/me
  - returns correct username and expires_at
  - unauthenticated request returns 401
  - revoked token returns 401
- POST /api/auth/change-password
  - successful change returns 204
  - new password works for subsequent login
  - old password no longer works after change
  - wrong current password returns 401
  - password shorter than 8 characters returns 422
  - unauthenticated request returns 401
"""
from datetime import datetime, timezone


# ── POST /api/auth/token ──────────────────────────────────────────────────────

async def test_login_returns_token(client):
    """Valid credentials must return a bearer token."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["access_token"]


async def test_login_response_schema(client):
    """Login response must include access_token, token_type, and expires_at."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert "expires_at" in body


async def test_login_expires_at_is_future(client):
    """expires_at in the login response must be a future UTC datetime."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    expires_at = datetime.fromisoformat(resp.json()["expires_at"])
    # Make offset-naive for comparison if needed
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at > datetime.now(timezone.utc)


async def test_login_wrong_password(client):
    """Wrong password must return 401."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "totally-wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


async def test_login_wrong_username(client):
    """Non-existent username must return 401."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "nobody", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


async def test_login_empty_credentials(client):
    """Empty username and password must be rejected (422 from form validation or 401)."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "", "password": ""},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code in (401, 422)


# ── POST /api/auth/refresh ────────────────────────────────────────────────────

async def test_refresh_returns_new_token(auth_client):
    """A valid token can be refreshed and the new token is different."""
    old_token = auth_client.headers["Authorization"].split(" ")[1]
    resp = await auth_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["access_token"] != old_token


async def test_refresh_new_token_grants_access(auth_client):
    """The refreshed token must be accepted by protected endpoints."""
    resp = await auth_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]
    auth_client.headers.update({"Authorization": f"Bearer {new_token}"})
    me_resp = await auth_client.get("/api/auth/me")
    assert me_resp.status_code == 200


async def test_refresh_old_token_is_revoked(client):
    """After a refresh the original token must no longer be accepted."""
    # Login to get a token
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    original_token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {original_token}"})

    # Refresh
    refresh_resp = await client.post("/api/auth/refresh")
    assert refresh_resp.status_code == 200

    # Old token must now be rejected
    client.headers.update({"Authorization": f"Bearer {original_token}"})
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 401


async def test_refresh_without_token(client):
    """Refresh without a token must return 401."""
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


# ── POST /api/auth/logout ─────────────────────────────────────────────────────

async def test_logout_returns_204(auth_client):
    """Successful logout returns HTTP 204."""
    resp = await auth_client.post("/api/auth/logout")
    assert resp.status_code == 204


async def test_logout_invalidates_token(client):
    """After logout, the used token must be rejected on subsequent requests."""
    # Login
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    # Logout
    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 204

    # Subsequent request with the same token must fail
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 401


async def test_logout_without_token_returns_401(client):
    """Logout without a token must return 401."""
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 401


# ── GET /api/auth/me ──────────────────────────────────────────────────────────

async def test_me_returns_username(auth_client):
    """GET /api/auth/me must return the correct username."""
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


async def test_me_returns_expires_at(auth_client):
    """GET /api/auth/me must return a future expires_at value."""
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    expires_at = datetime.fromisoformat(resp.json()["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at > datetime.now(timezone.utc)


async def test_me_without_token_returns_401(client):
    """GET /api/auth/me without a token must return 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_invalid_token_returns_401(client):
    """GET /api/auth/me with a garbage token must return 401."""
    client.headers.update({"Authorization": "Bearer this.is.garbage"})
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_after_logout_returns_401(client):
    """GET /api/auth/me with a revoked (post-logout) token must return 401."""
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    await client.post("/api/auth/logout")
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


# ── POST /api/auth/change-password ───────────────────────────────────────────

async def test_change_password_success(auth_client):
    """A valid password change returns 204."""
    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "NewPassword1!"},
    )
    assert resp.status_code == 204


async def test_change_password_new_password_works(client):
    """After a password change the new password must be accepted at login."""
    # Login to get a token
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    # Change password
    await client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "BrandNew99!"},
    )

    # New password must work
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "BrandNew99!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200


async def test_change_password_old_password_rejected(client):
    """After a password change the old password must be rejected at login."""
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})

    await client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "BrandNew99!"},
    )

    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


async def test_change_password_wrong_current(auth_client):
    """Wrong current password must return 401."""
    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-real-one", "new_password": "ShouldFail1!"},
    )
    assert resp.status_code == 401


async def test_change_password_too_short(auth_client):
    """New password shorter than 8 characters must return 422."""
    resp = await auth_client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "short"},
    )
    assert resp.status_code == 422


async def test_change_password_requires_auth(client):
    """Unauthenticated change-password request must return 401."""
    resp = await client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "ShouldFail1!"},
    )
    assert resp.status_code == 401
