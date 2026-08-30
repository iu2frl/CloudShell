"""Integration tests for per-user ownership isolation across core routes."""

from backend.routers.auth import _make_token



def _auth_headers(username: str) -> dict[str, str]:
    token, _, _ = _make_token(username)
    return {"Authorization": f"Bearer {token}"}



def _device_payload(name: str, connection_type: str = "ssh") -> dict:
    return {
        "name": name,
        "hostname": f"{name}.example.com",
        "port": 22,
        "username": "root",
        "auth_type": "password",
        "connection_type": connection_type,
        "password": "secret123",
    }


async def test_devices_are_isolated_between_users(client):
    user_a = _auth_headers("oidc:https://issuer.example:user-a")
    user_b = _auth_headers("oidc:https://issuer.example:user-b")

    created = await client.post("/api/devices/", json=_device_payload("alpha"), headers=user_a)
    assert created.status_code == 201
    device_id = created.json()["id"]

    list_a = await client.get("/api/devices/", headers=user_a)
    assert list_a.status_code == 200
    assert len(list_a.json()) == 1

    list_b = await client.get("/api/devices/", headers=user_b)
    assert list_b.status_code == 200
    assert list_b.json() == []

    get_b = await client.get(f"/api/devices/{device_id}", headers=user_b)
    assert get_b.status_code == 404

    update_b = await client.put(f"/api/devices/{device_id}", json={"name": "hijack"}, headers=user_b)
    assert update_b.status_code == 404

    delete_b = await client.delete(f"/api/devices/{device_id}", headers=user_b)
    assert delete_b.status_code == 404


async def test_folders_are_isolated_between_users(client):
    user_a = _auth_headers("oidc:https://issuer.example:user-a")
    user_b = _auth_headers("oidc:https://issuer.example:user-b")

    folder_resp = await client.post("/api/folders/", json={"name": "private-a"}, headers=user_a)
    assert folder_resp.status_code == 201
    folder_id = folder_resp.json()["id"]

    folder_list_a = await client.get("/api/folders/", headers=user_a)
    folder_list_b = await client.get("/api/folders/", headers=user_b)
    assert len(folder_list_a.json()) == 1
    assert folder_list_b.json() == []

    device_in_other_folder = await client.post(
        "/api/devices/",
        json={**_device_payload("owned-by-b"), "folder_id": folder_id},
        headers=user_b,
    )
    assert device_in_other_folder.status_code == 404


async def test_config_export_is_scoped_per_user(client):
    user_a = _auth_headers("oidc:https://issuer.example:user-a")
    user_b = _auth_headers("oidc:https://issuer.example:user-b")

    a_create = await client.post("/api/devices/", json=_device_payload("user-a-device"), headers=user_a)
    b_create = await client.post("/api/devices/", json=_device_payload("user-b-device"), headers=user_b)
    assert a_create.status_code == 201
    assert b_create.status_code == 201

    export_a = await client.get("/api/config/export", headers=user_a)
    export_b = await client.get("/api/config/export", headers=user_b)
    assert export_a.status_code == 200
    assert export_b.status_code == 200

    names_a = {d["name"] for d in export_a.json()["devices"]}
    names_b = {d["name"] for d in export_b.json()["devices"]}
    assert names_a == {"user-a-device"}
    assert names_b == {"user-b-device"}


async def test_config_export_local_admin_sees_all_devices(client):
    user_a = _auth_headers("oidc:https://issuer.example:user-a")
    user_b = _auth_headers("oidc:https://issuer.example:user-b")
    admin = _auth_headers("admin")

    create_a = await client.post("/api/devices/", json=_device_payload("a-device"), headers=user_a)
    create_b = await client.post("/api/devices/", json=_device_payload("b-device"), headers=user_b)
    assert create_a.status_code == 201
    assert create_b.status_code == 201

    export_admin = await client.get("/api/config/export", headers=admin)
    assert export_admin.status_code == 200
    names_admin = {d["name"] for d in export_admin.json()["devices"]}
    assert {"a-device", "b-device"}.issubset(names_admin)


async def test_terminal_session_open_rejects_cross_user_device(client):
    user_a = _auth_headers("oidc:https://issuer.example:user-a")
    user_b = _auth_headers("oidc:https://issuer.example:user-b")

    created = await client.post("/api/devices/", json=_device_payload("ssh-a"), headers=user_a)
    assert created.status_code == 201
    device_id = created.json()["id"]

    forbidden = await client.post(f"/api/terminal/session/{device_id}", headers=user_b)
    assert forbidden.status_code == 404


async def test_file_session_open_rejects_cross_user_device(client):
    user_a = _auth_headers("oidc:https://issuer.example:user-a")
    user_b = _auth_headers("oidc:https://issuer.example:user-b")

    ftp_created = await client.post(
        "/api/devices/",
        json=_device_payload("ftp-a", connection_type="ftp"),
        headers=user_a,
    )
    sftp_created = await client.post(
        "/api/devices/",
        json=_device_payload("sftp-a", connection_type="sftp"),
        headers=user_a,
    )
    assert ftp_created.status_code == 201
    assert sftp_created.status_code == 201

    ftp_id = ftp_created.json()["id"]
    sftp_id = sftp_created.json()["id"]

    ftp_open = await client.post(f"/api/ftp/session/{ftp_id}", headers=user_b)
    sftp_open = await client.post(f"/api/sftp/session/{sftp_id}", headers=user_b)
    assert ftp_open.status_code == 404
    assert sftp_open.status_code == 404
