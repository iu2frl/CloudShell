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
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Form
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import httpx
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.auth import AdminCredential, RevokedToken, AdminTOTPSecret, AdminTrustedDevice
from backend.models.user import User
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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

ALGORITHM = "HS256"
REMEMBER_DEVICE_DAYS = 30
REMEMBER_DEVICE_MAX_AGE_SECONDS = REMEMBER_DEVICE_DAYS * 24 * 60 * 60
REMEMBER_DEVICE_COOKIE_NAME = "cloudshell_trusted_device"
AUTH_COOKIE_NAME = "cloudshell_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 8 * 60 * 60  # Will be overridden by settings.token_ttl_hours
OIDC_STATE_COOKIE_NAME = "cloudshell_oidc_state"
OIDC_STATE_TTL_SECONDS = 300

_oidc_discovery_cache: dict[str, tuple[float, dict]] = {}
_oidc_jwks_cache: dict[str, tuple[float, dict]] = {}


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


class OIDCStatusOut(BaseModel):
    enabled: bool


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


def _normalize_next_path(value: str | None) -> str:
    """Return a safe relative path for post-login redirect."""
    if not value:
        return "/"
    if not value.startswith("/"):
        return "/"
    if value.startswith("//"):
        return "/"
    return value


def _make_oidc_state(next_path: str) -> str:
    """Create short-lived signed OIDC state payload with nonce."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "typ": "oidc_state",
        "nonce": secrets.token_urlsafe(32),
        "next": _normalize_next_path(next_path),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=OIDC_STATE_TTL_SECONDS)).timestamp()),
        "bid": _get_boot_id(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _decode_oidc_state(state_token: str) -> dict:
    """Decode and validate signed OIDC state token."""
    settings = get_settings()
    payload = jwt.decode(state_token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("typ") != "oidc_state":
        raise HTTPException(status_code=400, detail="Invalid OIDC state")
    if payload.get("bid") != _get_boot_id():
        raise HTTPException(status_code=400, detail="OIDC state is stale after restart")
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise HTTPException(status_code=400, detail="Invalid OIDC state nonce")
    payload["next"] = _normalize_next_path(payload.get("next"))
    return payload


async def _http_get_json(url: str) -> dict:
    """Fetch and parse JSON using a short timeout."""
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _get_oidc_discovery() -> dict:
    """Return OIDC discovery document with short in-memory cache."""
    settings = get_settings()
    issuer = settings.oidc_issuer_url.rstrip("/")
    now = time.time()

    cached = _oidc_discovery_cache.get(issuer)
    if cached and cached[0] > now:
        return cached[1]

    discovery_url = f"{issuer}/.well-known/openid-configuration"
    discovery = await _http_get_json(discovery_url)
    ttl = max(30, settings.oidc_discovery_ttl_seconds)
    _oidc_discovery_cache[issuer] = (now + ttl, discovery)
    return discovery


async def _get_oidc_jwks(jwks_uri: str) -> dict:
    """Return OIDC JWKS with short in-memory cache."""
    now = time.time()
    cached = _oidc_jwks_cache.get(jwks_uri)
    if cached and cached[0] > now:
        return cached[1]

    jwks = await _http_get_json(jwks_uri)
    ttl = max(30, get_settings().oidc_discovery_ttl_seconds)
    _oidc_jwks_cache[jwks_uri] = (now + ttl, jwks)
    return jwks


def _select_jwk_for_token(id_token: str, jwks: dict) -> dict:
    """Pick JWK by token kid, fail closed when missing."""
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    keys = jwks.get("keys") or []
    if not isinstance(keys, list) or not keys:
        raise HTTPException(status_code=502, detail="OIDC provider returned empty JWKS")

    if kid:
        for key in keys:
            if isinstance(key, dict) and key.get("kid") == kid:
                return key
        raise HTTPException(status_code=401, detail="OIDC signing key not found")

    first = keys[0]
    if not isinstance(first, dict):
        raise HTTPException(status_code=502, detail="OIDC JWKS key format is invalid")
    return first


def _resolve_oidc_username(claims: dict) -> str:
    """Build stable internal username from OIDC claims."""
    issuer = str(claims.get("iss") or "")
    subject = str(claims.get("sub") or "")
    if not issuer or not subject:
        raise HTTPException(status_code=401, detail="OIDC token missing iss/sub")
    return f"oidc:{issuer}:{subject}"[:128]


def _parse_oidc_username(username: str) -> tuple[str, str] | None:
    """Parse an internal OIDC username into (issuer, subject)."""
    if not username.startswith("oidc:"):
        return None
    parts = username.split(":", maxsplit=3)
    if len(parts) != 4:
        return None
    issuer = f"{parts[1]}:{parts[2]}"
    subject = parts[3]
    if not issuer or not subject:
        return None
    return issuer, subject


async def ensure_user_for_username(db: AsyncSession, username: str) -> User:
    """Fetch or create a user identity row for a token subject."""
    if not isinstance(db, AsyncSession):
        settings = get_settings()
        return User(
            id=0,
            username=username,
            auth_provider="local",
            provider_issuer=None,
            provider_subject=None,
            is_admin=username == settings.admin_user,
        )

    result = await db.execute(select(User).where(User.username == username))
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    settings = get_settings()
    oidc_identity = _parse_oidc_username(username)
    if oidc_identity:
        provider = "oidc"
        issuer, subject = oidc_identity
        provider_issuer = issuer
        provider_subject = subject
        is_admin = False
    else:
        provider = "local"
        provider_issuer = None
        provider_subject = None
        is_admin = username == settings.admin_user

    user = User(
        username=username,
        auth_provider=provider,
        provider_issuer=provider_issuer,
        provider_subject=provider_subject,
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_owner_user_id(db: AsyncSession, username: str) -> int:
    """Resolve numeric owner id for a username, creating a row when needed."""
    user = await ensure_user_for_username(db, username)
    return user.id


async def _exchange_oidc_code(code: str, expected_nonce: str) -> str:
    """Exchange authorization code and return internal username."""
    settings = get_settings()
    discovery = await _get_oidc_discovery()

    token_endpoint = discovery.get("token_endpoint")
    jwks_uri = discovery.get("jwks_uri")
    issuer = discovery.get("issuer")
    if not token_endpoint or not jwks_uri or not issuer:
        raise HTTPException(status_code=502, detail="OIDC discovery document is incomplete")

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
    }
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token_resp = await client.post(token_endpoint, data=form)
    if token_resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="OIDC token exchange failed")

    token_data = token_resp.json()
    id_token = token_data.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise HTTPException(status_code=401, detail="OIDC response missing id_token")

    jwks = await _get_oidc_jwks(jwks_uri)
    key = _select_jwk_for_token(id_token, jwks)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=settings.oidc_client_id,
            issuer=issuer,
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="OIDC id_token validation failed") from exc

    nonce = claims.get("nonce")
    if nonce != expected_nonce:
        raise HTTPException(status_code=401, detail="OIDC nonce mismatch")

    return _resolve_oidc_username(claims)


# -- Shared dependency ---------------------------------------------------------

async def get_current_user(
    request: Request = None,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> str:
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME) if request is not None else None
    token_value = token or cookie_token
    if not token_value:
        raise credentials_exception

    try:
        payload = jwt.decode(token_value, settings.secret_key, algorithms=[ALGORITHM])
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
    request: Request = None,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME) if request is not None else None
    token_value = token or cookie_token
    if not token_value:
        raise credentials_exception

    try:
        payload = jwt.decode(token_value, settings.secret_key, algorithms=[ALGORITHM])
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
            remaining_codes = len(TOTPService.codes_from_json(getattr(totp_record, "backup_codes", None)))

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

    await ensure_user_for_username(db, form_data.username)
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
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current token immediately and clear the auth cookie."""
    token_value = token or request.cookies.get(AUTH_COOKIE_NAME)
    if not token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    try:
        payload = jwt.decode(token_value, settings.secret_key, algorithms=[ALGORITHM])
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


