"""
routers/auth_2fa.py — Two-Factor Authentication endpoints

Endpoints
---------
GET  /api/auth/2fa/status       Check if 2FA is enabled
POST /api/auth/2fa/setup        Generate TOTP secret and QR code
POST /api/auth/2fa/reset        Reset pending 2FA setup
POST /api/auth/2fa/enable       Verify and enable 2FA
POST /api/auth/2fa/disable      Disable 2FA (requires verification)
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.auth import AdminTOTPSecret
from backend.services.audit import (
    ACTION_2FA_ENABLED,
    ACTION_2FA_DISABLED,
    ACTION_2FA_SETUP_INITIATED,
    ACTION_2FA_SETUP_RESET,
    ACTION_2FA_VERIFICATION_FAILED,
    get_client_ip,
    write_audit,
)
from backend.services.rate_limit import get_limiter
from backend.services.totp import TOTPService
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/auth/2fa", tags=["auth"])

_MIN_2FA_DISABLE_AGE = timedelta(minutes=2)

# -- Pydantic schemas ----------------------------------------------------------

class TOTPSetupResponse(BaseModel):
    """Response with QR code and one-time backup codes."""
    qr_code: str
    backup_codes: list[str]


class TOTPVerifyIn(BaseModel):
    """Request to verify and enable/disable 2FA."""
    token: str


class TwoFAStatusOut(BaseModel):
    """Response indicating if 2FA is enabled."""
    enabled: bool


# -- Routes --------------------------------------------------------------------

@router.get("/status", response_model=TwoFAStatusOut)
async def get_2fa_status(
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if 2FA is enabled for the current user."""
    totp_record = await db.get(AdminTOTPSecret, current_user)
    
    if totp_record and totp_record.is_enabled:
        return TwoFAStatusOut(enabled=True)
        
    return TwoFAStatusOut(enabled=False)


@router.post("/setup", response_model=TOTPSetupResponse)
async def setup_2fa(
    request: Request,
    response: Response,
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate new TOTP secret and QR code.

    User should scan the QR code with Google Authenticator, then call
    /2fa/enable with the 6-digit code.
    """
    # Rate limit: max 6 setup requests per minute from a single IP
    limiter = get_limiter()
    limiter.check_limit(request, endpoint="/auth/2fa/setup", requests_per_minute=6)
    
    # Check if already enabled or setup already pending
    existing = await db.get(AdminTOTPSecret, current_user)
    if existing and existing.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is already enabled for this user",
        )
    if existing and not existing.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA setup already in progress. Complete setup or reset it.",
        )

    # Generate new secret and backup codes
    secret = TOTPService.generate_secret()
    backup_codes = TOTPService.generate_backup_codes()

    # Generate QR code
    settings = get_settings()
    issuer = f"CloudShell ({settings.environment})"
    provisioning_uri = TOTPService.get_provisioning_uri(secret, current_user, issuer=issuer)
    qr_code_base64 = TOTPService.generate_qr_code(provisioning_uri)

    # Store secret (not yet enabled)
    totp_record = AdminTOTPSecret(
        username=current_user,
        secret=secret,
        is_enabled=False,
    backup_codes=TOTPService.codes_to_json(backup_codes, hashed=True),
    )
    db.add(totp_record)
    await db.commit()

    # Log 2FA setup initiation
    await write_audit(
        db, current_user, ACTION_2FA_SETUP_INITIATED,
        detail="User initiated 2FA setup (secret generated, awaiting verification)",
        source_ip=get_client_ip(request),
    )

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return TOTPSetupResponse(
        qr_code=qr_code_base64,
        backup_codes=backup_codes,
    )


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_2fa_setup(
    request: Request,
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset a pending 2FA setup.

    Only pending setup records (`is_enabled=False`) can be reset.
    Enabled 2FA must be disabled via /2fa/disable.
    """
    limiter = get_limiter()
    limiter.check_limit(request, endpoint="/auth/2fa/reset", requests_per_minute=10)

    totp_record = await db.get(AdminTOTPSecret, current_user)
    if not totp_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="2FA setup not found",
        )

    if totp_record.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is enabled. Disable 2FA before resetting setup.",
        )

    await db.delete(totp_record)
    await db.commit()

    await write_audit(
        db, current_user, ACTION_2FA_SETUP_RESET,
        detail="User reset pending 2FA setup",
        source_ip=get_client_ip(request),
    )


@router.post("/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_2fa(
    request: Request,
    body: TOTPVerifyIn,
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify TOTP token and enable 2FA.

    Must call /2fa/setup first to generate a secret.
    """
    # Rate limit: max 30 enable attempts per minute from a single IP
    limiter = get_limiter()
    limiter.check_limit(request, endpoint="/auth/2fa/enable", requests_per_minute=30)
    
    totp_record = await db.get(AdminTOTPSecret, current_user)
    if not totp_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="2FA setup not found. Call /2fa/setup first.",
        )

    if totp_record.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is already enabled",
        )

    # Verify the token
    if not TOTPService.verify_token(totp_record.secret, body.token):
        # Log failed verification attempt during setup
        await write_audit(
            db, current_user, ACTION_2FA_VERIFICATION_FAILED,
            detail="Invalid or expired token during 2FA setup verification",
            source_ip=get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Enable 2FA
    totp_record.is_enabled = True
    await db.commit()

    await write_audit(
        db, current_user, ACTION_2FA_ENABLED,
        detail="Two-factor authentication enabled (setup verified)",
        source_ip=get_client_ip(request),
    )


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_2fa(
    request: Request,
    body: TOTPVerifyIn,
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disable 2FA.

    Requires a valid TOTP token for security.
    """
    # Rate limit: max 30 disable attempts per minute from a single IP
    limiter = get_limiter()
    limiter.check_limit(request, endpoint="/auth/2fa/disable", requests_per_minute=30)
    
    totp_record = await db.get(AdminTOTPSecret, current_user)
    if not totp_record or not totp_record.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="2FA is not enabled",
        )

    now = datetime.now(timezone.utc)
    if (now - totp_record.created_at) < _MIN_2FA_DISABLE_AGE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="2FA disable is temporarily blocked after setup",
        )

    # Verify the token
    if not TOTPService.verify_token(totp_record.secret, body.token):
        # Log failed verification attempt during disable
        await write_audit(
            db, current_user, ACTION_2FA_VERIFICATION_FAILED,
            detail="Invalid or expired token during 2FA disable request",
            source_ip=get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Disable 2FA
    totp_record.is_enabled = False
    await db.commit()

    await write_audit(
        db, current_user, ACTION_2FA_DISABLED,
        detail="Two-factor authentication disabled",
        source_ip=get_client_ip(request),
    )
