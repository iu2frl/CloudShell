"""
tests/test_auth_direct.py — direct-call coverage tests for backend/routers/auth.py.

The ASGI transport used by httpx does NOT propagate Python's sys.settrace into
handler coroutines, so pytest-cov cannot record those lines even when HTTP tests
pass.  Calling handlers directly keeps the coverage tracer active throughout.

Covers all lines missed by the ASGI-based test suite:
- get_current_user:   126, 129, 135-140  (boot-id mismatch, revoked)
- _get_payload:       169-174, 191-197   (boot-id mismatch, revoked)
- login:              218-221            (success path body)
- refresh:            239, 249-254       (revoke old token, prune, return)
- logout:             277-294            (exp_ts branch, upsert, audit)
- change_password:    full handler body  (both row-exists and row-missing paths)
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from fastapi import HTTPException, Request
from starlette.responses import Response
from jose import jwt as jose_jwt
from starlette.datastructures import Headers

from backend.config import get_settings
from backend.models.auth import AdminCredential, RevokedToken
from backend.routers.auth import (
    ALGORITHM,
    ChangePasswordIn,
    _get_payload,
    _make_token,
    change_password,
    get_current_user,
    login,
    logout,
    me,
    refresh,
)
from backend.services.audit import ACTION_LOGIN, ACTION_LOGOUT, ACTION_PASSWORD_CHANGED


# -- Fake helpers --------------------------------------------------------------

class _FakeRequest:
    """Minimal Request duck-type for handlers that call get_client_ip(request)."""

    def __init__(self):
        self.headers = Headers(headers={})
        self.client = None
        self.cookies = {}


class _FakeDB:
    """Minimal AsyncSession duck-type."""

    def __init__(self, get_return=None):
        self._get_return = get_return
        self.added = []
        self.committed = False

    async def get(self, cls, pk):
        return self._get_return

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def execute(self, stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        return mock_result


def _valid_token(extra: dict | None = None) -> str:
    """Build a correctly-signed JWT for the running test process."""
    from backend.main import BOOT_ID
    settings = get_settings()
    payload = {
        "sub": "admin",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": BOOT_ID,
        **(extra or {}),
    }
    return jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _token_with_bad_bid() -> str:
    settings = get_settings()
    payload = {
        "sub": "admin",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "bid": "00000000-0000-0000-0000-000000000000",
    }
    return jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


# -- get_current_user ----------------------------------------------------------

async def test_get_current_user_invalid_jwt_raises_401():
    """get_current_user raises 401 when the token cannot be decoded (JWTError path)."""
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token="not.a.valid.jwt", db=db)
    assert exc_info.value.status_code == 401


async def test_get_current_user_boot_id_mismatch_raises_401():
    """get_current_user raises 401 when the token's bid does not match BOOT_ID."""
    token = _token_with_bad_bid()
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db)
    assert exc_info.value.status_code == 401
    assert "server restart" in exc_info.value.detail.lower()


async def test_get_current_user_revoked_token_raises_401():
    """get_current_user raises 401 when the token's jti is in the revoked set."""
    token = _valid_token()
    settings = get_settings()
    decoded = jose_jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    jti = decoded["jti"]

    # DB.get(RevokedToken, jti) returns a row  → token is revoked
    revoked_row = RevokedToken(
        jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db = _FakeDB(get_return=revoked_row)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


async def test_get_current_user_valid_token_returns_username():
    """get_current_user returns the username for a valid, non-revoked token."""
    token = _valid_token()
    db = _FakeDB(get_return=None)  # None → not revoked
    username = await get_current_user(token=token, db=db)
    assert username == "admin"


# -- _get_payload --------------------------------------------------------------

async def test_get_payload_boot_id_mismatch_raises_401():
    """_get_payload raises 401 when the token's bid does not match BOOT_ID."""
    token = _token_with_bad_bid()
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await _get_payload(token=token, db=db)
    assert exc_info.value.status_code == 401
    assert "server restart" in exc_info.value.detail.lower()


async def test_get_payload_revoked_token_raises_401():
    """_get_payload raises 401 when the token jti is revoked."""
    token = _valid_token()
    settings = get_settings()
    decoded = jose_jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    jti = decoded["jti"]

    revoked_row = RevokedToken(
        jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db = _FakeDB(get_return=revoked_row)
    with pytest.raises(HTTPException) as exc_info:
        await _get_payload(token=token, db=db)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


async def test_get_payload_valid_token_returns_dict():
    """_get_payload returns the full payload dict for a valid token."""
    token = _valid_token()
    db = _FakeDB(get_return=None)
    payload = await _get_payload(token=token, db=db)
    assert payload["sub"] == "admin"
    assert "jti" in payload


# -- login ---------------------------------------------------------------------

async def test_login_direct_success():
    """login returns a Token with correct fields when credentials are valid."""
    from fastapi.security import OAuth2PasswordRequestForm

    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "admin"
    form.password = "admin"

    db = _FakeDB()
    request = _FakeRequest()
    response = Response()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=True), \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock):
        token = await login(request=request, response=response, form_data=form, db=db)

    assert token.token_type == "bearer"
    assert token.access_token
    assert token.expires_at > datetime.now(timezone.utc)


async def test_login_direct_bad_credentials_raises_401():
    """login raises 401 when _verify_credentials returns False."""
    from fastapi.security import OAuth2PasswordRequestForm

    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "admin"
    form.password = "wrong"

    db = _FakeDB()
    request = _FakeRequest()
    response = Response()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await login(request=request, response=response, form_data=form, db=db)
    assert exc_info.value.status_code == 401


# -- refresh -------------------------------------------------------------------

