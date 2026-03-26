"""
routers/auth.py — Authentication & session management

Endpoints
---------
POST /api/auth/token            Login → JWT
POST /api/auth/refresh          Extend a valid (non-expired) session
POST /api/auth/logout           Revoke the current token
GET  /api/auth/me               Whoami + token expiry info
POST /api/auth/change-password  Change admin password (persisted in DB)
"""
import secrets
import uuid
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.auth import AdminCredential, RevokedToken, AdminTOTPSecret, AdminTrustedDevice
from backend.services.audit import (
    ACTION_LOGIN,
    ACTION_LOGOUT,
    ACTION_PASSWORD_CHANGED,
    ACTION_2FA_FAILED,
    ACTION_BACKUP_CODE_USED,
    ACTION_BACKUP_CODE_LOW,
    get_client_ip,
    write_audit,
)
from backend.services.rate_limit import get_limiter

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

ALGORITHM = "HS256"
REMEMBER_DEVICE_DAYS = 30
REMEMBER_DEVICE_MAX_AGE_SECONDS = REMEMBER_DEVICE_DAYS * 24 * 60 * 60
REMEMBER_DEVICE_COOKIE_NAME = "cloudshell_trusted_device"
AUTH_COOKIE_NAME = "cloudshell_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 8 * 60 * 60  # Will be overridden by settings.token_ttl_hours


def _get_boot_id() -> str:
    """Return the current process boot ID (imported lazily to avoid circular imports)."""
    from backend.main import BOOT_ID  # noqa: PLC0415
    return BOOT_ID


# -- Pydantic schemas ----------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_at: datetime   # ISO-8601 UTC, for the frontend countdown
    backup_codes_warning: str | None = None  # Warning if backup codes running low


class MeOut(BaseModel):
    username: str
    expires_at: datetime


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


# -- Internal helpers ----------------------------------------------------------

def _make_token(username: str) -> tuple[str, datetime, str]:
    """Return (encoded_jwt, expiry_datetime, jti)."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours)
    jti = str(uuid.uuid4())
    payload = {"sub": username, "exp": expire, "jti": jti, "bid": _get_boot_id()}
    encoded = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return encoded, expire, jti


async def _get_hashed_password(username: str, db: AsyncSession) -> str | None:
    """Return the bcrypt hash from DB, or None if no DB record yet."""
    row = await db.get(AdminCredential, username)
    return row.hashed_password if row else None


async def _verify_credentials(username: str, password: str, db: AsyncSession) -> bool:
    settings = get_settings()
    if username != settings.admin_user:
        return False
    db_hash = await _get_hashed_password(username, db)
    if db_hash:
        return bcrypt.checkpw(password.encode(), db_hash.encode())
    # Fall back to plain env-var comparison on first boot (before any password change)
    return secrets.compare_digest(password, settings.admin_password)


async def _is_revoked(jti: str, db: AsyncSession) -> bool:
    row = await db.get(RevokedToken, jti)
    return row is not None


async def _prune_expired_tokens(db: AsyncSession) -> None:
    """Delete rows that expired before now — housekeeping, best-effort."""
    now = datetime.now(timezone.utc)
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
    await db.commit()


def _hash_trusted_device_token(raw_token: str) -> str:
    """Return a stable hash for trusted-device token storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _is_truthy_form_flag(value: str | None) -> bool:
    """Parse common truthy values from form fields."""
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _is_secure_request(request: Request) -> bool:
    """Return True when the original client-facing request used HTTPS.

    Trust X-Forwarded-Proto only when the direct peer is listed in
    TRUSTED_PROXIES.
    """
    if request.url.scheme == "https":
        return True

    peer_ip = request.client.host if request.client else "unknown"
    settings = get_settings()
    trusted_proxies = {
        item.strip() for item in settings.trusted_proxies.split(",") if item.strip()
    }

    if peer_ip in trusted_proxies:
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto:
            first_hop_proto = forwarded_proto.split(",")[0].strip().lower()
            return first_hop_proto == "https"

    return False


