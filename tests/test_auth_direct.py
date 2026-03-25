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
from jose import JWTError
from starlette.datastructures import Headers

from backend.config import get_settings
from backend.models.auth import AdminCredential, RevokedToken
from backend.routers.auth import (
    ALGORITHM,
    ChangePasswordIn,
    _is_trusted_device,
    _remember_trusted_device,
    _get_hashed_password,
    _verify_credentials,
    _prune_expired_tokens,
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

        class _URL:
            scheme = "http"

        self.url = _URL()


class _FakeResponse:
    """Minimal Response duck-type for set_cookie/delete_cookie testing."""

    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value=None, max_age=None, expires=None, httponly=False, secure=False, samesite=None, path=None):
        self.cookies[key] = {"value": value, "max_age": max_age}

    def delete_cookie(self, key, path=None, secure=False, samesite=None):
        self.cookies[key] = None

class _FakeDB:
    """Minimal AsyncSession duck-type."""

    def __init__(self, get_return=None):
        self._get_return = get_return
        self.added = []
        self.deleted = []
        self.committed = False

    async def get(self, cls, pk):
        return self._get_return

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

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


async def test_get_current_user_missing_subject_or_jti_raises_401():
    """get_current_user raises 401 when required claims are missing."""
    settings = get_settings()
    from backend.main import BOOT_ID

    token = jose_jwt.encode(
        {
            "sub": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "bid": BOOT_ID,
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )

    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db)
    assert exc_info.value.status_code == 401


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


async def test_get_payload_missing_jti_raises_401():
    """_get_payload raises 401 when jti claim is missing."""
    settings = get_settings()
    from backend.main import BOOT_ID

    token = jose_jwt.encode(
        {
            "sub": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "bid": BOOT_ID,
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )

    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await _get_payload(token=token, db=db)
    assert exc_info.value.status_code == 401


async def test_get_hashed_password_returns_value_or_none():
    """_get_hashed_password returns stored hash when present, else None."""
    stored = AdminCredential(username="admin", hashed_password="hash")
    db = _FakeDB(get_return=stored)
    assert await _get_hashed_password("admin", db) == "hash"

    db_none = _FakeDB(get_return=None)
    assert await _get_hashed_password("admin", db_none) is None


async def test_verify_credentials_uses_db_hash_and_fallback_plaintext():
    """_verify_credentials should validate against DB hash or env fallback."""
    settings = get_settings()

    db_hash = bcrypt.hashpw(settings.admin_password.encode(), bcrypt.gensalt()).decode()

    with patch("backend.routers.auth._get_hashed_password", new_callable=AsyncMock, return_value=db_hash):
        assert await _verify_credentials(settings.admin_user, settings.admin_password, _FakeDB()) is True

    with patch("backend.routers.auth._get_hashed_password", new_callable=AsyncMock, return_value=None):
        assert await _verify_credentials(settings.admin_user, settings.admin_password, _FakeDB()) is True


async def test_prune_expired_tokens_commits():
    """_prune_expired_tokens should execute delete and commit."""
    db = _FakeDB()
    await _prune_expired_tokens(db)
    assert db.committed is True


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


async def test_is_trusted_device_returns_false_when_record_missing():
    """_is_trusted_device should return False when token hash is not found."""
    db = _FakeDB(get_return=None)
    is_trusted = await _is_trusted_device("admin", "cookie-token", db)
    assert is_trusted is False


async def test_is_trusted_device_invalid_record_is_deleted():
    """_is_trusted_device should delete stale/mismatched records and return False."""
    record = MagicMock()
    record.username = "other-user"
    record.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db = _FakeDB(get_return=record)

    is_trusted = await _is_trusted_device("admin", "cookie-token", db)

    assert is_trusted is False
    assert record in db.deleted
    assert db.committed is True


async def test_is_trusted_device_accepts_naive_future_expiry():
    """_is_trusted_device should normalize naive expiry and accept valid records."""
    record = MagicMock()
    record.username = "admin"
    record.expires_at = datetime.now() + timedelta(hours=1)
    db = _FakeDB(get_return=record)

    is_trusted = await _is_trusted_device("admin", "cookie-token", db)

    assert is_trusted is True


async def test_remember_trusted_device_sets_cookie_and_persists_record():
    """_remember_trusted_device should store DB row and set secure cookie on HTTPS."""
    db = _FakeDB()
    response = Response()
    request = _FakeRequest()
    request.url.scheme = "https"

    await _remember_trusted_device("admin", response, request, db)

    assert db.committed is True
    assert len(db.added) == 1
    set_cookie_values = response.headers.getlist("set-cookie")
    assert any("cloudshell_trusted_device=" in value for value in set_cookie_values)
    assert any("Secure" in value for value in set_cookie_values)


async def test_login_direct_backup_code_used_low_warning_and_remember_device():
    """login should consume backup code, warn when low, and remember device when requested."""
    from fastapi.security import OAuth2PasswordRequestForm

    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "admin"
    form.password = "admin"

    totp_record = MagicMock()
    totp_record.is_enabled = True
    totp_record.secret = "SECRET"
    totp_record.backup_codes = "[]"

    db = _FakeDB(get_return=totp_record)
    request = _FakeRequest()
    response = Response()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=True), \
         patch("backend.routers.auth._prune_expired_trusted_devices", new_callable=AsyncMock), \
         patch("backend.routers.auth._is_trusted_device", new_callable=AsyncMock, return_value=False), \
         patch("backend.routers.auth._remember_trusted_device", new_callable=AsyncMock) as mock_remember, \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock) as mock_audit, \
         patch("backend.services.totp.TOTPService.verify_token", return_value=False), \
         patch("backend.services.totp.TOTPService.verify_and_consume_backup_code", return_value=(True, '["hashed-only"]')), \
         patch("backend.services.totp.TOTPService.codes_from_json", return_value=["leftover"]):
        token = await login(
            request=request,
            response=response,
            form_data=form,
            totp_code="ABCD-EFGH",
            remember_device="true",
            db=db,
        )

    assert token.access_token
    assert db.committed is True
    assert "Only 1 backup code(s) remaining" in (token.backup_codes_warning or "")
    assert mock_audit.await_count >= 3
    mock_remember.assert_awaited_once()


