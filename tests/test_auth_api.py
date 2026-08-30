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
import hashlib
from urllib.parse import parse_qs, urlparse

import pyotp

from backend.models.auth import AdminTOTPSecret


# -- POST /api/auth/token ------------------------------------------------------

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


async def test_login_cookie_auth_allows_me_without_authorization_header(client):
    """After login, auth cookie alone should authorize protected endpoints."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200

    client.headers.pop("Authorization", None)
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "admin"


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
    """Wrong username must return 401."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "wrong", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


async def test_login_requires_2fa(client, monkeypatch):
    from backend.routers import auth
    # Mock verify
    async def mock_verify_credentials(*args, **kwargs):
        return True
    monkeypatch.setattr(auth, "_verify_credentials", mock_verify_credentials)
    
    # Mock db
    class MockTOTPRecord:
        is_enabled = True

    class MockDB:
        async def get(self, model, ident):
            return MockTOTPRecord()
        async def execute(self, *args, **kwargs):
            pass
        async def commit(self):
            pass

    async def override_get_db():
        yield MockDB()

    from backend.main import app
    app.dependency_overrides[auth.get_db] = override_get_db

    response = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "password"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "2FA_REQUIRED"

    app.dependency_overrides.clear()


async def test_login_invalid_2fa(client, monkeypatch):
    from backend.routers import auth
    async def mock_verify_credentials(*args, **kwargs):
        return True
    monkeypatch.setattr(auth, "_verify_credentials", mock_verify_credentials)

    class MockTOTPRecord:
        is_enabled = True
        secret = "SECRET"
        
        backup_codes = "[]"
        
    class MockDB:
        async def get(self, model, ident):
            return MockTOTPRecord()
        async def execute(self, *args, **kwargs):
            pass
        async def commit(self):
            pass
        def add(self, *args, **kwargs):
            pass

    async def override_get_db():
        yield MockDB()

    from backend.main import app
    app.dependency_overrides[auth.get_db] = override_get_db

    from backend.services.totp import TOTPService
    monkeypatch.setattr(TOTPService, "verify_token", lambda *args, **kwargs: False)

    response = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "password", "totp_code": "000000"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid 2FA code"

    app.dependency_overrides.clear()


async def test_login_valid_2fa(client, monkeypatch):
    from backend.routers import auth
    async def mock_verify_credentials(*args, **kwargs):
        return True
    monkeypatch.setattr(auth, "_verify_credentials", mock_verify_credentials)

    class MockTOTPRecord:
        is_enabled = True
        secret = "SECRET"
        backup_codes = "[]"
        
    class MockDB:
        async def get(self, model, ident):
            return MockTOTPRecord()

        async def execute(self, *args, **kwargs):
            """Support `write_audit()` (SELECT) calls during login."""

            class MockResult:
                def scalar_one_or_none(self):
                    return None

            return MockResult()

        def add(self, *args, **kwargs):
            pass

        async def commit(self):
            pass
            
    async def override_get_db():
        yield MockDB()

    from backend.main import app
    app.dependency_overrides[auth.get_db] = override_get_db

    from backend.services.totp import TOTPService
    monkeypatch.setattr(TOTPService, "verify_token", lambda *args, **kwargs: True)

    response = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "password", "totp_code": "123456"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

    app.dependency_overrides.clear()


async def test_login_rejects_legacy_sha256_backup_codes(client, monkeypatch):
    """Legacy SHA256 backup-code hashes should require regeneration."""
    from backend.routers import auth

    async def mock_verify_credentials(*args, **kwargs):
        return True

    monkeypatch.setattr(auth, "_verify_credentials", mock_verify_credentials)

    class MockTOTPRecord:
        is_enabled = True
        secret = "SECRET"
        backup_codes = '["' + hashlib.sha256("AAAA-BBBB".encode("utf-8")).hexdigest() + '"]'

    class MockDB:
        async def get(self, model, ident):
            return MockTOTPRecord()

        async def execute(self, *args, **kwargs):
            class MockResult:
                def scalar_one_or_none(self):
                    return None

            return MockResult()

        def add(self, *args, **kwargs):
            pass

        async def commit(self):
            pass

    async def override_get_db():
        yield MockDB()

    from backend.main import app

    app.dependency_overrides[auth.get_db] = override_get_db

    from backend.services.totp import TOTPService

    monkeypatch.setattr(TOTPService, "verify_token", lambda *args, **kwargs: False)

    response = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "password", "totp_code": "AAAA-BBBB"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Backup codes must be regenerated"

    app.dependency_overrides.clear()


