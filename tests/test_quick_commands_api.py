"""
tests/test_quick_commands_api.py — integration tests for the quick commands HTTP API.

Tests cover:
- GET  /api/quick_commands/{device_id}   requires auth; returns empty list for a known device
                                          with no commands stored yet; returns stored commands;
                                          gracefully handles corrupt JSON in the DB
- PUT  /api/quick_commands/{device_id}   requires auth; upserts new commands; updates existing;
                                          is isolated per user
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

# -- Helpers -------------------------------------------------------------------

def _password_device_payload(**overrides) -> dict:
    return {
        "name": "test-server",
        "hostname": "192.168.1.100",
        "port": 22,
        "username": "root",
        "auth_type": "password",
        "password": "s3cr3t",
        **overrides,
    }


QUICK_COMMANDS_PAYLOAD = [
    {"id": "abc-1", "label": "uptime", "command": "uptime"},
    {"id": "abc-2", "label": "df",     "command": "df -h"},
]

QUICK_COMMANDS_UPDATED = [
    {"id": "abc-1", "label": "uptime", "command": "uptime -p"},
    {"id": "abc-3", "label": "free",   "command": "free -m"},
]


@pytest_asyncio.fixture()
async def admin_client(client: AsyncClient):
    """Return an AsyncClient pre-authenticated as the default admin user."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest_asyncio.fixture()
async def admin_user1_device(admin_client: AsyncClient):
    """Create a device owned by the default admin user."""
    resp = await admin_client.post("/api/devices/", json=_password_device_payload(name="qcmd-host"))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture()
async def admin_user2_device(admin_client: AsyncClient):
    """Create a second device owned by the same admin user (for cross-device isolation)."""
    resp = await admin_client.post("/api/devices/", json=_password_device_payload(name="qcmd-host-2"))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# -- GET /api/quick_commands/{device_id} ---------------------------------------

async def test_get_empty_when_no_commands(admin_client: AsyncClient, admin_user1_device: int):
    """GET for a device that has never had commands saved must return an empty array."""
    resp = await admin_client.get(f"/api/quick_commands/{admin_user1_device}")
    assert resp.status_code == 200
    assert resp.json() == {"commands": []}


async def test_get_returns_stored_commands(admin_client: AsyncClient, admin_user1_device: int):
    """GET must return the commands previously saved via PUT."""
    await admin_client.put(
        f"/api/quick_commands/{admin_user1_device}",
        json={"commands": QUICK_COMMANDS_PAYLOAD},
    )
    resp = await admin_client.get(f"/api/quick_commands/{admin_user1_device}")
    assert resp.status_code == 200
    assert resp.json()["commands"] == QUICK_COMMANDS_PAYLOAD


async def test_get_unknown_device_returns_empty(admin_client: AsyncClient):
    """GET for a device with no stored commands (or one the user can't access) returns an empty list."""
    resp = await admin_client.get("/api/quick_commands/99999")
    assert resp.status_code == 200
    assert resp.json() == {"commands": []}


# -- PUT /api/quick_commands/{device_id} ---------------------------------------

async def test_put_upserts_new_commands(admin_client: AsyncClient, admin_user1_device: int):
    """First PUT for a device must insert a new row and echo back the payload."""
    resp = await admin_client.put(
        f"/api/quick_commands/{admin_user1_device}",
        json={"commands": QUICK_COMMANDS_PAYLOAD},
    )
    assert resp.status_code == 200
    assert resp.json()["commands"] == QUICK_COMMANDS_PAYLOAD

    # Verify persistence with a subsequent GET
    get_resp = await admin_client.get(f"/api/quick_commands/{admin_user1_device}")
    assert get_resp.json()["commands"] == QUICK_COMMANDS_PAYLOAD


async def test_put_updates_existing_commands(admin_client: AsyncClient, admin_user1_device: int):
    """Subsequent PUT calls must overwrite the previous commands entirely."""
    await admin_client.put(
        f"/api/quick_commands/{admin_user1_device}",
        json={"commands": QUICK_COMMANDS_PAYLOAD},
    )
    await admin_client.put(
        f"/api/quick_commands/{admin_user1_device}",
        json={"commands": QUICK_COMMANDS_UPDATED},
    )
    resp = await admin_client.get(f"/api/quick_commands/{admin_user1_device}")
    assert resp.json()["commands"] == QUICK_COMMANDS_UPDATED


async def test_put_isolated_per_device(admin_client: AsyncClient, admin_user1_device: int, admin_user2_device: int):
    """Commands saved on one device must not leak to another device."""
    await admin_client.put(
        f"/api/quick_commands/{admin_user1_device}",
        json={"commands": QUICK_COMMANDS_PAYLOAD},
    )
    r1 = await admin_client.get(f"/api/quick_commands/{admin_user1_device}")
    r2 = await admin_client.get(f"/api/quick_commands/{admin_user2_device}")
    assert r1.json()["commands"] == QUICK_COMMANDS_PAYLOAD
    assert r2.json()["commands"] == []


async def test_get_corrupt_json_returns_empty(
    admin_client: AsyncClient,
    admin_user1_device: int,
    db_session,
):
    """GET must return an empty array when commands_json contains invalid JSON (DB corruption guard)."""
    from backend.models.quick_command import QuickCommand
    from backend.routers.auth import get_owner_user_id

    uid = await get_owner_user_id(db_session, "admin")
    row = QuickCommand(owner_user_id=uid, device_id=admin_user1_device, commands_json="{not valid json")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    resp = await admin_client.get(f"/api/quick_commands/{admin_user1_device}")
    assert resp.status_code == 200
    assert resp.json() == {"commands": []}


async def test_put_unknown_device_returns_404(admin_client: AsyncClient):
    """PUT for a non-existent device must return 404."""
    resp = await admin_client.put(
        "/api/quick_commands/99999",
        json={"commands": QUICK_COMMANDS_PAYLOAD},
    )
    assert resp.status_code == 404
