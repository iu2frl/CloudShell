"""
tests/test_auth_2fa_api.py — Integration tests for 2FA endpoints.
"""
import json

import pytest
from httpx import AsyncClient

from backend.models.auth import AdminTOTPSecret
from backend.services.totp import TOTPService


@pytest.mark.asyncio
class TestTwoFactorAuthAPI:
    """Test 2FA API endpoints."""

    async def test_get_2fa_status_disabled(self, client: AsyncClient, token: str):
        """Should return enabled=false when 2FA not set up."""
        response = await client.get(
            "/api/auth/2fa/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

    async def test_setup_2fa_generates_qr_code(self, client: AsyncClient, token: str):
        """Setup endpoint should return QR code, secret, and backup codes."""
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "qr_code" in data
        assert data["qr_code"].startswith("data:image/png;base64,")
        assert "secret" in data
        assert len(data["secret"]) == 32
        assert "backup_codes" in data
        assert len(data["backup_codes"]) == 10
        # Codes should be in format XXXX-XXXX
        for code in data["backup_codes"]:
            assert len(code) == 9
            assert code[4] == "-"

    async def test_setup_2fa_fails_if_already_enabled(
        self, client: AsyncClient, token: str, db
    ):
        """Should reject setup if 2FA already enabled."""
        import pyotp
        
        # Setup 2FA first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        secret = response.json()["secret"]
        
        # Enable it
        totp = pyotp.TOTP(secret)
        totp_code = totp.now()
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp_code},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204
        
        # Try to setup again
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409
        assert "already enabled" in response.json()["detail"]

    async def test_enable_2fa_requires_valid_token(
        self, client: AsyncClient, token: str
    ):
        """Should reject invalid TOTP tokens."""
        # Setup first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        
        # Try to enable with wrong code
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": "000000"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    async def test_enable_2fa_with_valid_token(
        self, client: AsyncClient, token: str
    ):
        """Should enable 2FA with valid TOTP token."""
        import pyotp
        
        # Setup
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        secret = response.json()["secret"]
        
        # Generate valid code
        totp = pyotp.TOTP(secret)
        code = totp.now()
        
        # Enable with valid code
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": code},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204
        
        # Verify it's enabled
        response = await client.get(
            "/api/auth/2fa/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is True

    async def test_disable_2fa_requires_valid_token(
        self, client: AsyncClient, token: str
    ):
        """Should reject invalid TOTP when disabling."""
        import pyotp
        
        # Setup and enable first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        secret = response.json()["secret"]
        totp = pyotp.TOTP(secret)
        
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp.now()},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204
        
        # Try to disable with wrong code
        response = await client.post(
            "/api/auth/2fa/disable",
            json={"token": "000000"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    async def test_disable_2fa_with_valid_token(
        self, client: AsyncClient, token: str
    ):
        """Should disable 2FA with valid TOTP token."""
        import pyotp
        
        # Setup and enable
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        secret = response.json()["secret"]
        totp = pyotp.TOTP(secret)
        
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": totp.now()},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204
        
        # Verify enabled
        response = await client.get(
            "/api/auth/2fa/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["enabled"] is True
        
        # Disable with valid code
        response = await client.post(
            "/api/auth/2fa/disable",
            json={"token": totp.now()},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204
        
        # Verify disabled
        response = await client.get(
            "/api/auth/2fa/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["enabled"] is False

    async def test_2fa_endpoints_require_auth(self, client: AsyncClient):
        """2FA endpoints should require authentication."""
        # No token
        response = await client.get("/api/auth/2fa/status")
        assert response.status_code == 403
        
        response = await client.post("/api/auth/2fa/setup")
        assert response.status_code == 403
        
        response = await client.post("/api/auth/2fa/enable", json={"token": "000000"})
        assert response.status_code == 403
        
        response = await client.post("/api/auth/2fa/disable", json={"token": "000000"})
        assert response.status_code == 403

    async def test_backup_codes_stored_on_setup(
        self, client: AsyncClient, token: str, db
    ):
        """Backup codes should be stored in database."""
        response = await client.post(
            "/api/auth/2fa/setup",
            headers={"Authorization": f"Bearer {token}"},
        )
        backup_codes = response.json()["backup_codes"]
        
        # Check database
        record = await db.get(AdminTOTPSecret, "admin")
        assert record is not None
        assert record.is_enabled is False
        
        stored_codes = json.loads(record.backup_codes)
        assert stored_codes == backup_codes