async def test_login_empty_credentials(client):
    """Empty username and password must be rejected (422 from form validation or 401)."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "", "password": ""},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code in (401, 422)


# -- OIDC endpoints ------------------------------------------------------------

async def test_oidc_status_disabled_by_default(client):
    """OIDC status should be disabled when OIDC_ENABLED is not set."""
    resp = await client.get("/api/auth/oidc/status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


async def test_oidc_login_disabled_returns_404(client):
    """OIDC login endpoint must be unavailable when OIDC is disabled."""
    resp = await client.get("/api/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 404


async def test_oidc_login_redirects_with_state_cookie(client, monkeypatch):
    """OIDC login must redirect to provider and set signed state cookie."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "super-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://test/api/auth/oidc/callback")

    from backend.config import get_settings
    get_settings.cache_clear()

    from backend.routers import auth

    async def _fake_discovery():
        return {"authorization_endpoint": "https://id.example.com/authorize"}

    monkeypatch.setattr(auth, "_get_oidc_discovery", _fake_discovery)

    resp = await client.get("/api/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://id.example.com/authorize"
    assert "state" in query
    assert "nonce" in query
    assert "cloudshell_oidc_state" in resp.cookies
    assert resp.cookies["cloudshell_oidc_state"] == query["state"][0]


async def test_oidc_callback_creates_local_session_cookie(client, monkeypatch):
    """Valid OIDC callback should create a local CloudShell session cookie."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "super-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://test/api/auth/oidc/callback")

    from backend.config import get_settings
    get_settings.cache_clear()

    from backend.routers import auth

    async def _fake_discovery():
        return {"authorization_endpoint": "https://id.example.com/authorize"}

    async def _fake_exchange(code: str, expected_nonce: str) -> str:
        assert code == "test-code"
        assert expected_nonce
        return "oidc:https://id.example.com:user-123"

    monkeypatch.setattr(auth, "_get_oidc_discovery", _fake_discovery)
    monkeypatch.setattr(auth, "_exchange_oidc_code", _fake_exchange)

    start_resp = await client.get("/api/auth/oidc/login", follow_redirects=False)
    state = parse_qs(urlparse(start_resp.headers["location"]).query)["state"][0]

    callback_resp = await client.get(
        f"/api/auth/oidc/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"] == "/"

    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "oidc:https://id.example.com:user-123"


async def test_oidc_callback_rejects_state_mismatch(client, monkeypatch):
    """OIDC callback must reject mismatched state values."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "super-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://test/api/auth/oidc/callback")

    from backend.config import get_settings
    get_settings.cache_clear()

    from backend.routers import auth

    async def _fake_discovery():
        return {"authorization_endpoint": "https://id.example.com/authorize"}

    monkeypatch.setattr(auth, "_get_oidc_discovery", _fake_discovery)

    start_resp = await client.get("/api/auth/oidc/login", follow_redirects=False)
    assert start_resp.status_code == 302

    bad_state = "not-the-cookie-state"
    callback_resp = await client.get(
        f"/api/auth/oidc/callback?code=test-code&state={bad_state}",
        follow_redirects=False,
    )
    assert callback_resp.status_code == 400


async def test_login_remember_device_skips_future_2fa(client, db_session):
    """A remembered device should bypass TOTP for 30 days."""
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    auth_headers = {"Authorization": f"Bearer {token}"}
    setup_resp = await client.post("/api/auth/2fa/setup", headers=auth_headers)
    assert setup_resp.status_code == 200

    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is not None
    totp_code = pyotp.TOTP(record.secret).now()

    enable_resp = await client.post(
        "/api/auth/2fa/enable",
        headers=auth_headers,
        json={"token": totp_code},
    )
    assert enable_resp.status_code == 204

    require_2fa_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert require_2fa_resp.status_code == 403
    assert require_2fa_resp.json()["detail"] == "2FA_REQUIRED"

    remember_resp = await client.post(
        "/api/auth/token",
        data={
            "username": "admin",
            "password": "admin",
            "totp_code": pyotp.TOTP(record.secret).now(),
            "remember_device": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert remember_resp.status_code == 200
    assert "cloudshell_trusted_device=" in remember_resp.headers.get("set-cookie", "")
    assert "Max-Age=2592000" in remember_resp.headers.get("set-cookie", "")

    trusted_login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert trusted_login_resp.status_code == 200


async def test_login_invalid_remembered_device_cookie_still_requires_2fa(client, db_session):
    """An unknown remember-device cookie must not bypass TOTP."""
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    auth_headers = {"Authorization": f"Bearer {token}"}
    setup_resp = await client.post("/api/auth/2fa/setup", headers=auth_headers)
    assert setup_resp.status_code == 200

    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is not None
    enable_resp = await client.post(
        "/api/auth/2fa/enable",
        headers=auth_headers,
        json={"token": pyotp.TOTP(record.secret).now()},
    )
    assert enable_resp.status_code == 204

    client.cookies.set("cloudshell_trusted_device", "not-a-valid-token")

    response = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "2FA_REQUIRED"


# -- POST /api/auth/refresh ----------------------------------------------------

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


# -- POST /api/auth/logout -----------------------------------------------------

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


# -- GET /api/auth/me ----------------------------------------------------------

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


# -- POST /api/auth/change-password -------------------------------------------

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


# -- Backup code depletion warnings -------------------------------------------

async def test_login_backup_codes_warning_normal_login(client):
    """Normal login without backup codes should have no warning."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # No backup codes used, so warning should be None
    assert body.get("backup_codes_warning") is None


async def test_login_backup_codes_warning_when_depleting(client, db_session):
    """Login using last backup code should include warning."""
    from backend.services.totp import TOTPService
    from backend.models.auth import AdminTOTPSecret
    
    # Setup and login to get token
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # Setup 2FA
    setup_resp = await client.post("/api/auth/2fa/setup", headers=auth_headers)
    assert setup_resp.status_code == 200
    
    # Manually enable with only 1 backup code remaining
    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is not None
    record.is_enabled = True
    
    # Set just 1 backup code (depleted state)
    test_codes = ["AAAA-BBBB"]
    record.backup_codes = TOTPService.codes_to_json(test_codes, hashed=True)
    await db_session.commit()
    
    # Logout
    await client.post("/api/auth/logout", headers=auth_headers)
    
    # Login with backup code (the only one)
    login_resp = await client.post(
        "/api/auth/token",
        data={
            "username": "admin",
            "password": "admin",
            "totp_code": "AAAA-BBBB",  # Last backup code
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    
    # Should have warning about depletion
    assert body.get("backup_codes_warning") is not None
    assert "0 backup code" in body["backup_codes_warning"]
    assert "WARNING" in body["backup_codes_warning"]


async def test_login_backup_codes_warning_at_threshold(client, db_session):
    """Login using 3rd-to-last backup code should trigger warning."""
    from backend.services.totp import TOTPService
    from backend.models.auth import AdminTOTPSecret
    
    # Setup and login to get token
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # Setup 2FA
    setup_resp = await client.post("/api/auth/2fa/setup", headers=auth_headers)
    assert setup_resp.status_code == 200
    
    # Manually enable with exactly 3 backup codes
    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is not None
    record.is_enabled = True
    
    test_codes = ["AAAA-BBBB", "CCCC-DDDD", "EEEE-FFFF"]
    record.backup_codes = TOTPService.codes_to_json(test_codes, hashed=True)
    await db_session.commit()
    
    # Logout
    await client.post("/api/auth/logout", headers=auth_headers)
    
    # Login with last code (will leave 2 remaining, below threshold)
    login_resp = await client.post(
        "/api/auth/token",
        data={
            "username": "admin",
            "password": "admin",
            "totp_code": "EEEE-FFFF",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    
    # Should have warning (2 codes remaining, which is < 3)
    assert body.get("backup_codes_warning") is not None
    assert "2 backup code" in body["backup_codes_warning"]


async def test_login_backup_codes_no_warning_above_threshold(client, db_session):
    """Login with >3 backup codes remaining should have no warning."""
    from backend.services.totp import TOTPService
    from backend.models.auth import AdminTOTPSecret
    
    # Setup and login to get token
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # Setup 2FA
    setup_resp = await client.post("/api/auth/2fa/setup", headers=auth_headers)
    assert setup_resp.status_code == 200
    
    # Manually enable with 5 backup codes
    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is not None
    record.is_enabled = True
    
    test_codes = ["AAAA-BBBB", "CCCC-DDDD", "EEEE-FFFF", "GGGG-HHHH", "IIII-JJJJ"]
    record.backup_codes = TOTPService.codes_to_json(test_codes, hashed=True)
    await db_session.commit()
    
    # Logout
    await client.post("/api/auth/logout", headers=auth_headers)
    
    # Login with one code (will leave 4 remaining, above threshold)
    login_resp = await client.post(
        "/api/auth/token",
        data={
            "username": "admin",
            "password": "admin",
            "totp_code": "IIII-JJJJ",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    
    # Should have no warning (4 codes remaining, which is >= 3)
    assert body.get("backup_codes_warning") is None
