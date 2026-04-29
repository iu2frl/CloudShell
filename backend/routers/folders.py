"""API endpoints for device folder management."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.device import Device
from backend.models.folder import Folder
from backend.routers.auth import get_current_user
from backend.services.folder import (
    build_folder_tree,
    get_folder_or_404,
    validate_parent_folder,
)

router = APIRouter(prefix="/folders", tags=["folders"])


# -- Schemas ------------------------------------------------------------------

class FolderCreate(BaseModel):
    """Schema for creating a new folder."""

    name: str
    description: Optional[str] = None
    parent_folder_id: Optional[int] = None


class FolderUpdate(BaseModel):
    """Schema for updating a folder."""

    name: Optional[str] = None
    description: Optional[str] = None
    parent_folder_id: Optional[int] = None


class FolderOut(BaseModel):
    """Schema for folder response."""

    id: int
    name: str
    description: Optional[str] = None
    parent_folder_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FolderWithChildrenOut(FolderOut):
    """Schema for folder response with nested children."""

    children: list["FolderWithChildrenOut"] = []
    device_count: int = 0


FolderWithChildrenOut.model_rebuild()


# -- Routes -------------------------------------------------------------------

@router.post("/", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    payload: FolderCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Create a new folder for organizing devices."""
    if payload.parent_folder_id is not None:
        await validate_parent_folder(db, payload.parent_folder_id)

    folder = Folder(
        name=payload.name,
        description=payload.description,
        parent_folder_id=payload.parent_folder_id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.get("/", response_model=list[FolderWithChildrenOut])
async def list_root_folders(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """List all root-level folders with their hierarchical structure."""
    result = await db.execute(
        select(Folder)
        .where(Folder.parent_folder_id.is_(None))
        .order_by(Folder.name)
    )
    folders = result.scalars().all()
    return [await build_folder_tree(folder, db) for folder in folders]


@router.get("/{folder_id}", response_model=FolderWithChildrenOut)
async def get_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Get a specific folder with its complete hierarchy."""
    folder = await get_folder_or_404(db, folder_id)
    return await build_folder_tree(folder, db)


@router.put("/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: int,
    payload: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Update a folder's details."""
    folder = await get_folder_or_404(db, folder_id)

    if payload.parent_folder_id is not None:
        await validate_parent_folder(db, payload.parent_folder_id, folder_id)

    if payload.name is not None:
        folder.name = payload.name
    if payload.description is not None:
        folder.description = payload.description
    if payload.parent_folder_id is not None:
        folder.parent_folder_id = payload.parent_folder_id

    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Delete a folder and move its direct contents to the parent folder."""
    folder = await get_folder_or_404(db, folder_id)
    target_parent_id = folder.parent_folder_id

    # Move devices to the parent folder (or root when deleting a root folder)
    await db.execute(
        update(Device)
        .where(Device.folder_id == folder.id)
        .values(folder_id=target_parent_id)
    )

    # Move direct subfolders to the parent folder as well
    await db.execute(
        update(Folder)
        .where(Folder.parent_folder_id == folder.id)
        .values(parent_folder_id=target_parent_id)
    )

    await db.flush()
    await db.delete(folder)
    await db.commit()