async def _prune_expired_trusted_devices(db: AsyncSession) -> None:
    """Delete expired trusted-device rows."""
    now = datetime.now(timezone.utc)
    await db.execute(delete(AdminTrustedDevice).where(AdminTrustedDevice.expires_at < now))
    await db.commit()


async def _is_trusted_device(
    username: str,
    raw_token: str | None,
    db: AsyncSession,
) -> bool:
    """Return True when the provided trusted-device cookie is valid."""
    if not raw_token:
        return False

    token_hash = _hash_trusted_device_token(raw_token)
    record = await db.get(AdminTrustedDevice, token_hash)
    if not record:
        return False

    now = datetime.now(timezone.utc)
    expiry = record.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if record.username != username or expiry < now:
        await db.delete(record)
        await db.commit()
        return False

    return True


async def _remember_trusted_device(
    username: str,
    response: Response,
    request: Request,
    db: AsyncSession,
) -> None:
    """Issue a new trusted-device cookie and persist its hashed token."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_trusted_device_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REMEMBER_DEVICE_DAYS)

    db.add(AdminTrustedDevice(token_hash=token_hash, username=username, expires_at=expires_at))
    await db.commit()

    response.set_cookie(
        key=REMEMBER_DEVICE_COOKIE_NAME,
        value=raw_token,
        max_age=REMEMBER_DEVICE_MAX_AGE_SECONDS,
        expires=REMEMBER_DEVICE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def _set_auth_cookie(
    response: Response,
    token: str,
    request: Request,
    ttl_hours: int,
) -> None:
    """Set the auth token as a secure httpOnly cookie."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=ttl_hours * 60 * 60,
        expires=ttl_hours * 60 * 60,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


# -- Shared dependency ---------------------------------------------------------

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> str:
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        if username is None or jti is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    if payload.get("bid") != _get_boot_id():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated by server restart",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if await _is_revoked(jti, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


