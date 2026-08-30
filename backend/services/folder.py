"""Reusable service functions for folder operations."""

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.folder import Folder

logger = logging.getLogger(__name__)


async def get_folder_or_404(
    db: AsyncSession,
    folder_id: int,
    owner_user_id: int | None = None,
) -> Folder:
    """Fetch a folder by ID or raise HTTP 404.

    Args:
        db: Async database session.
        folder_id: Primary key of the folder.

    Returns:
        The matching Folder instance.

    Raises:
        HTTPException: 404 when the folder does not exist.
    """
    stmt = select(Folder).where(Folder.id == folder_id)
    if owner_user_id is not None:
        stmt = stmt.where(Folder.owner_user_id == owner_user_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if not folder:
        logger.debug("Folder %d not found", folder_id)
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


async def validate_parent_folder(
    db: AsyncSession,
    parent_id: int,
    current_folder_id: int | None = None,
    owner_user_id: int | None = None,
) -> None:
    """Validate that a parent folder exists and is not the folder itself.

    Args:
        db: Async database session.
        parent_id: The proposed parent folder ID.
        current_folder_id: When updating, the ID of the folder being moved
            (to reject self-referential moves).

    Raises:
        HTTPException: 400 if the folder would become its own parent.
        HTTPException: 404 if the parent folder does not exist.
    """
    if current_folder_id is not None and parent_id == current_folder_id:
        raise HTTPException(
            status_code=400, detail="Cannot move folder into itself"
        )
    stmt = select(Folder).where(Folder.id == parent_id)
    if owner_user_id is not None:
        stmt = stmt.where(Folder.owner_user_id == owner_user_id)
    result = await db.execute(stmt)
    parent = result.scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent folder not found")


async def validate_folder_exists(
    db: AsyncSession,
    folder_id: int,
    owner_user_id: int | None = None,
) -> None:
    """Validate that a folder exists (used when assigning a device to a folder).

    Args:
        db: Async database session.
        folder_id: Primary key of the folder to check.

    Raises:
        HTTPException: 404 when the folder does not exist.
    """
    stmt = select(Folder).where(Folder.id == folder_id)
    if owner_user_id is not None:
        stmt = stmt.where(Folder.owner_user_id == owner_user_id)
    result = await db.execute(stmt)
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")


async def build_folder_tree(
    folder: Folder,
    db: AsyncSession,
    owner_user_id: int | None = None,
) -> dict:
    """Build a nested dictionary representation of a folder and its children.

    Recursively loads children from the database and counts devices
    in each folder.

    Args:
        folder: The root folder to start from.
        db: Async database session.

    Returns:
        A dictionary matching the FolderWithChildrenOut schema.
    """
    children_stmt = (
        select(Folder)
        .where(Folder.parent_folder_id == folder.id)
        .order_by(Folder.name)
    )
    if owner_user_id is not None:
        children_stmt = children_stmt.where(Folder.owner_user_id == owner_user_id)

    children_result = await db.execute(children_stmt)
    children = children_result.scalars().all()

    device_count_stmt = select(Device.id).where(Device.folder_id == folder.id)
    if owner_user_id is not None:
        device_count_stmt = device_count_stmt.where(Device.owner_user_id == owner_user_id)

    device_count_result = await db.execute(device_count_stmt)
    device_count = len(device_count_result.scalars().all())

    return {
        "id": folder.id,
        "name": folder.name,
        "description": folder.description,
        "parent_folder_id": folder.parent_folder_id,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
        "children": [
            await build_folder_tree(child, db, owner_user_id=owner_user_id) for child in children
        ],
        "device_count": device_count,
    }
