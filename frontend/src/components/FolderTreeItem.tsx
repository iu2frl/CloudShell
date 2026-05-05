import { useEffect, useState } from "react";
import { ChevronRight, ChevronDown, Trash2, PencilLine, FolderOpen } from "lucide-react";
import { FolderWithChildren, deleteFolder } from "../api/client";
import { useToast } from "./Toast";

interface FolderTreeItemProps {
  folder: FolderWithChildren;
  level: number;
  activeDeviceId: number | null;
  folderIdsWithDevices: Set<number>;
  selectedFolderId: number | null;
  expandedFolders: Set<number>;
  onToggleExpand: (folderId: number) => void;
  onSelectFolder: (folderId: number) => void;
  onEdit: (folder: FolderWithChildren) => void;
  onDelete: (folderId: number) => void;
  renderDevices: (folderId: number, level: number) => React.ReactNode;
}

export function FolderTreeItem({
  folder,
  level,
  activeDeviceId,
  folderIdsWithDevices,
  selectedFolderId,
  expandedFolders,
  onToggleExpand,
  onSelectFolder,
  onEdit,
  onDelete,
  renderDevices,
}: FolderTreeItemProps) {
  const toast = useToast();
  const isExpanded = expandedFolders.has(folder.id);
  const isSelected = selectedFolderId === folder.id;
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmId(folder.id);
  };

  const handleDeleteCancel = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setConfirmId(null);
  };

  useEffect(() => {
    if (confirmId !== folder.id) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setConfirmId(null);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [confirmId, folder.id]);

  const handleDeleteConfirm = async () => {
    setConfirmId(null);
    setDeletingId(folder.id);
    try {
      await deleteFolder(folder.id);
      onDelete(folder.id);
      toast.success("Folder deleted");
    } catch (err) {
      toast.error(`Delete failed: ${err}`);
    } finally {
      setDeletingId(null);
    }
  };

  const hasChildren =
    (folder.children && Array.isArray(folder.children) && folder.children.length > 0) ||
    folderIdsWithDevices.has(folder.id);

  return (
    <div data-test-folder={`${folder.name}-level-${level}-haschildren-${hasChildren}`}>
      {/* Folder item */}
      <div
        onClick={() => !confirmId && onSelectFolder(folder.id)}
        className={`group relative flex items-center gap-2 px-4 py-2 cursor-pointer transition-colors select-none ml-${level * 4}
          ${isSelected ? "bg-blue-600/20 border-l-2 border-blue-500" : "hover:bg-slate-800 border-l-2 border-transparent"}
          ${confirmId ? "opacity-40 pointer-events-none" : ""}`}
        style={{ paddingLeft: `${8 + level * 12}px` }}
      >
        {/* Expand/collapse button */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(folder.id);
            }}
            className="flex-shrink-0 text-slate-400 hover:text-white transition-colors"
          >
            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        ) : (
          <div className="flex-shrink-0 w-4" />
        )}

        {/* Folder icon */}
        <FolderOpen size={14} className="text-amber-400 flex-shrink-0" />

        {/* Folder name */}
        <span className="text-sm font-medium text-slate-200 truncate flex-1">
          {folder.name}
        </span>

        {/* Action icons */}
        {!deletingId && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900/80 rounded pl-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onEdit(folder);
              }}
              className="icon-btn text-slate-400 hover:text-blue-400"
              title="Edit folder"
            >
              <PencilLine size={14} />
            </button>
            <button
              onClick={handleDeleteClick}
              className="icon-btn text-slate-400 hover:text-red-400"
              title="Delete folder"
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}

      </div>

      {/* Delete confirmation modal */}
      {confirmId === folder.id && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={handleDeleteCancel}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`folder-delete-title-${folder.id}`}
            className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-800 p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id={`folder-delete-title-${folder.id}`} className="text-lg font-semibold text-white">
              Delete folder?
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-300">
              Devices in this folder will not be deleted. They will be moved to the parent folder.
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              Are you sure you want to delete {folder.name}?
            </p>
            <div className="mt-6 flex gap-3">
              <button
                onClick={handleDeleteCancel}
                className="btn-secondary flex-1"
              >
                Cancel
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteConfirm();
                }}
                className="btn-danger flex-1"
              >
                Delete folder
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Expanded content */}
      {isExpanded && (
        <>
          {/* Devices in this folder */}
          {renderDevices(folder.id, level)}

          {/* Child folders */}
          {folder.children && Array.isArray(folder.children) && folder.children.map((child) => (
            <FolderTreeItem
              key={child.id}
              folder={child}
              level={level + 1}
              activeDeviceId={activeDeviceId}
              folderIdsWithDevices={folderIdsWithDevices}
              selectedFolderId={selectedFolderId}
              expandedFolders={expandedFolders}
              onToggleExpand={onToggleExpand}
              onSelectFolder={onSelectFolder}
              onEdit={onEdit}
              onDelete={onDelete}
              renderDevices={renderDevices}
            />
          ))}
        </>
      )}
    </div>
  );
}
