"""Test suite for device folder organization functionality."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_folder(auth_client: AsyncClient):
    """Test creating a new folder."""
    response = await auth_client.post(
        "/api/folders/",
        json={
            "name": "Production Servers",
            "description": "All production servers",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Production Servers"
    assert data["description"] == "All production servers"
    assert data["parent_folder_id"] is None


@pytest.mark.asyncio
async def test_create_folder_with_parent(auth_client: AsyncClient):
    """Test creating a nested folder."""
    # Create parent folder
    parent_response = await auth_client.post(
        "/api/folders/",
        json={"name": "USA"},
    )
    parent_id = parent_response.json()["id"]

    # Create child folder
    response = await auth_client.post(
        "/api/folders/",
        json={
            "name": "New York",
            "parent_folder_id": parent_id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New York"
    assert data["parent_folder_id"] == parent_id


@pytest.mark.asyncio
async def test_list_folders_hierarchy(auth_client: AsyncClient):
    """Test listing folders with hierarchical structure."""
    # Create folder structure
    parent_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Parent"},
    )
    parent_id = parent_response.json()["id"]

    child_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Child", "parent_folder_id": parent_id},
    )

    # List root folders
    response = await auth_client.get(
        "/api/folders/",
    )
    assert response.status_code == 200
    folders = response.json()
    assert len(folders) == 1
    assert folders[0]["name"] == "Parent"
    assert len(folders[0]["children"]) == 1
    assert folders[0]["children"][0]["name"] == "Child"


@pytest.mark.asyncio
async def test_get_folder_with_children(auth_client: AsyncClient):
    """Test getting a specific folder with its children."""
    # Create folder structure
    parent_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Parent"},
    )
    parent_id = parent_response.json()["id"]

    await auth_client.post(
        "/api/folders/",
        json={"name": "Child", "parent_folder_id": parent_id},
    )

    # Get parent folder
    response = await auth_client.get(
        f"/api/folders/{parent_id}",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Parent"
    assert len(data["children"]) == 1


@pytest.mark.asyncio
async def test_update_folder(auth_client: AsyncClient):
    """Test updating folder details."""
    # Create folder
    create_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Original Name"},
    )
    folder_id = create_response.json()["id"]

    # Update folder
    response = await auth_client.put(
        f"/api/folders/{folder_id}",
        json={
            "name": "Updated Name",
            "description": "Updated description",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


@pytest.mark.asyncio
async def test_delete_folder(auth_client: AsyncClient):
    """Test deleting a folder."""
    # Create folder
    create_response = await auth_client.post(
        "/api/folders/",
        json={"name": "To Delete"},
    )
    folder_id = create_response.json()["id"]

    # Delete folder
    response = await auth_client.delete(
        f"/api/folders/{folder_id}",
    )
    assert response.status_code == 204

    # Verify it's deleted
    response = await auth_client.get(
        f"/api/folders/{folder_id}",
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_device_with_folder(auth_client: AsyncClient):
    """Test creating a device in a folder."""
    # Create folder
    folder_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Web Servers"},
    )
    folder_id = folder_response.json()["id"]

    # Create device in folder
    response = await auth_client.post(
        "/api/devices/",
        json={
            "name": "Web Server 1",
            "hostname": "web1.example.com",
            "port": 22,
            "username": "root",
            "auth_type": "password",
            "connection_type": "ssh",
            "password": "secret123",
            "folder_id": folder_id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["folder_id"] == folder_id


@pytest.mark.asyncio
async def test_move_device_to_folder(auth_client: AsyncClient):
    """Test moving a device to a folder."""
    # Create device
    device_response = await auth_client.post(
        "/api/devices/",
        json={
            "name": "My Server",
            "hostname": "server.example.com",
            "port": 22,
            "username": "root",
            "auth_type": "password",
            "connection_type": "ssh",
            "password": "secret123",
        },
    )
    device_id = device_response.json()["id"]

    # Create folder
    folder_response = await auth_client.post(
        "/api/folders/",
        json={"name": "My Servers"},
    )
    folder_id = folder_response.json()["id"]

    # Move device to folder
    response = await auth_client.put(
        f"/api/devices/{device_id}",
        json={"folder_id": folder_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["folder_id"] == folder_id


@pytest.mark.asyncio
async def test_delete_folder_moves_devices_to_root(auth_client: AsyncClient):
    """Test that deleting a folder moves its devices to root level."""
    # Create folder
    folder_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Temporary"},
    )
    folder_id = folder_response.json()["id"]

    # Create device in folder
    device_response = await auth_client.post(
        "/api/devices/",
        json={
            "name": "Device in Temp",
            "hostname": "temp.example.com",
            "port": 22,
            "username": "root",
            "auth_type": "password",
            "connection_type": "ssh",
            "password": "secret123",
            "folder_id": folder_id,
        },
    )
    device_id = device_response.json()["id"]

    # Delete folder
    await auth_client.delete(
        f"/api/folders/{folder_id}",
    )

    # Verify device is now at root level
    response = await auth_client.get(
        f"/api/devices/{device_id}",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["folder_id"] is None


@pytest.mark.asyncio
async def test_delete_nested_folder_moves_devices_to_root(auth_client: AsyncClient):
    """Test that deleting a nested folder moves its devices to root level."""
    cloud_response = await auth_client.post(
        "/api/folders/",
        json={"name": "cloud"},
    )
    cloud_id = cloud_response.json()["id"]

    asd_response = await auth_client.post(
        "/api/folders/",
        json={"name": "asd", "parent_folder_id": cloud_id},
    )
    asd_id = asd_response.json()["id"]

    device_response = await auth_client.post(
        "/api/devices/",
        json={
            "name": "Nested Device",
            "hostname": "nested.example.com",
            "port": 22,
            "username": "root",
            "auth_type": "password",
            "connection_type": "ssh",
            "password": "secret123",
            "folder_id": asd_id,
        },
    )
    device_id = device_response.json()["id"]

    response = await auth_client.delete(f"/api/folders/{asd_id}")
    assert response.status_code == 204

    device_lookup = await auth_client.get(f"/api/devices/{device_id}")
    assert device_lookup.status_code == 200
    assert device_lookup.json()["folder_id"] is None

    cloud_lookup = await auth_client.get(f"/api/folders/{cloud_id}")
    assert cloud_lookup.status_code == 200
    assert cloud_lookup.json()["children"] == []


@pytest.mark.asyncio
async def test_cannot_move_folder_into_itself(auth_client: AsyncClient):
    """Test that moving a folder into itself is rejected."""
    # Create folder
    folder_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Test Folder"},
    )
    folder_id = folder_response.json()["id"]

    # Try to move folder into itself
    response = await auth_client.put(
        f"/api/folders/{folder_id}",
        json={"parent_folder_id": folder_id},
    )
    assert response.status_code == 400
    assert "into itself" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_folder_device_count(auth_client: AsyncClient):
    """Test that folder device_count is calculated correctly."""
    # Create folder
    folder_response = await auth_client.post(
        "/api/folders/",
        json={"name": "Web Servers"},
    )
    folder_id = folder_response.json()["id"]

    # Create devices in folder
    for i in range(3):
        await auth_client.post(
            "/api/devices/",
            json={
                "name": f"Server {i+1}",
                "hostname": f"server{i+1}.example.com",
                "port": 22,
                "username": "root",
                "auth_type": "password",
                "connection_type": "ssh",
                "password": "secret123",
                "folder_id": folder_id,
            },
        )

    # List folders and check device count
    response = await auth_client.get(
        "/api/folders/",
    )
    assert response.status_code == 200
    folders = response.json()
    assert len(folders) > 0
    folder = next((f for f in folders if f["id"] == folder_id), None)
    assert folder is not None
    assert folder["device_count"] == 3


@pytest.mark.asyncio
async def test_create_folder_requires_auth(client: AsyncClient):
    """Test that folder creation requires authentication."""
    response = await client.post(
        "/api/folders/",
        json={"name": "Test"},
    )
    assert response.status_code == 401
