"""
tests/test_auth_2fa_api.py — Integration tests for 2FA endpoints.
"""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch, MagicMock

from httpx import AsyncClient
from sqlalchemy import text

from backend.models.auth import AdminTOTPSecret


def _get_token_from_response(response) -> str:
    """Extract access_token from login response."""
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _get_auth_headers(client: AsyncClient) -> dict:
    """Get auth headers with valid token."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = _get_token_from_response(resp)
    return {"Authorization": f"Bearer {token}"}


class TestTwoFactorAuthAPI:
    """Test 2FA API endpoints."""

    async def test_get_2fa_status_disabled(self, client: AsyncClient):
        """Should return enabled=false when 2FA not set up."""
        headers = await _get_auth_headers(client)
        response = await client.get(
            "/api/auth/2fa/status",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

    async def test_setup_2fa_generates_qr_code(self, client: AsyncClient):
        """Setup endpoint should return QR code and backup codes only."""
        headers = await _get_auth_headers(client)
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "qr_code" in data
        assert data["qr_code"].startswith("data:image/png;base64,")
        assert "secret" not in data
        assert "backup_codes" in data
        assert len(data["backup_codes"]) == 10
        # Codes should be in format XXXX-XXXX
        for code in data["backup_codes"]:
            assert len(code) == 9
            assert code[4] == "-"

    async def test_setup_2fa_sets_no_store_headers(self, client: AsyncClient):
        """Setup response should disable HTTP caching for sensitive payloads."""
        headers = await _get_auth_headers(client)
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, max-age=0"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"

    async def test_setup_2fa_uses_environment_aware_issuer(self, client: AsyncClient):
        """Setup should pass environment-aware issuer to provisioning URI helper."""
        headers = await _get_auth_headers(client)

        with patch("backend.routers.auth_2fa.get_settings") as mock_get_settings, patch(
            "backend.routers.auth_2fa.TOTPService.get_provisioning_uri"
        ) as mock_get_provisioning_uri:
            mock_get_settings.return_value = MagicMock(environment="staging")
            mock_get_provisioning_uri.return_value = "otpauth://dummy"

            response = await client.post(
                "/api/auth/2fa/setup",
                headers=headers,
            )
            assert response.status_code == 200

            _, kwargs = mock_get_provisioning_uri.call_args
            assert kwargs["issuer"] == "CloudShell (staging)"

    async def test_setup_2fa_restarts_if_setup_in_progress(
        self, client: AsyncClient
    ):
        """Should restart setup when a pending setup already exists."""
        headers = await _get_auth_headers(client)

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        first_payload = response.json()

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        second_payload = response.json()
        assert second_payload["qr_code"] != first_payload["qr_code"]

    async def test_reset_2fa_pending_setup_allows_new_setup(
        self, client: AsyncClient
    ):
        """Reset endpoint should clear pending setup and allow a new setup."""
        headers = await _get_auth_headers(client)

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

        response = await client.post(
            "/api/auth/2fa/reset",
            headers=headers,
        )
        assert response.status_code == 204

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

    async def test_reset_2fa_fails_if_enabled(
        self, client: AsyncClient, db_session
    ):
        """Reset endpoint should reject resetting when 2FA is already enabled."""
        import pyotp

        headers = await _get_auth_headers(client)

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None

        totp = pyotp.TOTP(record.secret)
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp.now()},
            headers=headers,
        )
        assert response.status_code == 204

        response = await client.post(
            "/api/auth/2fa/reset",
            headers=headers,
        )
        assert response.status_code == 409
        assert "Disable 2FA before resetting setup" in response.json()["detail"]

    async def test_setup_2fa_fails_if_already_enabled(
        self, client: AsyncClient, db_session
    ):
        """Should reject setup if 2FA already enabled."""
        import pyotp
        
        headers = await _get_auth_headers(client)
        
        # Setup 2FA first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        secret = record.secret
        
        # Enable it
        totp = pyotp.TOTP(secret)
        totp_code = totp.now()
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp_code},
            headers=headers,
        )
        assert response.status_code == 204
        
        # Try to setup again
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 409
        assert "already enabled" in response.json()["detail"]

    async def test_enable_2fa_requires_valid_token(
        self, client: AsyncClient
    ):
        """Should reject invalid TOTP tokens."""
        headers = await _get_auth_headers(client)
        
        # Setup first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        
        # Try to enable with wrong code
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": "000000"},
            headers=headers,
        )
        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    async def test_enable_2fa_with_valid_token(
        self, client: AsyncClient, db_session
    ):
        """Should enable 2FA with valid TOTP token."""
        import pyotp
        
        headers = await _get_auth_headers(client)
        
        # Setup
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        secret = record.secret
        
        # Generate valid code
        totp = pyotp.TOTP(secret)
        code = totp.now()
        
        # Enable with valid code
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": code},
            headers=headers,
        )
        assert response.status_code == 204
        
        # Verify it's enabled
        response = await client.get(
            "/api/auth/2fa/status",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is True

    async def test_disable_2fa_requires_valid_token(
        self, client: AsyncClient, db_session
    ):
        """Should reject invalid TOTP when disabling."""
        import pyotp
        
        headers = await _get_auth_headers(client)
        
        # Setup and enable first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        secret = record.secret
        totp = pyotp.TOTP(secret)
        
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp.now()},
            headers=headers,
        )
        assert response.status_code == 204

        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db_session.commit()

        # Try to disable with wrong code
        response = await client.post(
            "/api/auth/2fa/disable",
            json={"token": "000000"},
            headers=headers,
        )
        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    async def test_disable_2fa_with_valid_token(
        self, client: AsyncClient, db_session
    ):
        """Should disable 2FA with valid TOTP token."""
        import pyotp
        
        headers = await _get_auth_headers(client)
        
        # Setup and enable
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        secret = record.secret
        totp = pyotp.TOTP(secret)
        
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp.now()},
            headers=headers,
        )
        assert response.status_code == 204
        
        # Verify enabled
        response = await client.get(
            "/api/auth/2fa/status",
            headers=headers,
        )
        assert response.json()["enabled"] is True

        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db_session.commit()

        # Disable with valid code
        response = await client.post(
            "/api/auth/2fa/disable",
            json={"token": totp.now()},
            headers=headers,
        )
        assert response.status_code == 204
        
        # Verify disabled
        response = await client.get(
            "/api/auth/2fa/status",
            headers=headers,
        )
        assert response.json()["enabled"] is False

    async def test_setup_2fa_allowed_again_after_disable(
        self, client: AsyncClient, db_session
    ):
        """After disabling 2FA, user should be able to start setup again."""
        import pyotp

        headers = await _get_auth_headers(client)

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        totp = pyotp.TOTP(record.secret)

        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp.now()},
            headers=headers,
        )
        assert response.status_code == 204

        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db_session.commit()

        response = await client.post(
            "/api/auth/2fa/disable",
            json={"token": totp.now()},
            headers=headers,
        )
        assert response.status_code == 204

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

    async def test_2fa_endpoints_require_auth(self, client: AsyncClient):
        """2FA endpoints should require authentication."""
        # No token — OAuth2 returns 401, not 403
        response = await client.get("/api/auth/2fa/status")
        assert response.status_code == 401
        
        response = await client.post("/api/auth/2fa/setup")
        assert response.status_code == 401

        response = await client.post("/api/auth/2fa/reset")
        assert response.status_code == 401
        
        response = await client.post("/api/auth/2fa/enable", json={"token": "000000"})
        assert response.status_code == 401
        
        response = await client.post("/api/auth/2fa/disable", json={"token": "000000"})
        assert response.status_code == 401

    async def test_backup_codes_stored_on_setup(
        self, client: AsyncClient, db_session
    ):
        """Backup codes should be stored in database."""
        headers = await _get_auth_headers(client)

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        backup_codes = response.json()["backup_codes"]

        # Check database
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        assert record.is_enabled is False

        stored_codes = json.loads(record.backup_codes)
        assert stored_codes != backup_codes
        assert len(stored_codes) == len(backup_codes)
        assert all(isinstance(x, str) for x in stored_codes)
        assert all(x.startswith("$2") for x in stored_codes)  # bcrypt hashes

    async def test_totp_secret_encrypted_at_rest(
        self, client: AsyncClient, db_session
    ):
        """TOTP secret should not be stored as plaintext in the database."""
        headers = await _get_auth_headers(client)

        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

        query = await db_session.execute(
            text("SELECT secret FROM admin_totp_secrets WHERE username = 'admin'")
        )
        raw_secret = query.scalar_one()

        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        assert raw_secret != record.secret
        assert raw_secret.startswith("v1:")
