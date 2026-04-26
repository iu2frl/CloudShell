import { useState } from "react";
import { ChevronRight, ChevronDown, Trash2, PencilLine, FolderOpen } from "lucide-react";
import { FolderWithChildren, deleteFolder } from "../api/client";
import { useToast } from "./Toast";

interface FolderTreeItemProps {
  folder: FolderWithChildren;
  level: number;
  activeDeviceId: number | null;
  selectedFolderId: number | null;
  expandedFolders: Set<number>;
  onToggleExpand: (folderId: number) => void;
  onSelectFolder: (folderId: number) => void;
  onEdit: (folder: FolderWithChildren) => void;
  onDelete: (folderId: number) => void;
  renderDevices: (folderId: number) => React.ReactNode;
}

export function FolderTreeItem({
  folder,
  level,
  activeDeviceId,
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

  const hasChildren = folder.children && Array.isArray(folder.children) && folder.children.length > 0;

  return (
    <div>
      {/* Folder item */}
      <div
        onClick={() => !confirmId && onSelectFolder(folder.id)}
        className={`group flex items-center gap-2 px-4 py-2 cursor-pointer transition-colors select-none ml-${level * 4}
          ${isSelected ? "bg-blue-600/20 border-l-2 border-blue-500" : "hover:bg-slate-800 border-l-2 border-transparent"}
          ${confirmId ? "opacity-40 pointer-events-none" : ""}`}
        style={{ paddingLeft: `${8 + level * 16}px` }}
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

        {/* Device count badge */}
        {folder.device_count > 0 && (
          <span className="text-[10px] bg-slate-700 text-slate-400 rounded-full px-1.5 py-0.5 flex-shrink-0">
            {folder.device_count}
          </span>
        )}

        {/* Action icons */}
        {!deletingId && (
          <div className="absolute right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900/80 rounded pl-1">
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

        {/* Delete confirmation */}
        {confirmId === folder.id && (
          <div className="absolute right-2 flex items-center gap-1 bg-red-900/80 rounded px-2 py-1">
            <span className="text-[11px] text-red-200">Delete?</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteConfirm();
              }}
              className="text-[11px] text-red-300 hover:text-red-100 font-semibold"
            >
              Yes
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setConfirmId(null);
              }}
              className="text-[11px] text-slate-400 hover:text-slate-200"
            >
              No
            </button>
          </div>
        )}
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <>
          {/* Devices in this folder */}
          {renderDevices(folder.id)}

          {/* Child folders */}
          {folder.children && Array.isArray(folder.children) && folder.children.map((child) => (
            <FolderTreeItem
              key={child.id}
              folder={child}
              level={level + 1}
              activeDeviceId={activeDeviceId}
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
