"""
tests/test_devices_api.py — integration tests for the device management HTTP API.

Tests cover:
- GET /api/devices/           requires auth; returns empty list; returns created devices
- POST /api/devices/          requires auth; creates password device; creates key device;
                              rejects password type without password; rejects key type without key;
                              returns 201 with correct fields; default port is 22
- GET /api/devices/{id}       requires auth; returns 404 for missing device; returns correct fields
- PUT /api/devices/{id}       requires auth; updates individual fields; returns 404 for missing device
- DELETE /api/devices/{id}    requires auth; deletes device; returns 204; returns 404 for missing
"""
from backend.services.crypto import generate_key_pair


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _key_device_payload(pem: str, **overrides) -> dict:
    return {
        "name": "key-server",
        "hostname": "10.0.0.1",
        "port": 2222,
        "username": "deploy",
        "auth_type": "key",
        "private_key": pem,
        **overrides,
    }


# ── GET /api/devices/ ─────────────────────────────────────────────────────────

async def test_list_devices_requires_auth(client):
    """Unauthenticated GET /api/devices/ must return 401."""
    resp = await client.get("/api/devices/")
    assert resp.status_code == 401


async def test_list_devices_empty(auth_client):
    """Empty device list must be returned as an empty JSON array."""
    resp = await auth_client.get("/api/devices/")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_devices_returns_created(auth_client):
    """Devices created via POST must appear in GET /api/devices/."""
    await auth_client.post("/api/devices/", json=_password_device_payload(name="alpha"))
    await auth_client.post("/api/devices/", json=_password_device_payload(name="beta"))

    resp = await auth_client.get("/api/devices/")
    assert resp.status_code == 200
    names = {d["name"] for d in resp.json()}
    assert names == {"alpha", "beta"}


async def test_list_devices_sorted_by_name(auth_client):
    """GET /api/devices/ must return devices ordered alphabetically by name."""
    await auth_client.post("/api/devices/", json=_password_device_payload(name="zzz"))
    await auth_client.post("/api/devices/", json=_password_device_payload(name="aaa"))
    await auth_client.post("/api/devices/", json=_password_device_payload(name="mmm"))

    resp = await auth_client.get("/api/devices/")
    names = [d["name"] for d in resp.json()]
    assert names == sorted(names)


# ── POST /api/devices/ ────────────────────────────────────────────────────────

async def test_create_password_device_returns_201(auth_client):
    """Creating a password-based device must return 201."""
    resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    assert resp.status_code == 201


async def test_create_password_device_response_fields(auth_client):
    """The created device must include all expected fields."""
    resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "test-server"
    assert body["hostname"] == "192.168.1.100"
    assert body["port"] == 22
    assert body["username"] == "root"
    assert body["auth_type"] == "password"
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


async def test_create_device_default_port(auth_client):
    """When port is omitted the default value must be 22."""
    payload = _password_device_payload()
    del payload["port"]
    resp = await auth_client.post("/api/devices/", json=payload)
    assert resp.status_code == 201
    assert resp.json()["port"] == 22


async def test_create_password_device_no_password_returns_400(auth_client):
    """Submitting auth_type=password without a password must return 400."""
    payload = _password_device_payload()
    del payload["password"]
    resp = await auth_client.post("/api/devices/", json=payload)
    assert resp.status_code == 400


async def test_create_key_device_no_key_returns_400(auth_client):
    """Submitting auth_type=key without a private_key must return 400."""
    resp = await auth_client.post(
        "/api/devices/",
        json={
            "name": "key-server",
            "hostname": "10.0.0.1",
            "port": 22,
            "username": "root",
            "auth_type": "key",
        },
    )
    assert resp.status_code == 400


