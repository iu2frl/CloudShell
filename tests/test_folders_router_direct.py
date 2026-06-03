"""Direct tests for folder router handlers."""

import pytest

from backend.models.device import AuthType, ConnectionType, Device
from backend.models.folder import Folder
from backend.routers.folders import (
    FolderCreate,
    FolderUpdate,
    create_folder,
    delete_folder,
    get_folder,
    list_root_folders,
    update_folder,
)


@pytest.mark.asyncio
async def test_create_folder_direct(db_session):
    """Create a folder via the router handler."""
    payload = FolderCreate(name="Direct Root", description="Root folder")

    folder = await create_folder(payload, db_session, "user")

    assert folder.id is not None
    assert folder.name == "Direct Root"
    assert folder.description == "Root folder"
    assert folder.parent_folder_id is None


@pytest.mark.asyncio
async def test_list_root_folders_direct(db_session):
    """List root folders and include children via the handler."""
    root = await create_folder(FolderCreate(name="Root"), db_session, "user")
    child = await create_folder(
        FolderCreate(name="Child", parent_folder_id=root.id),
        db_session,
        "user",
    )

    folders = await list_root_folders(db_session, "user")

    assert len(folders) == 1
    assert folders[0]["id"] == root.id
    assert folders[0]["children"][0]["id"] == child.id


@pytest.mark.asyncio
async def test_get_folder_direct(db_session):
    """Get a folder tree via the handler."""
    root = await create_folder(FolderCreate(name="Root"), db_session, "user")
    child = await create_folder(
        FolderCreate(name="Child", parent_folder_id=root.id),
        db_session,
        "user",
    )

    folder = await get_folder(root.id, db_session, "user")

    assert folder["id"] == root.id
    assert folder["children"][0]["id"] == child.id


@pytest.mark.asyncio
async def test_update_folder_direct(db_session):
    """Update folder fields via the handler."""
    root = await create_folder(FolderCreate(name="Root"), db_session, "user")
    new_parent = await create_folder(
        FolderCreate(name="New Parent"),
        db_session,
        "user",
    )

    payload = FolderUpdate(
        name="Renamed",
        description="New description",
        parent_folder_id=new_parent.id,
    )
    folder = await update_folder(root.id, payload, db_session, "user")

    assert folder.name == "Renamed"
    assert folder.description == "New description"
    assert folder.parent_folder_id == new_parent.id


@pytest.mark.asyncio
async def test_delete_folder_direct_moves_children_and_devices(db_session):
    """Delete a folder and move its contents via the handler."""
    parent = await create_folder(FolderCreate(name="Parent"), db_session, "user")
    child = await create_folder(
        FolderCreate(name="Child", parent_folder_id=parent.id),
        db_session,
        "user",
    )

    device = Device(
        name="Device",
        hostname="host.example.com",
        port=22,
        username="root",
        auth_type=AuthType.password,
        connection_type=ConnectionType.ssh,
        folder_id=child.id,
    )
    db_session.add(device)

    subfolder = Folder(name="Sub", parent_folder_id=child.id)
    db_session.add(subfolder)
    await db_session.commit()

    await delete_folder(child.id, db_session, "user")

    moved_device = await db_session.get(Device, device.id)
    moved_subfolder = await db_session.get(Folder, subfolder.id)
    deleted_child = await db_session.get(Folder, child.id)

    assert moved_device.folder_id == parent.id
    assert moved_subfolder.parent_folder_id == parent.id
    assert deleted_child is None
