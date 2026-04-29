"""Tests for backend/services/folder.py -- folder service layer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.models.folder import Folder
from backend.services.folder import (
    build_folder_tree,
    get_folder_or_404,
    validate_folder_exists,
    validate_parent_folder,
)


# -- Fake DB helper ------------------------------------------------------------

class _FakeDB:
    """Minimal AsyncSession duck-type for unit tests."""

    def __init__(self, get_return=None, execute_rows=None, scalar_value=0):
        self._get_return = get_return
        self._execute_rows = execute_rows or []
        self._scalar_value = scalar_value

    async def get(self, cls, pk):
        return self._get_return

    async def execute(self, stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = self._execute_rows
        mock_result.scalar.return_value = self._scalar_value
        return mock_result


# -- get_folder_or_404 ---------------------------------------------------------

async def test_get_folder_or_404_found():
    """get_folder_or_404 returns the folder when it exists."""
    folder = MagicMock(spec=Folder)
    db = _FakeDB(get_return=folder)
    result = await get_folder_or_404(db, 1)
    assert result is folder


async def test_get_folder_or_404_not_found():
    """get_folder_or_404 raises HTTP 404 when the folder does not exist."""
    db = _FakeDB(get_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_folder_or_404(db, 99)
    assert exc_info.value.status_code == 404
    assert "Folder not found" in exc_info.value.detail


# -- validate_parent_folder ----------------------------------------------------

async def test_validate_parent_folder_self_reference():
    """validate_parent_folder rejects moving a folder into itself."""
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        await validate_parent_folder(db, parent_id=5, current_folder_id=5)
    assert exc_info.value.status_code == 400
    assert "into itself" in exc_info.value.detail.lower()


async def test_validate_parent_folder_not_found():
    """validate_parent_folder raises 404 when the parent does not exist."""
    db = _FakeDB(get_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await validate_parent_folder(db, parent_id=99)
    assert exc_info.value.status_code == 404
    assert "Parent folder not found" in exc_info.value.detail


async def test_validate_parent_folder_success():
    """validate_parent_folder passes when parent exists and is not self."""
    parent = MagicMock(spec=Folder)
    db = _FakeDB(get_return=parent)
    await validate_parent_folder(db, parent_id=1, current_folder_id=2)


async def test_validate_parent_folder_no_current_id():
    """validate_parent_folder works for create (no current_folder_id)."""
    parent = MagicMock(spec=Folder)
    db = _FakeDB(get_return=parent)
    await validate_parent_folder(db, parent_id=1)


# -- validate_folder_exists ----------------------------------------------------

async def test_validate_folder_exists_found():
    """validate_folder_exists passes when the folder exists."""
    folder = MagicMock(spec=Folder)
    db = _FakeDB(get_return=folder)
    await validate_folder_exists(db, 1)


async def test_validate_folder_exists_not_found():
    """validate_folder_exists raises 404 when the folder does not exist."""
    db = _FakeDB(get_return=None)
    with pytest.raises(HTTPException) as exc_info:
        await validate_folder_exists(db, 99)
    assert exc_info.value.status_code == 404
    assert "Folder not found" in exc_info.value.detail


# -- build_folder_tree ---------------------------------------------------------

async def test_build_folder_tree_leaf():
    """build_folder_tree returns a correct dict for a leaf folder (no children)."""
    folder = MagicMock(spec=Folder)
    folder.id = 1
    folder.name = "leaf"
    folder.description = None
    folder.parent_folder_id = None
    folder.created_at = "2025-01-01T00:00:00Z"
    folder.updated_at = "2025-01-01T00:00:00Z"

    db = _FakeDB(execute_rows=[], scalar_value=0)
    result = await build_folder_tree(folder, db)

    assert result["id"] == 1
    assert result["name"] == "leaf"
    assert result["children"] == []
    assert result["device_count"] == 0


async def test_build_folder_tree_with_device_count():
    """build_folder_tree reports the device count for a folder."""
    folder = MagicMock(spec=Folder)
    folder.id = 2
    folder.name = "servers"
    folder.description = "prod"
    folder.parent_folder_id = None
    folder.created_at = "2025-01-01T00:00:00Z"
    folder.updated_at = "2025-01-01T00:00:00Z"

    db = _FakeDB(execute_rows=[], scalar_value=5)
    result = await build_folder_tree(folder, db)

    assert result["device_count"] == 5
