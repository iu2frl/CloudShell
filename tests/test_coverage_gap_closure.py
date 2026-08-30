"""Targeted tests to close remaining coverage gaps."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from jose import JWTError
from starlette.datastructures import UploadFile

from backend.config import get_settings
from backend.database import _ensure_user_ownership_backfill
from backend.models.device import AuthType, ConnectionType, Device
from backend.models.folder import Folder
from backend.models.user import User
from backend.routers import auth as auth_router
from backend.routers.auth import (
    ALGORITHM,
    OIDC_STATE_COOKIE_NAME,
    _claims_match_client_audience,
    _decode_oidc_state,
    _extract_groups_from_claims,
    _exchange_oidc_code,
    _get_oidc_discovery,
    _get_oidc_jwks,
    _http_get_json,
    _make_oidc_state,
    _normalize_next_path,
    _resolve_oidc_username,
    ensure_user_for_username,
    oidc_callback,
    oidc_login,
)
from backend.routers.config_transfer import import_config
from backend.routers.devices import DeviceCreate, DeviceUpdate, create_device, delete_device, get_device, update_device
from backend.routers.ftp import upload_file
from backend.routers.ftp import open_session as open_ftp_session_route
from backend.routers.sftp import open_session as open_sftp_session_route
from backend.routers.terminal import open_session as open_terminal_session_route
from backend.services.folder import validate_folder_exists
from backend.services.ssh import SSHHostFingerprintUnavailableError


class _FakeRequest:
    def __init__(self):
        self.cookies = {}

        class _URL:
            scheme = "http"

        self.url = _URL()
        self.headers = {}
        self.client = None


class _FakeOIDCResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeOIDCClient:
    def __init__(self, response: _FakeOIDCResp):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    async def post(self, url, data):
        _ = url, data
        return self._response


class _FakeNonAsyncDb:
    def __init__(self, device: Device | None = None):
        self._device = device
        self.added: list[object] = []

    async def get(self, cls, pk):
        _ = cls, pk
        return self._device

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 999
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, obj):
        return obj

    async def delete(self, obj):
        _ = obj
        return None


class _FakeConnResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []
        self._execute_count = 0

    async def execute(self, stmt, params=None):
        self._execute_count += 1
        sql = str(stmt)
        self.calls.append((sql, params))
        if "SELECT id FROM users" in sql:
            return _FakeConnResult(one=None)
        return _FakeConnResult()


def _oidc_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://test/api/auth/oidc/callback")


def test_config_oidc_missing_required(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://test/callback")
    with pytest.raises(ValueError, match="missing required settings"):
        get_settings()
    get_settings.cache_clear()


def test_config_oidc_rejects_bad_redirect_scheme(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "ftp://bad")
    with pytest.raises(ValueError, match="OIDC_REDIRECT_URI must start"):
        get_settings()
    get_settings.cache_clear()


def test_config_oidc_rejects_bad_issuer_scheme(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("OIDC_ISSUER_URL", "ftp://bad")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://test/callback")
    with pytest.raises(ValueError, match="OIDC_ISSUER_URL must start"):
        get_settings()
    get_settings.cache_clear()


def test_config_oidc_non_dev_rejects_http_redirect(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "strong-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-admin-pass")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://localhost/callback")
    with pytest.raises(ValueError, match="OIDC_REDIRECT_URI must use https"):
        get_settings()
    get_settings.cache_clear()


def test_config_oidc_non_dev_rejects_http_issuer(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "strong-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-admin-pass")
    monkeypatch.setenv("OIDC_ISSUER_URL", "http://issuer")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cloudshell")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://ok/callback")
    with pytest.raises(ValueError, match="OIDC_ISSUER_URL must use https"):
        get_settings()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_database_backfill_returns_when_admin_row_missing(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_USER", "admin")
    conn = _FakeConn()
    await _ensure_user_ownership_backfill(conn)
    update_calls = [sql for sql, _ in conn.calls if sql.startswith("UPDATE devices") or sql.startswith("UPDATE folders")]
    assert update_calls == []


def test_normalize_next_path_guards():
    assert _normalize_next_path(None) == "/"
    assert _normalize_next_path("abc") == "/"
    assert _normalize_next_path("//evil") == "/"


@pytest.mark.asyncio
async def test_decode_oidc_state_rejects_invalid_typ(monkeypatch):
    _oidc_env(monkeypatch)
    with patch("backend.routers.auth.jwt.decode", return_value={"typ": "wrong", "bid": "x", "nonce": "n"}), \
         patch("backend.routers.auth._get_boot_id", return_value="x"):
        with pytest.raises(HTTPException, match="Invalid OIDC state"):
            _decode_oidc_state("token")


@pytest.mark.asyncio
async def test_decode_oidc_state_rejects_stale_bid(monkeypatch):
    _oidc_env(monkeypatch)
    with patch("backend.routers.auth.jwt.decode", return_value={"typ": "oidc_state", "bid": "old", "nonce": "n"}), \
         patch("backend.routers.auth._get_boot_id", return_value="new"):
        with pytest.raises(HTTPException, match="stale"):
            _decode_oidc_state("token")


@pytest.mark.asyncio
async def test_decode_oidc_state_rejects_missing_nonce(monkeypatch):
    _oidc_env(monkeypatch)
    with patch("backend.routers.auth.jwt.decode", return_value={"typ": "oidc_state", "bid": "ok", "nonce": ""}), \
         patch("backend.routers.auth._get_boot_id", return_value="ok"):
        with pytest.raises(HTTPException, match="nonce"):
            _decode_oidc_state("token")


@pytest.mark.asyncio
async def test_http_get_json_success():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def get(self, url):
            _ = url
            return _Resp()

    with patch("backend.routers.auth.httpx.AsyncClient", return_value=_Client()):
        data = await _http_get_json("https://id.example.com/discovery")
    assert data == {"ok": True}


@pytest.mark.asyncio
async def test_oidc_discovery_cache_miss_and_hit(monkeypatch):
    _oidc_env(monkeypatch)
    auth_router._oidc_discovery_cache.clear()
    fake = AsyncMock(return_value={"issuer": "https://id.example.com"})
    with patch("backend.routers.auth._http_get_json", fake):
        first = await _get_oidc_discovery()
        second = await _get_oidc_discovery()
    assert first["issuer"] == "https://id.example.com"
    assert second["issuer"] == "https://id.example.com"
    assert fake.await_count == 1


@pytest.mark.asyncio
async def test_oidc_jwks_cache_miss_and_hit(monkeypatch):
    _oidc_env(monkeypatch)
    auth_router._oidc_jwks_cache.clear()
    fake = AsyncMock(return_value={"keys": [{"kid": "k1"}]})
    with patch("backend.routers.auth._http_get_json", fake):
        first = await _get_oidc_jwks("https://id.example.com/jwks")
        second = await _get_oidc_jwks("https://id.example.com/jwks")
    assert first["keys"][0]["kid"] == "k1"
    assert second["keys"][0]["kid"] == "k1"
    assert fake.await_count == 1


def test_select_jwk_error_and_success_paths():
    with patch("backend.routers.auth.jwt.get_unverified_header", return_value={"kid": "k1"}):
        with pytest.raises(HTTPException, match="empty JWKS"):
            auth_router._select_jwk_for_token("tok", {"keys": []})
        with pytest.raises(HTTPException, match="signing key not found"):
            auth_router._select_jwk_for_token("tok", {"keys": [{"kid": "other"}]})
        key = auth_router._select_jwk_for_token("tok", {"keys": [{"kid": "k1"}]})
        assert key["kid"] == "k1"

    with patch("backend.routers.auth.jwt.get_unverified_header", return_value={}):
        with pytest.raises(HTTPException, match="format is invalid"):
            auth_router._select_jwk_for_token("tok", {"keys": ["bad"]})
        key = auth_router._select_jwk_for_token("tok", {"keys": [{"kid": "first"}]})
        assert key["kid"] == "first"


def test_oidc_claim_helpers():
    with pytest.raises(HTTPException, match="missing iss/sub"):
        _resolve_oidc_username({"iss": "", "sub": ""})
    assert _extract_groups_from_claims({}) == set()
    assert _extract_groups_from_claims({"groups": "A,b"}) == {"a", "b"}
    assert _extract_groups_from_claims({"groups": [" Dev ", "Ops"]}) == {"dev", "ops"}
    assert _extract_groups_from_claims({"groups": 123}) == set()
    assert _claims_match_client_audience({"aud": "cloudshell"}, "cloudshell") is True
    assert _claims_match_client_audience({"aud": ["x", "cloudshell"]}, "cloudshell") is True
    assert _claims_match_client_audience({"aud": ["x"], "azp": "cloudshell"}, "cloudshell") is True
    assert _claims_match_client_audience({"aud": ["x"], "azp": "other"}, "cloudshell") is False
    assert auth_router._parse_oidc_username("oidc:only-three:parts") is None
    assert auth_router._parse_oidc_username("oidc:http://issuer:") is None


@pytest.mark.asyncio
async def test_ensure_user_for_oidc_identity(db_session, monkeypatch):
    _oidc_env(monkeypatch)
    user = await ensure_user_for_username(db_session, "oidc:https://issuer.example.com:user-1")
    assert user.auth_provider == "oidc"
    assert user.provider_issuer == "https://issuer.example.com"
    assert user.provider_subject == "user-1"
    assert user.is_admin is False


@pytest.mark.asyncio
async def test_exchange_oidc_error_paths(monkeypatch):
    _oidc_env(monkeypatch)

    with patch("backend.routers.auth._get_oidc_discovery", AsyncMock(return_value={"issuer": "x"})):
        with pytest.raises(HTTPException, match="discovery document is incomplete"):
            await _exchange_oidc_code("c", "n")

    bad_response = _FakeOIDCResp(status_code=400, payload={})
    with patch(
        "backend.routers.auth._get_oidc_discovery",
        AsyncMock(return_value={"token_endpoint": "https://id/token", "jwks_uri": "https://id/jwks", "issuer": "https://id"}),
    ), patch("backend.routers.auth.httpx.AsyncClient", return_value=_FakeOIDCClient(bad_response)):
        with pytest.raises(HTTPException, match="token exchange failed"):
            await _exchange_oidc_code("c", "n")

    missing_id = _FakeOIDCResp(status_code=200, payload={"access_token": "a"})
    with patch(
        "backend.routers.auth._get_oidc_discovery",
        AsyncMock(return_value={"token_endpoint": "https://id/token", "jwks_uri": "https://id/jwks", "issuer": "https://id"}),
    ), patch("backend.routers.auth.httpx.AsyncClient", return_value=_FakeOIDCClient(missing_id)):
        with pytest.raises(HTTPException, match="missing id_token"):
            await _exchange_oidc_code("c", "n")

    missing_access = _FakeOIDCResp(status_code=200, payload={"id_token": "id"})
    with patch(
        "backend.routers.auth._get_oidc_discovery",
        AsyncMock(return_value={"token_endpoint": "https://id/token", "jwks_uri": "https://id/jwks", "issuer": "https://id"}),
    ), patch("backend.routers.auth.httpx.AsyncClient", return_value=_FakeOIDCClient(missing_access)):
        with pytest.raises(HTTPException, match="missing access_token"):
            await _exchange_oidc_code("c", "n")


@pytest.mark.asyncio
async def test_exchange_oidc_decode_error_and_nonce_mismatch(monkeypatch):
    _oidc_env(monkeypatch)
    ok_resp = _FakeOIDCResp(status_code=200, payload={"id_token": "id", "access_token": "at"})

    with patch(
        "backend.routers.auth._get_oidc_discovery",
        AsyncMock(return_value={"token_endpoint": "https://id/token", "jwks_uri": "https://id/jwks", "issuer": "https://id"}),
    ), patch("backend.routers.auth._get_oidc_jwks", AsyncMock(return_value={"keys": [{}]})), \
         patch("backend.routers.auth._select_jwk_for_token", return_value={"kid": "k"}), \
         patch("backend.routers.auth.httpx.AsyncClient", return_value=_FakeOIDCClient(ok_resp)), \
         patch("backend.routers.auth.jwt.decode", side_effect=JWTError("bad")):
        with pytest.raises(HTTPException, match="validation failed"):
            await _exchange_oidc_code("c", "n")

    with patch(
        "backend.routers.auth._get_oidc_discovery",
        AsyncMock(return_value={"token_endpoint": "https://id/token", "jwks_uri": "https://id/jwks", "issuer": "https://id"}),
    ), patch("backend.routers.auth._get_oidc_jwks", AsyncMock(return_value={"keys": [{}]})), \
         patch("backend.routers.auth._select_jwk_for_token", return_value={"kid": "k"}), \
         patch("backend.routers.auth.httpx.AsyncClient", return_value=_FakeOIDCClient(ok_resp)), \
         patch("backend.routers.auth.jwt.decode", return_value={"iss": "https://id", "sub": "u", "aud": ["cloudshell"], "nonce": "wrong"}):
        with pytest.raises(HTTPException, match="nonce mismatch"):
            await _exchange_oidc_code("c", "expected")


@pytest.mark.asyncio
async def test_oidc_login_missing_authorization_endpoint(monkeypatch):
    _oidc_env(monkeypatch)
    req = _FakeRequest()
    with patch("backend.routers.auth._get_oidc_discovery", AsyncMock(return_value={})):  # missing authorization endpoint
        with pytest.raises(HTTPException, match="missing authorization endpoint"):
            await oidc_login(request=req)


@pytest.mark.asyncio
async def test_oidc_callback_error_branches(monkeypatch):
    _oidc_env(monkeypatch)
    req = _FakeRequest()

    get_settings.cache_clear()
    monkeypatch.setenv("OIDC_ENABLED", "false")
    with pytest.raises(HTTPException, match="OIDC is disabled"):
        await oidc_callback(request=req, code="c", state="s", db=_FakeNonAsyncDb())

    _oidc_env(monkeypatch)

    with pytest.raises(HTTPException, match="OIDC authorization failed"):
        await oidc_callback(request=req, error="invalid_scope", db=_FakeNonAsyncDb())

    with pytest.raises(HTTPException, match="Missing OIDC code/state"):
        await oidc_callback(request=req, code=None, state=None, db=_FakeNonAsyncDb())

    with pytest.raises(HTTPException, match="Missing OIDC state cookie"):
        await oidc_callback(request=req, code="c", state="s", db=_FakeNonAsyncDb())

    req.cookies[OIDC_STATE_COOKIE_NAME] = "cookie-state"
    with pytest.raises(HTTPException, match="state mismatch"):
        await oidc_callback(request=req, code="c", state="other-state", db=_FakeNonAsyncDb())

    req.cookies[OIDC_STATE_COOKIE_NAME] = "same"
    with patch("backend.routers.auth._decode_oidc_state", side_effect=JWTError("bad")):
        with pytest.raises(HTTPException, match="invalid or expired"):
            await oidc_callback(request=req, code="c", state="same", db=_FakeNonAsyncDb())


@pytest.mark.asyncio
async def test_oidc_callback_success_direct(monkeypatch):
    _oidc_env(monkeypatch)
    req = _FakeRequest()
    req.cookies[OIDC_STATE_COOKIE_NAME] = "same"

    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    with patch("backend.routers.auth._decode_oidc_state", return_value={"nonce": "n", "next": "/dashboard"}), \
         patch("backend.routers.auth._exchange_oidc_code", new=AsyncMock(return_value="oidc:https://id:u1")), \
         patch("backend.routers.auth.ensure_user_for_username", new=AsyncMock()), \
         patch("backend.routers.auth._make_token", return_value=("jwt-token", expire, "jti-1")), \
         patch("backend.routers.auth.write_audit", new=AsyncMock()) as mock_audit:
        resp = await oidc_callback(request=req, code="c", state="same", db=_FakeNonAsyncDb())

    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"
    assert "set-cookie" in resp.headers
    assert mock_audit.await_count == 1


@pytest.mark.asyncio
async def test_import_config_direct_calls_process_bundle(monkeypatch):
    class _S:
        keys_dir = "/tmp/keys"

    monkeypatch.setattr("backend.routers.config_transfer.get_settings", lambda: _S())
    monkeypatch.setattr("backend.routers.config_transfer.get_owner_user_id", AsyncMock(return_value=7))
    monkeypatch.setattr(
        "backend.routers.config_transfer._process_import_bundle",
        AsyncMock(return_value={"imported": 0, "skipped": 0, "errors": 0, "messages": []}),
    )

    payload = b'{"format_version":1,"exported_at":"2026-01-01T00:00:00+00:00","device_count":0,"devices":[]}'
    upload = UploadFile(filename="cloudshell-config.json", file=io.BytesIO(payload))

    result = await import_config(file=upload, db=_FakeNonAsyncDb(), current_user="user-a")
    assert result["imported"] == 0


@pytest.mark.asyncio
async def test_validate_folder_exists_owner_scoped_path(db_session):
    owner = User(username="owner-a", auth_provider="local", is_admin=False)
    db_session.add(owner)
    await db_session.flush()

    folder = Folder(name="f1", owner_user_id=owner.id)
    db_session.add(folder)
    await db_session.commit()

    await validate_folder_exists(db_session, folder.id, owner_user_id=owner.id)


@pytest.mark.asyncio
async def test_devices_async_and_fallback_owner_paths(db_session, monkeypatch):
    owner = User(username="owner-b", auth_provider="local", is_admin=False)
    db_session.add(owner)
    await db_session.flush()

    folder = Folder(name="fd", owner_user_id=owner.id)
    db_session.add(folder)
    await db_session.flush()

    monkeypatch.setattr("backend.routers.devices.get_owner_user_id", AsyncMock(return_value=owner.id))

    payload = DeviceCreate(
        name="d1",
        hostname="10.0.0.1",
        port=22,
        username="root",
        auth_type=AuthType.password,
        password="pw",
        folder_id=folder.id,
    )
    with patch("backend.routers.devices.validate_folder_exists", new=AsyncMock()) as mock_validate:
        created = await create_device(payload=payload, db=db_session, _="owner-b")
    assert created.id is not None
    assert mock_validate.await_count == 1

    got = await get_device(created.id, db=db_session, _="owner-b")
    assert got.id == created.id

    up = DeviceUpdate(folder_id=folder.id)
    with patch("backend.routers.devices.validate_folder_exists", new=AsyncMock()) as mock_validate_update:
        await update_device(created.id, payload=up, db=db_session, _="owner-b")
    assert mock_validate_update.await_count == 1

    await delete_device(created.id, db=db_session, _="owner-b")

    # Non-AsyncSession fallback path for create folder validation branch.
    fake = _FakeNonAsyncDb()
    with patch("backend.routers.devices.get_owner_user_id", AsyncMock(return_value=1)), \
         patch("backend.routers.devices.validate_folder_exists", new=AsyncMock()) as mock_validate_non_async, \
         patch("backend.routers.devices.encrypt", return_value="enc"):
        await create_device(payload=payload, db=fake, _="owner-b")
    assert mock_validate_non_async.await_count == 1


@pytest.mark.asyncio
async def test_ftp_sftp_terminal_asyncsession_owner_query_paths(db_session, monkeypatch):
    owner = User(username="owner-c", auth_provider="local", is_admin=False)
    db_session.add(owner)
    await db_session.flush()

    ftp_dev = Device(
        name="ftp-d",
        hostname="10.0.0.2",
        port=21,
        username="u",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ftp,
        owner_user_id=owner.id,
        encrypted_password="enc",
    )
    sftp_dev = Device(
        name="sftp-d",
        hostname="10.0.0.3",
        port=22,
        username="u",
        auth_type=AuthType.password,
        connection_type=ConnectionType.sftp,
        owner_user_id=owner.id,
        encrypted_password="enc",
    )
    ssh_dev = Device(
        name="ssh-d",
        hostname="10.0.0.4",
        port=22,
        username="u",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
        owner_user_id=owner.id,
        encrypted_password="enc",
    )
    db_session.add_all([ftp_dev, sftp_dev, ssh_dev])
    await db_session.commit()

    req = _FakeRequest()
    monkeypatch.setattr("backend.routers.ftp.get_owner_user_id", AsyncMock(return_value=owner.id))
    monkeypatch.setattr("backend.routers.sftp.get_owner_user_id", AsyncMock(return_value=owner.id))
    monkeypatch.setattr("backend.routers.terminal.get_owner_user_id", AsyncMock(return_value=owner.id))

    with patch("backend.routers.ftp.decrypt", return_value="pw"), \
         patch("backend.routers.ftp.open_ftp_session", new=AsyncMock(return_value="ftp-sess")), \
         patch("backend.routers.ftp.write_audit", new=AsyncMock()):
        ftp_result = await open_ftp_session_route(device_id=ftp_dev.id, request=req, db=db_session, current_user="owner-c")
    assert ftp_result["session_id"] == "ftp-sess"

    with patch("backend.routers.sftp._resolve_device_credentials", new=AsyncMock(return_value=("pw", None, None))), \
         patch("backend.routers.sftp.probe_ssh_host_fingerprint", new=AsyncMock(side_effect=SSHHostFingerprintUnavailableError("x"))):
        with pytest.raises(HTTPException, match="host fingerprint unavailable"):
            await open_sftp_session_route(device_id=sftp_dev.id, request=req, db=db_session, current_user="owner-c", trust_host=True)

    with patch("backend.routers.terminal.decrypt", return_value="pw"), \
         patch("backend.routers.terminal.probe_ssh_host_fingerprint", new=AsyncMock(return_value="AA:BB:CC")), \
         patch("backend.routers.terminal.create_session", new=AsyncMock(return_value="term-sess")), \
         patch("backend.routers.terminal.write_audit", new=AsyncMock()):
        term_result = await open_terminal_session_route(device_id=ssh_dev.id, request=req, db=db_session, current_user="owner-c", trust_host=True)
    assert term_result["session_id"] == "term-sess"


@pytest.mark.asyncio
async def test_ftp_upload_progress_callback_handles_missing_status_entry():
    upload = UploadFile(filename="f.txt", file=io.BytesIO(b"abc"))
    tasks = BackgroundTasks()

    async def _fake_write(session_id, path, data, progress_cb):
        _ = session_id, path, data
        from backend.routers import ftp as ftp_router
        ftp_router._upload_status.clear()
        progress_cb(1)

    with patch("backend.routers.ftp.write_file_bytes", new=AsyncMock(side_effect=_fake_write)):
        result = await upload_file(
            session_id="sess-1",
            path="/tmp",
            file=upload,
            background_tasks=tasks,
            _="admin",
        )
        for task in tasks.tasks:
            await task()

    assert "upload_id" in result


@pytest.mark.asyncio
async def test_ftp_upload_progress_callback_handles_percent_calculation_error():
    class _BadSize:
        def __bool__(self):
            return True

        def __gt__(self, other):
            _ = other
            return True

        def __rtruediv__(self, other):
            _ = other
            raise RuntimeError("boom")

    upload = UploadFile(filename="f.txt", file=io.BytesIO(b"abcd"))
    tasks = BackgroundTasks()

    async def _fake_write(session_id, path, data, progress_cb):
        _ = session_id, path, data
        from backend.routers import ftp as ftp_router
        for entry in ftp_router._upload_status.values():
            entry["size_bytes"] = _BadSize()
        progress_cb(2)

    with patch("backend.routers.ftp.write_file_bytes", new=AsyncMock(side_effect=_fake_write)):
        result = await upload_file(
            session_id="sess-2",
            path="/tmp",
            file=upload,
            background_tasks=tasks,
            _="admin",
        )
        for task in tasks.tasks:
            await task()

    from backend.routers import ftp as ftp_router
    status = ftp_router._upload_status[result["upload_id"]]
    assert status.get("percent") is None