@router.get("/oidc/status", response_model=OIDCStatusOut)
async def oidc_status() -> OIDCStatusOut:
    """Expose whether OIDC login is enabled for frontend toggles."""
    return OIDCStatusOut(enabled=get_settings().oidc_enabled)


@router.get("/oidc/login")
async def oidc_login(request: Request, next_path: str | None = None):
    """Start OIDC authorization code flow by redirecting to the provider."""
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="OIDC is disabled")

    discovery = await _get_oidc_discovery()
    authorization_endpoint = discovery.get("authorization_endpoint")
    if not authorization_endpoint:
        raise HTTPException(status_code=502, detail="OIDC discovery missing authorization endpoint")

    normalized_next_path = _normalize_next_path(next_path) if next_path else _normalize_next_path(settings.oidc_post_login_redirect)
    state = _make_oidc_state(normalized_next_path)
    payload = _decode_oidc_state(state)

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": payload["nonce"],
    }
    location = f"{authorization_endpoint}?{urlencode(params)}"
    response = RedirectResponse(url=location, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OIDC_STATE_COOKIE_NAME,
        value=state,
        max_age=OIDC_STATE_TTL_SECONDS,
        expires=OIDC_STATE_TTL_SECONDS,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Finish OIDC flow, issue local session cookie, then redirect to app."""
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="OIDC is disabled")
    if error:
        raise HTTPException(status_code=401, detail=f"OIDC authorization failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OIDC code/state")

    cookie_state = request.cookies.get(OIDC_STATE_COOKIE_NAME)
    if not cookie_state:
        raise HTTPException(status_code=400, detail="Missing OIDC state cookie")
    if not secrets.compare_digest(cookie_state, state):
        raise HTTPException(status_code=400, detail="OIDC state mismatch")

    try:
        state_payload = _decode_oidc_state(state)
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="OIDC state is invalid or expired") from exc

    username = await _exchange_oidc_code(code, state_payload["nonce"])
    await ensure_user_for_username(db, username)
    encoded, expire, _ = _make_token(username)

    redirect_response = RedirectResponse(
        url=state_payload["next"],
        status_code=status.HTTP_302_FOUND,
    )
    _set_auth_cookie(redirect_response, encoded, request, settings.token_ttl_hours)
    redirect_response.delete_cookie(
        key=OIDC_STATE_COOKIE_NAME,
        path="/",
        secure=_is_secure_request(request),
        samesite="lax",
    )
    await write_audit(
        db,
        username,
        ACTION_LOGIN,
        detail=f"User logged in via OIDC, expires at {expire.isoformat()}",
        source_ip=get_client_ip(request),
    )
    return redirect_response
