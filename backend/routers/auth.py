"""
routers/auth.py — Authentication & session management

Endpoints
---------
POST /api/auth/token           Login → JWT
POST /api/auth/refresh         Extend a valid (non-expired) session
POST /api/auth/logout          Revoke the current token
GET  /api/auth/me              Whoami + token expiry info
POST /api/auth/change-password Change admin password (persisted in DB)
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.auth import AdminCredential, RevokedToken
from backend.services.audit import (
    ACTION_LOGIN,
    ACTION_LOGOUT,
    ACTION_PASSWORD_CHANGED,
    get_client_ip,
    write_audit,
)

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

ALGORITHM = "HS256"


def _get_boot_id() -> str:
    """Return the current process boot ID (imported lazily to avoid circular imports)."""
    from backend.main import BOOT_ID  # noqa: PLC0415
    return BOOT_ID


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_at: datetime   # ISO-8601 UTC, for the frontend countdown


class MeOut(BaseModel):
    username: str
    expires_at: datetime


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


# ── Internal helpers ──────────────────────────────────────────────────────────

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
        return pwd_context.verify(password, db_hash)
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


# ── Shared dependency ─────────────────────────────────────────────────────────

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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    if not await _verify_credentials(form_data.username, form_data.password, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    encoded, expire, _ = _make_token(form_data.username)
    await write_audit(
        db, form_data.username, ACTION_LOGIN,
        detail="User logged in",
        source_ip=get_client_ip(request),
    )
    return Token(access_token=encoded, token_type="bearer", expires_at=expire)


@router.post("/refresh", response_model=Token)
async def refresh(
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

    encoded, expire, _ = _make_token(username)
    return Token(access_token=encoded, token_type="bearer", expires_at=expire)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current token immediately."""
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
    new_hash = pwd_context.hash(body.new_password)
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
