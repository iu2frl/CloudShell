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

    # Pending setup should now conflict
    with pytest.raises(HTTPException) as exc:
        await setup_2fa(
            request=request,
            response=Response(),
            current_user="admin",
            db=db_session,
        )
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
    assert record.is_enabled is False
