"""
tests/test_audit_2fa_events.py — Test audit events for 2FA operations.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from backend.models.audit import AuditLog
from backend.services.audit import (
    ACTION_2FA_FAILED,
    ACTION_BACKUP_CODE_USED,
)


@pytest.mark.asyncio
class TestAudit2FAEvents:
    """Test audit logging for 2FA operations."""

    async def test_failed_2fa_attempt_logged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Should log failed 2FA attempts."""
        from backend.services.totp import TOTPService
        from backend.models.auth import AdminTOTPSecret

        headers = await _get_auth_headers(client)

        # Setup and enable 2FA
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200
        setup_data = response.json()

        # Manually enable 2FA in database
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        record.is_enabled = True
        await db_session.commit()

        # Clear any existing audit logs
        await db_session.execute(delete(AuditLog))
        await db_session.commit()

        # Now logout and login with wrong 2FA code
        await client.post("/api/auth/logout", headers=headers)

        # Login with credentials + invalid 2FA code (2FA now enabled)
        login_response = await client.post(
            "/api/auth/token",
            data={
                "username": "admin",
                "password": "admin",
                "totp_code": "000000",
            },
        )
        assert login_response.status_code == 401

        # Check audit log
        query = select(AuditLog).where(AuditLog.action == ACTION_2FA_FAILED)
        result = await db_session.execute(query)
        audit_entries = result.scalars().all()
        assert len(audit_entries) > 0, "2FA failed attempt should be logged"

    async def test_backup_code_usage_logged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Should log backup code usage."""
        from backend.services.totp import TOTPService
        from backend.models.auth import AdminTOTPSecret

        headers = await _get_auth_headers(client)

        # Setup 2FA
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

        # Manually enable 2FA in database and save a backup code
        record = await db_session.get(AdminTOTPSecret, "admin")
        assert record is not None
        record.is_enabled = True

        # Generate test backup codes and get raw codes
        test_codes = ["AAAA-BBBB", "CCCC-DDDD"]
        record.backup_codes = TOTPService.codes_to_json(test_codes, hashed=True)
        await db_session.commit()

        # Clear audit logs
        await db_session.execute(delete(AuditLog))
        await db_session.commit()

        # Logout and login with backup code
        await client.post("/api/auth/logout", headers=headers)

        login_response = await client.post(
            "/api/auth/token",
            data={
                "username": "admin",
                "password": "admin",
                "totp_code": "AAAA-BBBB",  # Backup code
            },
        )
        assert login_response.status_code == 200

        # Check audit log for backup code usage
        query = select(AuditLog).where(AuditLog.action == ACTION_BACKUP_CODE_USED)
        result = await db_session.execute(query)
        audit_entries = result.scalars().all()
        assert len(audit_entries) > 0, "Backup code usage should be logged"

    async def test_successful_2fa_not_logged_as_failure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Successful 2FA should not create a failure audit log."""
        headers = await _get_auth_headers(client)

        # Setup 2FA
        response = await client.post(
            "/api/auth/2fa/setup",
            headers=headers,
        )
        assert response.status_code == 200

        # Clear audit logs
        await db_session.execute(delete(AuditLog))
        await db_session.commit()

        # Check that no 2FA_FAILED events exist yet
        query = select(AuditLog).where(AuditLog.action == ACTION_2FA_FAILED)
        result = await db_session.execute(query)
        initial_entries = result.scalars().all()
        initial_count = len(initial_entries)

        # Make a valid login (no 2FA required yet since it's not enabled)
        response = await client.post(
            "/api/auth/token",
            data={"username": "admin", "password": "admin"},
        )
        assert response.status_code == 200

        # Check no 2FA_FAILED events were created
        query = select(AuditLog).where(AuditLog.action == ACTION_2FA_FAILED)
        result = await db_session.execute(query)
        final_entries = result.scalars().all()
        final_count = len(final_entries)
        assert final_count == initial_count, "No 2FA_FAILED events should be created on successful login"


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
