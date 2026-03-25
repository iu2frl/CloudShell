"""
tests/test_auth_2fa_direct.py — Unit tests for the 2FA router functions directly.

By calling the router functions directly rather than routing through the test client
and ASGITransport, we get 100% accurate coverage tracking from coverage.py because
the execution happens purely in the main test thread.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response
from fastapi import HTTPException

from backend.routers.auth_2fa import (
    get_2fa_status,
    setup_2fa,
    reset_2fa_setup,
    enable_2fa,
    disable_2fa,
    TOTPVerifyIn,
)
from backend.models.auth import AdminTOTPSecret


async def test_get_2fa_status_direct(db_session):
    """Directly test getting 2FA status."""
    # Setup mock record disabled
    db_session.add(AdminTOTPSecret(username="admin", secret="ABCD", is_enabled=False))
    await db_session.commit()

    resp = await get_2fa_status(current_user="admin", db=db_session)
    assert resp.enabled is False

    # Setup mock record enabled
    record = await db_session.get(AdminTOTPSecret, "admin")
    record.is_enabled = True
    await db_session.commit()

    resp = await get_2fa_status(current_user="admin", db=db_session)
    assert resp.enabled is True

    # Setup missing record
    resp = await get_2fa_status(current_user="nonexistent", db=db_session)
    assert resp.enabled is False


async def test_setup_2fa_direct(db_session):
    """Directly test 2FA setup generation."""
    from unittest.mock import MagicMock

    # Mock request for rate limiting
    request = MagicMock()
    request.client = MagicMock(host="127.0.0.1")
    request.headers = {}

    resp = await setup_2fa(
        request=request,
        response=Response(),
        current_user="admin",
        db=db_session,
    )

    assert resp.qr_code.startswith("data:image/")
    assert len(resp.backup_codes) == 10

    # Pending setup should be restartable
    second = await setup_2fa(
        request=request,
        response=Response(),
        current_user="admin",
        db=db_session,
    )
    assert second.qr_code.startswith("data:image/")
    assert second.qr_code != resp.qr_code


async def test_setup_2fa_uses_environment_aware_issuer_direct(db_session):
    """Setup should pass environment-aware issuer to provisioning URI helper."""
    from unittest.mock import MagicMock

    request = MagicMock()
    request.client = MagicMock(host="127.0.0.1")
    request.headers = {}

    with patch("backend.routers.auth_2fa.get_settings") as mock_get_settings, patch(
        "backend.routers.auth_2fa.TOTPService.get_provisioning_uri"
    ) as mock_get_provisioning_uri:
        mock_get_settings.return_value = MagicMock(environment="production")
        mock_get_provisioning_uri.return_value = "otpauth://dummy"

        await setup_2fa(
            request=request,
            response=Response(),
            current_user="admin",
            db=db_session,
        )

        _, kwargs = mock_get_provisioning_uri.call_args
        assert kwargs["issuer"] == "CloudShell (production)"


async def test_reset_2fa_setup_direct(db_session):
    """Directly test pending 2FA setup reset flow."""
    from unittest.mock import MagicMock

    request = MagicMock()
    request.client = MagicMock(host="127.0.0.1")
    request.headers = {}

    # No setup should return not found
    with pytest.raises(HTTPException) as exc:
        await reset_2fa_setup(request=request, current_user="admin", db=db_session)
    assert exc.value.status_code == 404

    # Pending setup can be reset
    await setup_2fa(
        request=request,
        response=Response(),
        current_user="admin",
        db=db_session,
    )
    await reset_2fa_setup(request=request, current_user="admin", db=db_session)

    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is None

    # Enabled setup cannot be reset
    db_session.add(AdminTOTPSecret(username="admin", secret="ABCD", is_enabled=True))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await reset_2fa_setup(request=request, current_user="admin", db=db_session)
    assert exc.value.status_code == 409

    # Test conflict when already enabled
    record = await db_session.get(AdminTOTPSecret, "admin")
    record.is_enabled = True
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await setup_2fa(
            request=request,
            response=Response(),
            current_user="admin",
            db=db_session,
        )
    assert exc.value.status_code == 409


async def test_enable_2fa_direct(db_session):
    """Directly test 2FA enable flow."""
    # Mock the request for audit log IP
    mock_request = AsyncMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"

    # Test not found
    with pytest.raises(HTTPException) as exc:
        await enable_2fa(request=mock_request, body=TOTPVerifyIn(token="123456"), current_user="admin", db=db_session)
    assert exc.value.status_code == 404

    # Add disabled record
    with patch("backend.routers.auth_2fa.TOTPService.verify_token", return_value=False):
        db_session.add(AdminTOTPSecret(username="admin", secret="ABCD", is_enabled=False))
        await db_session.commit()

        # Test invalid token
        with pytest.raises(HTTPException) as exc:
            await enable_2fa(request=mock_request, body=TOTPVerifyIn(token="000000"), current_user="admin", db=db_session)
        assert exc.value.status_code == 401

    # Test successful enable
    with patch("backend.routers.auth_2fa.TOTPService.verify_token", return_value=True):
        await enable_2fa(request=mock_request, body=TOTPVerifyIn(token="123456"), current_user="admin", db=db_session)

    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record.is_enabled is True

    # Test already enabled
    with pytest.raises(HTTPException) as exc:
        await enable_2fa(request=mock_request, body=TOTPVerifyIn(token="123456"), current_user="admin", db=db_session)
    assert exc.value.status_code == 409


async def test_disable_2fa_direct(db_session):
    """Directly test 2FA disable flow."""
    mock_request = AsyncMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"

    # Test not found
    with pytest.raises(HTTPException) as exc:
        await disable_2fa(request=mock_request, body=TOTPVerifyIn(token="123456"), current_user="admin", db=db_session)
    assert exc.value.status_code == 404

    # Add disabled record (which behaves like not found for disable)
    db_session.add(AdminTOTPSecret(username="admin", secret="ABCD", is_enabled=False))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await disable_2fa(request=mock_request, body=TOTPVerifyIn(token="123456"), current_user="admin", db=db_session)
    assert exc.value.status_code == 404

    # Enable record and make it old enough for disable policy
    record = await db_session.get(AdminTOTPSecret, "admin")
    record.is_enabled = True
    record.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()

    # Test invalid token
    with patch("backend.routers.auth_2fa.TOTPService.verify_token", return_value=False):
        with pytest.raises(HTTPException) as exc:
            await disable_2fa(request=mock_request, body=TOTPVerifyIn(token="000000"), current_user="admin", db=db_session)
        assert exc.value.status_code == 401

    # Test successful disable
    with patch("backend.routers.auth_2fa.TOTPService.verify_token", return_value=True):
        await disable_2fa(request=mock_request, body=TOTPVerifyIn(token="123456"), current_user="admin", db=db_session)

    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is None


async def test_disable_2fa_direct_handles_naive_created_at(db_session):
    """Disable flow should tolerate naive timestamps loaded from SQLite."""
    mock_request = AsyncMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"

    db_session.add(AdminTOTPSecret(username="admin", secret="ABCD", is_enabled=True))
    await db_session.commit()

    record = await db_session.get(AdminTOTPSecret, "admin")
    assert record is not None
    record.created_at = datetime(2000, 1, 1, 0, 0, 0)
    await db_session.commit()

    with patch("backend.routers.auth_2fa.TOTPService.verify_token", return_value=True):
        await disable_2fa(
            request=mock_request,
            body=TOTPVerifyIn(token="123456"),
            current_user="admin",
            db=db_session,
        )

    updated = await db_session.get(AdminTOTPSecret, "admin")
    assert updated is None