async def test_refresh_direct_success():
    """refresh revokes the old token, prunes, and issues a fresh Token."""
    old_jti = str(uuid.uuid4())
    old_exp = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {
        "sub": "admin",
        "jti": old_jti,
        "exp": int(old_exp.timestamp()),
    }

    db = _FakeDB()

    with patch("backend.routers.auth._prune_expired_tokens", new_callable=AsyncMock) as mock_prune:
        token = await refresh(payload=payload, db=db)

    assert token.token_type == "bearer"
    assert token.access_token
    # Old jti must have been added to revoked set
    assert any(isinstance(o, RevokedToken) and o.jti == old_jti for o in db.added)
    assert db.committed
    mock_prune.assert_awaited_once()


# -- logout --------------------------------------------------------------------

async def test_logout_direct_no_jti_returns_early():
    """logout returns early without committing when the decoded payload has no jti."""
    settings = get_settings()
    from backend.main import BOOT_ID
    # Patch jwt.decode to return a payload without 'jti'
    no_jti_payload = {"sub": "admin", "bid": BOOT_ID}
    db = _FakeDB()
    request = _FakeRequest()

    with patch("backend.routers.auth.jwt.decode", return_value=no_jti_payload):
        await logout(request=request, token="any.token.value", db=db)

    # No RevokedToken should have been added and no commit
    assert not any(isinstance(o, RevokedToken) for o in db.added)
    assert not db.committed


async def test_logout_direct_success_with_exp():
    """logout adds a RevokedToken and writes an audit entry when exp is present."""
    token = _valid_token()
    db = _FakeDB(get_return=None)  # not already revoked
    request = _FakeRequest()

    with patch("backend.routers.auth.write_audit", new_callable=AsyncMock) as mock_audit:
        await logout(request=request, token=token, db=db)

    assert db.committed
    assert any(isinstance(o, RevokedToken) for o in db.added)
    mock_audit.assert_awaited_once()


async def test_logout_direct_exp_missing_uses_now():
    """logout falls back to datetime.now when the token carries no exp claim."""
    settings = get_settings()
    from backend.main import BOOT_ID
    # Build a token without an 'exp' claim (jose will still encode it, just omit it)
    payload_dict = {
        "sub": "admin",
        "jti": str(uuid.uuid4()),
        "bid": BOOT_ID,
    }
    # jose requires exp; simulate by decoding manually and popping it
    encoded = jose_jwt.encode(
        {**payload_dict, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    # Patch jwt.decode to return a payload without 'exp'
    no_exp_payload = {**payload_dict}  # no 'exp' key

    db = _FakeDB(get_return=None)
    request = _FakeRequest()

    with patch("backend.routers.auth.jwt.decode", return_value=no_exp_payload), \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock):
        await logout(request=request, token=encoded, db=db)

    # The fallback path should have added a RevokedToken
    assert any(isinstance(o, RevokedToken) for o in db.added)


async def test_logout_direct_already_revoked_skips_add():
    """logout does not add a second RevokedToken when the token is already revoked."""
    token = _valid_token()
    settings = get_settings()
    decoded = jose_jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    jti = decoded["jti"]

    existing_row = RevokedToken(
        jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db = _FakeDB(get_return=existing_row)  # already revoked
    request = _FakeRequest()

    with patch("backend.routers.auth.write_audit", new_callable=AsyncMock):
        await logout(request=request, token=token, db=db)

    # No new RevokedToken should have been added
    assert not any(isinstance(o, RevokedToken) for o in db.added)
    assert not db.committed  # no commit because nothing was added


# -- change_password -----------------------------------------------------------

async def test_change_password_direct_no_existing_row():
    """change_password creates a new AdminCredential row when none exists."""
    body = ChangePasswordIn(current_password="admin", new_password="NewPass1!")
    db = _FakeDB(get_return=None)  # no existing credential row
    request = _FakeRequest()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=True), \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock) as mock_audit:
        await change_password(request=request, body=body, current_user="admin", db=db)

    assert any(isinstance(o, AdminCredential) for o in db.added)
    assert db.committed
    mock_audit.assert_awaited_once()


async def test_change_password_direct_updates_existing_row():
    """change_password updates hashed_password in-place when a row already exists."""
    existing = AdminCredential(
        username="admin",
        hashed_password=bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
    )
    db = _FakeDB(get_return=existing)
    body = ChangePasswordIn(current_password="admin", new_password="UpdatedPass1!")
    request = _FakeRequest()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=True), \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock) as mock_audit:
        await change_password(request=request, body=body, current_user="admin", db=db)

    # The existing row's hash should have been replaced
    assert bcrypt.checkpw(b"UpdatedPass1!", existing.hashed_password.encode())
    assert db.committed
    mock_audit.assert_awaited_once()


async def test_change_password_direct_wrong_current_raises_401():
    """change_password raises 401 when the current password is incorrect."""
    body = ChangePasswordIn(current_password="wrong", new_password="NewPass1!")
    db = _FakeDB()
    request = _FakeRequest()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await change_password(request=request, body=body, current_user="admin", db=db)
    assert exc_info.value.status_code == 401


async def test_change_password_direct_short_password_raises_422():
    """change_password raises 422 when new_password is fewer than 8 characters."""
    body = ChangePasswordIn(current_password="admin", new_password="short")
    db = _FakeDB()
    request = _FakeRequest()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await change_password(request=request, body=body, current_user="admin", db=db)
    assert exc_info.value.status_code == 422


# -- me ------------------------------------------------------------------------

async def test_me_direct_returns_username_and_expiry():
    """me returns MeOut with the correct username and a future expires_at."""
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {"sub": "admin", "exp": int(exp.timestamp())}
    result = await me(payload=payload)
    assert result.username == "admin"
    assert result.expires_at > datetime.now(timezone.utc)
