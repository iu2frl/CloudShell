"""
tests/test_devices_extended.py — extended device API tests covering branches
missed by the base device tests.

Covers:
- PUT /api/devices/{id}: update the password on a password-type device (line 144)
- PUT /api/devices/{id}: update the private key on a key-type device (line 146-148)
- DELETE /api/devices/{id}: deletes the encrypted key file for key-type devices (lines 161-169)
- _store_key helper is exercised by key-device create/update paths
"""
import os
import tempfile
from unittest.mock import patch

import pytest

from backend.services.crypto import generate_key_pair


# ── Helpers ───────────────────────────────────────────────────────────────────

def _password_payload(**kw) -> dict:
    return {
        "name": "pw-device",
        "hostname": "10.0.0.1",
        "port": 22,
        "username": "root",
        "auth_type": "password",
        "password": "original-secret",
        **kw,
    }


def _key_payload(pem: str, **kw) -> dict:
    return {
        "name": "key-device",
        "hostname": "10.0.0.2",
        "port": 22,
        "username": "deploy",
        "auth_type": "key",
        "private_key": pem,
        **kw,
    }


# ── PUT — update password on a password-type device ──────────────────────────

async def test_update_device_password(auth_client):
    """PUT /api/devices/{id} with a new password must accept and store it."""
    create_resp = await auth_client.post("/api/devices/", json=_password_payload())
    assert create_resp.status_code == 201
    device_id = create_resp.json()["id"]

    resp = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"password": "new-secret-password"},
    )
    assert resp.status_code == 200
    # The raw password is never returned, but the device update must succeed
    assert resp.json()["id"] == device_id


async def test_update_device_username(auth_client):
    """PUT /api/devices/{id} can update the SSH username."""
    create_resp = await auth_client.post("/api/devices/", json=_password_payload())
    device_id = create_resp.json()["id"]

    resp = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"username": "newuser"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "newuser"


# ── PUT — update private key on a key-type device ────────────────────────────

async def test_update_device_private_key(auth_client):
    """PUT /api/devices/{id} with a new private_key must accept and store it."""
    pem1, _ = generate_key_pair()
    pem2, _ = generate_key_pair()

    create_resp = await auth_client.post("/api/devices/", json=_key_payload(pem1))
    assert create_resp.status_code == 201
    device_id = create_resp.json()["id"]
    old_key_filename = create_resp.json()["key_filename"]

    resp = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"private_key": pem2},
    )
    assert resp.status_code == 200
    # key_filename should still be present (device still uses key auth)
    assert resp.json()["key_filename"] is not None


# ── DELETE — key file cleanup ─────────────────────────────────────────────────

async def test_delete_key_device_removes_key_file(auth_client):
    """Deleting a key-based device must also delete the encrypted key file from disk."""
    pem, _ = generate_key_pair()

    with tempfile.TemporaryDirectory() as keys_dir:
        # The route imports get_settings locally from backend.config, so patch there.
        from backend.config import Settings
        settings_obj = Settings(
            secret_key="test-secret-key-do-not-use-in-prod",
            admin_user="admin",
            admin_password="admin",
            data_dir="/tmp/cloudshell-pytest",
            keys_dir=keys_dir,
        )
        with patch("backend.config.get_settings", return_value=settings_obj):
            create_resp = await auth_client.post("/api/devices/", json=_key_payload(pem))
            assert create_resp.status_code == 201
            device_id = create_resp.json()["id"]
            key_filename = create_resp.json()["key_filename"]

            # Key file must exist on disk before deletion
            key_path = os.path.join(keys_dir, key_filename)
            assert os.path.exists(key_path), "Key file should exist after device creation"

            del_resp = await auth_client.delete(f"/api/devices/{device_id}")
            assert del_resp.status_code == 204

            # Key file must be gone after device deletion
            assert not os.path.exists(key_path), "Key file should be removed after device deletion"


async def test_delete_password_device_no_key_file(auth_client):
    """Deleting a password-based device must succeed even though there is no key file."""
    create_resp = await auth_client.post("/api/devices/", json=_password_payload())
    device_id = create_resp.json()["id"]

    resp = await auth_client.delete(f"/api/devices/{device_id}")
    assert resp.status_code == 204


# ── auth_type update ──────────────────────────────────────────────────────────

async def test_update_device_auth_type(auth_client):
    """PUT /api/devices/{id} can change the auth_type field."""
    create_resp = await auth_client.post("/api/devices/", json=_password_payload())
    device_id = create_resp.json()["id"]

    pem, _ = generate_key_pair()
    resp = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"auth_type": "key", "private_key": pem},
    )
    assert resp.status_code == 200
    assert resp.json()["auth_type"] == "key"
