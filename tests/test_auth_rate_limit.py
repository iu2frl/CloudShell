"""
tests/test_auth_rate_limit.py — Integration tests for auth endpoint rate limiting.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestAuthRateLimit:
    """Test rate limiting on authentication endpoints."""

    async def test_login_rate_limit(self, client: AsyncClient):
        """Should rate limit login attempts."""
        # Make 10 login attempts (at limit)
        for _ in range(10):
            response = await client.post(
                "/api/auth/token",
                data={"username": "admin", "password": "wrong"},
            )
            # Can be 401 (auth fail) or other, but not 429
            assert response.status_code != 429

        # 11th attempt should be rate limited (429)
        response = await client.post(
            "/api/auth/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.text

    async def test_2fa_setup_rate_limit(self, client: AsyncClient):
        """Should rate limit 2FA setup attempts."""
        headers = await _get_auth_headers(client)

        # Make 6 setup attempts (at limit)
        for _ in range(6):
            response = await client.post(
                "/api/auth/2fa/setup",
                headers=headers,
            )
            # 200 or conflict, but not 429
            assert response.status_code != 429

        # 7th attempt should be rate limited (429)
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.text

    async def test_2fa_enable_rate_limit(self, client: AsyncClient):
        """Should rate limit 2FA enable attempts."""
        headers = await _get_auth_headers(client)

        # Setup 2FA first
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

        # Make 30 enable attempts (at limit) with invalid code
        for _ in range(30):
            response = await client.post(
                "/api/auth/2fa/enable",
                json={"token": "000000"},
                headers=headers,
            )
            # Should get 401 (invalid token), not 429
            assert response.status_code != 429

        # 31st attempt should be rate limited (429)
        response = await client.post(
            "/api/auth/2fa/enable",
            json={"token": "000000"},
            headers=headers,
        )
        assert response.status_code == 429

    async def test_2fa_disable_rate_limit(self, client: AsyncClient):
        """Should rate limit 2FA disable attempts."""
        headers = await _get_auth_headers(client)

        # Make 30 disable attempts (at limit) with invalid code
        for _ in range(30):
            response = await client.post(
                "/api/auth/2fa/disable",
                json={"token": "000000"},
                headers=headers,
            )
            # Should get 404 (not enabled), not 429
            assert response.status_code != 429

        # 31st attempt should be rate limited (429)
        response = await client.post(
            "/api/auth/2fa/disable",
            json={"token": "000000"},
            headers=headers,
        )
        assert response.status_code == 429

    async def test_rate_limit_per_ip(self, client: AsyncClient):
        """Rate limits should be per IP address."""
        # First client at default IP
        response1 = await client.post(
            "/api/auth/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert response1.status_code != 429

        # Simulate different IP via x-forwarded-for header
        headers = {"x-forwarded-for": "10.0.0.2"}
        response2 = await client.post(
            "/api/auth/token",
            data={"username": "admin", "password": "wrong"},
            headers=headers,
        )
        # Different IP should have its own limit
        assert response2.status_code != 429


async def _get_auth_headers(client: AsyncClient) -> dict:
    """Helper to get valid auth headers."""
    response = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
    )
    if response.status_code != 200:
        raise ValueError(f"Failed to authenticate: {response.text}")
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