async def test_login_direct_trusted_device_skips_totp_code_requirement():
    """login should allow successful auth without totp_code when device is trusted."""
    from fastapi.security import OAuth2PasswordRequestForm

    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "admin"
    form.password = "admin"

    totp_record = MagicMock()
    totp_record.is_enabled = True

    db = _FakeDB(get_return=totp_record)
    request = _FakeRequest()
    response = Response()

    with patch("backend.routers.auth._verify_credentials", new_callable=AsyncMock, return_value=True), \
         patch("backend.routers.auth._prune_expired_trusted_devices", new_callable=AsyncMock), \
         patch("backend.routers.auth._is_trusted_device", new_callable=AsyncMock, return_value=True), \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock):
        token = await login(
            request=request,
            response=response,
            form_data=form,
            totp_code=None,
            db=db,
        )

    assert token.access_token


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
    request = _FakeRequest()
    response = _FakeResponse()

    with patch("backend.routers.auth._prune_expired_tokens", new_callable=AsyncMock) as mock_prune:
        token = await refresh(response=response, request=request, payload=payload, db=db)

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
    response = _FakeResponse()

    with patch("backend.routers.auth.jwt.decode", return_value=no_jti_payload):
        await logout(response=response, request=request, token="any.token.value", db=db)

    # No RevokedToken should have been added and no commit
    assert not any(isinstance(o, RevokedToken) for o in db.added)
    assert not db.committed


async def test_logout_direct_invalid_jwt_returns_early():
    """logout should return early when jwt.decode raises JWTError."""
    db = _FakeDB()
    request = _FakeRequest()
    response = _FakeResponse()

    with patch("backend.routers.auth.jwt.decode", side_effect=JWTError("bad token")):
        await logout(response=response, request=request, token="bad.token", db=db)

    assert db.added == []
    assert db.committed is False


async def test_logout_direct_success_with_exp():
    """logout adds a RevokedToken and writes an audit entry when exp is present."""
    token = _valid_token()
    db = _FakeDB(get_return=None)  # not already revoked
    request = _FakeRequest()
    response = _FakeResponse()

    with patch("backend.routers.auth.write_audit", new_callable=AsyncMock) as mock_audit:
        await logout(response=response, request=request, token=token, db=db)

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
    response = _FakeResponse()

    with patch("backend.routers.auth.jwt.decode", return_value=no_exp_payload), \
         patch("backend.routers.auth.write_audit", new_callable=AsyncMock):
        await logout(response=response, request=request, token=encoded, db=db)

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
    response = _FakeResponse()

    with patch("backend.routers.auth.write_audit", new_callable=AsyncMock):
        await logout(response=response, request=request, token=token, db=db)

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
