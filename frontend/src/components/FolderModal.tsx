import { useState } from "react";
import { Folder, FolderWithChildren, createFolder, updateFolder } from "../api/client";

interface FolderModalProps {
  isOpen: boolean;
  editingFolder: FolderWithChildren | null;
  availableFolders: FolderWithChildren[];
  onClose: () => void;
  onSave: (folder: Folder) => void;
}

export function FolderModal({
  isOpen,
  editingFolder,
  availableFolders,
  onClose,
  onSave,
}: FolderModalProps) {
  const [name, setName] = useState(editingFolder?.name ?? "");
  const [description, setDescription] = useState(editingFolder?.description ?? "");
  const [parentFolderId, setParentFolderId] = useState<number | null>(
    editingFolder?.parent_folder_id ?? null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Reset form when modal opens/closes or editing folder changes
  const handleOpenChange = (open: boolean) => {
    if (!open) {
      onClose();
      setName("");
      setDescription("");
      setParentFolderId(null);
      setError("");
    }
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Folder name is required");
      return;
    }

    setLoading(true);
    setError("");
    try {
      let savedFolder: Folder;
      if (editingFolder) {
        savedFolder = await updateFolder(editingFolder.id, {
          name: name.trim(),
          description: description.trim() || undefined,
          parent_folder_id: parentFolderId,
        });
      } else {
        savedFolder = await createFolder({
          name: name.trim(),
          description: description.trim() || undefined,
          parent_folder_id: parentFolderId,
        });
      }
      onSave(savedFolder);
      handleOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save folder");
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-xl w-96 p-6 border border-slate-700">
        <h2 className="text-lg font-semibold text-white mb-4">
          {editingFolder ? "Edit Folder" : "New Folder"}
        </h2>

        <div className="space-y-4">
          {/* Name field */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Folder Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Servers"
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              disabled={loading}
            />
          </div>

          {/* Description field */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Description (optional)
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Organize your servers..."
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none h-16"
              disabled={loading}
            />
          </div>

          {/* Parent folder selector */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Parent Folder (optional)
            </label>
            <select
              value={parentFolderId ?? ""}
              onChange={(e) => setParentFolderId(e.target.value ? parseInt(e.target.value) : null)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-slate-100 focus:outline-none focus:border-blue-500"
              disabled={loading}
            >
              <option value="">Root</option>
              {availableFolders.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  {folder.name}
                </option>
              ))}
            </select>
          </div>

          {/* Error message */}
          {error && <div className="text-sm text-red-400">{error}</div>}
        </div>

        {/* Buttons */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={() => handleOpenChange(false)}
            className="flex-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-100 rounded transition-colors disabled:opacity-50"
            disabled={loading}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors disabled:opacity-50"
            disabled={loading}
          >
            {loading ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