# Also expose a version that returns the full payload (used by /refresh)
async def _get_payload(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise credentials_exception from exc

    jti: str | None = payload.get("jti")
    if not jti:
        raise credentials_exception
    if payload.get("bid") != _get_boot_id():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated by server restart",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if await _is_revoked(jti, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# -- Routes --------------------------------------------------------------------

@router.post("/token", response_model=Token)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str | None = Form(default=None),
    remember_device: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Rate limit: max 10 login attempts per minute per account+IP
    limiter = get_limiter()
    limiter.check_limit(
        request,
        endpoint="/auth/token",
        account=form_data.username,
        requests_per_minute=10,
    )
    
    if not await _verify_credentials(form_data.username, form_data.password, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    totp_record = await db.get(AdminTOTPSecret, form_data.username)
    backup_codes_warning = None
    trusted_cookie = request.cookies.get(REMEMBER_DEVICE_COOKIE_NAME)
    
    if totp_record and totp_record.is_enabled:
        await _prune_expired_trusted_devices(db)
        is_trusted_device = await _is_trusted_device(form_data.username, trusted_cookie, db)

        if is_trusted_device:
            totp_code = None

        from backend.services.totp import TOTPService, DeprecatedBackupCodeFormatError
        if not totp_code and not is_trusted_device:
            # We return a specific error that the frontend can intercept 
            # to know that 2FA is required.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="2FA_REQUIRED",
            )

        if not is_trusted_device:
            is_valid_totp = TOTPService.verify_token(totp_record.secret, totp_code)
            backup_code_used = False

            if not is_valid_totp:
                # Check backup codes if TOTPs fail.
                # Backup codes are stored hashed; on success we consume (remove) the used one.
                try:
                    ok, updated_json = TOTPService.verify_and_consume_backup_code(
                        getattr(totp_record, "backup_codes", None),
                        totp_code,
                    )
                except DeprecatedBackupCodeFormatError as exc:
                    await write_audit(
                        db, form_data.username, ACTION_2FA_FAILED,
                        detail="Deprecated backup-code hash detected; regeneration required",
                        source_ip=get_client_ip(request),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Backup codes must be regenerated",
                    ) from exc

                if ok:
                    totp_record.backup_codes = updated_json
                    await db.commit()
                    is_valid_totp = True
                    backup_code_used = True
                    # Track remaining backup codes for audit and warnings
                    remaining_codes = len(TOTPService.codes_from_json(updated_json))

            if not is_valid_totp:
                # Log failed 2FA attempt
                await write_audit(
                    db, form_data.username, ACTION_2FA_FAILED,
                    detail="Invalid or expired 2FA code during login",
                    source_ip=get_client_ip(request),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid 2FA code",
                )

            # If backup code was used, log it with remaining count and warn if low
            if backup_code_used:
                await write_audit(
                    db, form_data.username, ACTION_BACKUP_CODE_USED,
                    detail=f"User authenticated using backup code ({remaining_codes} codes remaining)",
                    source_ip=get_client_ip(request),
                )

                # Warn if backup codes running low (<3 remaining)
                if remaining_codes < 3:
                    backup_codes_warning = f"WARNING: Only {remaining_codes} backup code(s) remaining. Regenerate 2FA backup codes soon."
                    await write_audit(
                        db, form_data.username, ACTION_BACKUP_CODE_LOW,
                        detail=f"Backup codes depleting: {remaining_codes} codes remaining after login",
                        source_ip=get_client_ip(request),
                    )

            if _is_truthy_form_flag(remember_device):
                await _remember_trusted_device(form_data.username, response, request, db)

    encoded, expire, _ = _make_token(form_data.username)
    settings = get_settings()
    _set_auth_cookie(response, encoded, request, settings.token_ttl_hours)
    await write_audit(
        db, form_data.username, ACTION_LOGIN,
        detail="User logged in",
        source_ip=get_client_ip(request),
    )
    return Token(access_token=encoded, token_type="bearer", expires_at=expire, backup_codes_warning=backup_codes_warning)


@router.post("/refresh", response_model=Token)
async def refresh(
    response: Response,
    request: Request,
    payload: dict = Depends(_get_payload),
    db: AsyncSession = Depends(get_db),
):
    """
    Issue a new token with a fresh expiry window and revoke the old one.
    The client should call this ~10 min before the current token expires.
    """
    username: str = payload["sub"]
    old_jti: str = payload["jti"]
    old_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    # Revoke the old token
    db.add(RevokedToken(jti=old_jti, expires_at=old_exp))
    await db.commit()

    # Housekeeping (fire-and-forget, don't block)
    await _prune_expired_tokens(db)

    settings = get_settings()
    encoded, expire, _ = _make_token(username)
    _set_auth_cookie(response, encoded, request, settings.token_ttl_hours)
    return Token(access_token=encoded, token_type="bearer", expires_at=expire)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current token immediately and clear the auth cookie."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return  # already invalid — nothing to do

    jti = payload.get("jti")
    if not jti:
        return

    exp_ts = payload.get("exp")
    exp_dt = (
        datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        if exp_ts
        else datetime.now(timezone.utc)
    )
    # Upsert — ignore if already revoked
    existing = await db.get(RevokedToken, jti)
    if not existing:
        db.add(RevokedToken(jti=jti, expires_at=exp_dt))
        await db.commit()

    username: str = payload.get("sub", "unknown")
    await write_audit(
        db, username, ACTION_LOGOUT,
        detail="User logged out",
        source_ip=get_client_ip(request),
    )
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        secure=_is_secure_request(request),
        samesite="lax",
    )


@router.get("/me", response_model=MeOut)
async def me(
    payload: dict = Depends(_get_payload),
):
    exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    return MeOut(username=payload["sub"], expires_at=exp_dt)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: Request,
    body: ChangePasswordIn,
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await _verify_credentials(current_user, body.current_password, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password must be at least 8 characters",
        )
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    row = await db.get(AdminCredential, current_user)
    if row:
        row.hashed_password = new_hash
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(AdminCredential(username=current_user, hashed_password=new_hash))
    await db.commit()
    await write_audit(
        db, current_user, ACTION_PASSWORD_CHANGED,
        detail="User changed password",
        source_ip=get_client_ip(request),
    )
