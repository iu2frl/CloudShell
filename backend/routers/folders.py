"""API endpoints for device folder management."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, contains_eager

from backend.database import get_db
from backend.models.folder import Folder
from backend.routers.auth import get_current_user

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
    # Validate parent folder exists if specified
    if payload.parent_folder_id is not None:
        parent = await db.get(Folder, payload.parent_folder_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")

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
    """List all root-level folders (folders with no parent) with their hierarchical structure."""
    result = await db.execute(
        select(Folder)
        .where(Folder.parent_folder_id.is_(None))
        .order_by(Folder.name)
    )
    folders = result.scalars().all()
    return [await _folder_to_dict_with_children_async(folder, db) for folder in folders]


@router.get("/{folder_id}", response_model=FolderWithChildrenOut)
async def get_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Get a specific folder with its complete hierarchy."""
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id)
    )
    folder = result.scalars().first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return await _folder_to_dict_with_children_async(folder, db)


@router.put("/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: int,
    payload: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Update a folder's details."""
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Validate new parent folder if specified
    if payload.parent_folder_id is not None:
        if payload.parent_folder_id == folder_id:
            raise HTTPException(status_code=400, detail="Cannot move folder into itself")

        parent = await db.get(Folder, payload.parent_folder_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")

    # Update fields
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
    """Delete a folder and move its devices to the root level."""
    # Get folder with devices and children eager-loaded
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id)
        .options(selectinload(Folder.devices), selectinload(Folder.children))
    )
    folder = result.scalars().first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Move devices to root level (set folder_id to NULL)
    if folder.devices:
        for device in folder.devices:
            device.folder_id = None
            db.add(device)

    # Move subfolders to root level
    if folder.children:
        for subfolder in folder.children:
            subfolder.parent_folder_id = None
            db.add(subfolder)

    # Flush changes to ensure devices and subfolders are updated before deleting folder
    await db.flush()
    
    # Now delete the folder
    await db.delete(folder)
    await db.commit()


# -- Helpers ------------------------------------------------------------------

async def _folder_to_dict_with_children_async(folder: Folder, db: AsyncSession) -> dict:
    """Convert a folder instance to a dictionary with nested children, loading them from DB."""
    from backend.models.device import Device
    
    # Query for direct children
    children_result = await db.execute(
        select(Folder).where(Folder.parent_folder_id == folder.id).order_by(Folder.name)
    )
    children = children_result.scalars().all()
    
    # Query for device count in this folder
    device_count_result = await db.execute(
        select(func.count(Device.id)).where(Device.folder_id == folder.id)
    )
    device_count = device_count_result.scalar() or 0
    
    return {
        "id": folder.id,
        "name": folder.name,
        "description": folder.description,
        "parent_folder_id": folder.parent_folder_id,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
        "children": [
            await _folder_to_dict_with_children_async(child, db) 
            for child in children
        ],
        "device_count": device_count,
    }


def _folder_to_dict_with_children(folder: Folder) -> dict:
    """Convert a folder instance to a dictionary with nested children."""
    children_list = folder.children if folder.children is not None else []
    return {
        "id": folder.id,
        "name": folder.name,
        "description": folder.description,
        "parent_folder_id": folder.parent_folder_id,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
        "children": [_folder_to_dict_with_children(child) for child in sorted(children_list, key=lambda f: f.name)],
        "device_count": len(folder.devices) if folder.devices is not None else 0,
    }