async def test_create_key_device(auth_client):
    """A key-based device should be created successfully with a real PEM key."""
    private_pem, _ = generate_key_pair()
    resp = await auth_client.post(
        "/api/devices/",
        json=_key_device_payload(private_pem),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["auth_type"] == "key"
    # key_filename should be stored but the raw private key must not be in the response
    assert "private_key" not in body


async def test_create_device_requires_auth(client):
    """Creating a device without auth must return 401."""
    resp = await client.post("/api/devices/", json=_password_device_payload())
    assert resp.status_code == 401


# ── GET /api/devices/{id} ─────────────────────────────────────────────────────

async def test_get_device_returns_correct_data(auth_client):
    """GET /api/devices/{id} returns the exact device that was created."""
    create_resp = await auth_client.post(
        "/api/devices/",
        json=_password_device_payload(name="my-box", hostname="1.2.3.4", port=2222),
    )
    device_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/devices/{device_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == device_id
    assert body["name"] == "my-box"
    assert body["hostname"] == "1.2.3.4"
    assert body["port"] == 2222


async def test_get_device_not_found(auth_client):
    """GET /api/devices/{id} with a non-existent ID must return 404."""
    resp = await auth_client.get("/api/devices/99999")
    assert resp.status_code == 404


async def test_get_device_requires_auth(client):
    """GET /api/devices/{id} without auth must return 401."""
    resp = await client.get("/api/devices/1")
    assert resp.status_code == 401


# ── PUT /api/devices/{id} ─────────────────────────────────────────────────────

async def test_update_device_name(auth_client):
    """PUT /api/devices/{id} must update the device name."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload(name="old-name"))
    device_id = create_resp.json()["id"]

    resp = await auth_client.put(f"/api/devices/{device_id}", json={"name": "new-name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-name"


async def test_update_device_hostname_and_port(auth_client):
    """PUT /api/devices/{id} must update hostname and port independently."""
    create_resp = await auth_client.post(
        "/api/devices/",
        json=_password_device_payload(hostname="old.host", port=22),
    )
    device_id = create_resp.json()["id"]

    resp = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"hostname": "new.host", "port": 2222},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hostname"] == "new.host"
    assert body["port"] == 2222


async def test_update_device_not_found(auth_client):
    """PUT /api/devices/{id} with a non-existent ID must return 404."""
    resp = await auth_client.put("/api/devices/99999", json={"name": "ghost"})
    assert resp.status_code == 404


async def test_update_device_requires_auth(client):
    """PUT /api/devices/{id} without auth must return 401."""
    resp = await client.put("/api/devices/1", json={"name": "x"})
    assert resp.status_code == 401


# ── DELETE /api/devices/{id} ──────────────────────────────────────────────────

async def test_delete_device_returns_204(auth_client):
    """Deleting an existing device must return 204."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    resp = await auth_client.delete(f"/api/devices/{device_id}")
    assert resp.status_code == 204


async def test_delete_device_removes_it(auth_client):
    """After deletion, the device must no longer be found via GET."""
    create_resp = await auth_client.post("/api/devices/", json=_password_device_payload())
    device_id = create_resp.json()["id"]

    await auth_client.delete(f"/api/devices/{device_id}")

    get_resp = await auth_client.get(f"/api/devices/{device_id}")
    assert get_resp.status_code == 404


async def test_delete_device_not_found(auth_client):
    """DELETE /api/devices/{id} with a non-existent ID must return 404."""
    resp = await auth_client.delete("/api/devices/99999")
    assert resp.status_code == 404


async def test_delete_device_not_in_list(auth_client):
    """After deletion the device must not appear in the device list."""
    create_resp = await auth_client.post(
        "/api/devices/", json=_password_device_payload(name="to-delete")
    )
    device_id = create_resp.json()["id"]

    await auth_client.delete(f"/api/devices/{device_id}")

    list_resp = await auth_client.get("/api/devices/")
    ids = [d["id"] for d in list_resp.json()]
    assert device_id not in ids


async def test_delete_device_requires_auth(client):
    """DELETE /api/devices/{id} without auth must return 401."""
    resp = await client.delete("/api/devices/1")
    assert resp.status_code == 401
