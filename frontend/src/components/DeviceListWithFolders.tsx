import { useState, useEffect } from "react";
import { Device, FolderWithChildren, deleteDevice, listFolders, updateDevice } from "../api/client";
import { Monitor, Trash2, PencilLine, Plus, RefreshCw, KeyRound, Lock, ChevronsLeft, ChevronsRight, FolderPlus, Folder as FolderIcon, FolderOpen } from "lucide-react";
import { useToast } from "./Toast";
import { FolderTreeItem } from "./FolderTreeItem";
import { FolderModal } from "./FolderModal";

interface Props {
  devices: Device[];
  activeDeviceId: number | null;
  loading: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onConnect: (d: Device) => void;
  onAdd: () => void;
  onEdit: (d: Device) => void;
  onDelete: (id: number) => void;
  onRefresh: () => void;
  onFoldersChanged?: () => void;
}

export function DeviceListWithFolders({
  devices,
  activeDeviceId,
  loading,
  collapsed,
  onToggleCollapse,
  onConnect,
  onAdd,
  onEdit,
  onDelete,
  onRefresh,
  onFoldersChanged,
}: Props) {
  const toast = useToast();
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [folders, setFolders] = useState<FolderWithChildren[]>([]);
  const [expandedFolders, setExpandedFolders] = useState<Set<number>>(new Set());
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [editingFolder, setEditingFolder] = useState<FolderWithChildren | null>(null);
  const [showMoveModal, setShowMoveModal] = useState(false);
  const [movingDevice, setMovingDevice] = useState<Device | null>(null);

  // Load folders
  useEffect(() => {
    const loadFolders = async () => {
      try {
        const data = await listFolders();
        console.log("Folders data from API:", JSON.stringify(data, null, 2));
        setFolders(data);
      } catch (err) {
        // Folders might not exist yet, which is fine
      }
    };
    loadFolders();
  }, []);

  const handleDeleteClick = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    setConfirmId(id);
  };

  const handleDeleteConfirm = async (id: number) => {
    setConfirmId(null);
    setDeletingId(id);
    try {
      await deleteDevice(id);
      onDelete(id);
      toast.success("Device deleted");
    } catch (err) {
      toast.error(`Delete failed: ${err}`);
    } finally {
      setDeletingId(null);
    }
  };

  const handleToggleExpand = (folderId: number) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(folderId)) {
      newExpanded.delete(folderId);
    } else {
      newExpanded.add(folderId);
    }
    setExpandedFolders(newExpanded);
  };

  const handleFolderSaved = async () => {
    setShowFolderModal(false);
    setEditingFolder(null);
    try {
      const data = await listFolders();
      setFolders(data);
      onFoldersChanged?.();
    } catch (err) {
      toast.error(`Failed to refresh folders: ${err}`);
    }
  };

  const handleDeleteFolder = async () => {
    try {
      const data = await listFolders();
      setFolders(data);
      onRefresh();
      onFoldersChanged?.();
    } catch (err) {
      toast.error(`Failed to refresh folders: ${err}`);
    }
  };

  const handleMoveDevice = (device: Device) => {
    setMovingDevice(device);
    setShowMoveModal(true);
  };

  const handleMoveConfirm = async (folderId: number | null) => {
    if (!movingDevice) return;
    
    try {
      await updateDevice(movingDevice.id, { folder_id: folderId });
      // Refresh devices to reflect the move
      onRefresh();
      toast.success(`Device moved to ${folderId ? 'folder' : 'root'}`);
    } catch (err) {
      toast.error(`Failed to move device: ${err}`);
    } finally {
      setShowMoveModal(false);
      setMovingDevice(null);
    }
  };

  const getFlattenedFolders = (folders: FolderWithChildren[], prefix = ""): Array<{folder: FolderWithChildren, path: string}> => {
    const result: Array<{folder: FolderWithChildren, path: string}> = [];
    
    folders.forEach((folder) => {
      const currentPath = prefix ? `${prefix} > ${folder.name}` : folder.name;
      result.push({ folder, path: currentPath });
      
      if (folder.children && Array.isArray(folder.children) && folder.children.length > 0) {
        result.push(...getFlattenedFolders(folder.children, currentPath));
      }
    });
    
    return result;
  };

  const renderFolderTreeForMove = (folders: FolderWithChildren[]): React.ReactElement[] => {
    const flattened = getFlattenedFolders(folders);
    
    return flattened.map(({ folder, path }) => (
      <button
        key={`folder-${folder.id}`}
        onClick={() => handleMoveConfirm(folder.id)}
        className="w-full text-left px-3 py-2 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors"
      >
        {path}
      </button>
    ));
  };

  const renderDeviceInFolder = (folderId: number) => {
    const devicesInFolder = devices.filter((d) => d.folder_id === folderId);
    return devicesInFolder.map((d) => {
      const isActive = activeDeviceId === d.id;
      const isDeleting = deletingId === d.id;
      const isConfirm = confirmId === d.id;

      return (
        <div key={d.id} className="relative">
          <div
            onClick={() => !isConfirm && onConnect(d)}
            className={`group flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors select-none ml-12
              ${isActive ? "bg-blue-600/20 border-l-2 border-blue-500" : "hover:bg-slate-800 border-l-2 border-transparent"}
              ${isConfirm ? "opacity-40 pointer-events-none" : ""}`}
          >
            {/* Status dot - only show when connected */}
            {isActive && <div className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-green-400" />}

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <p className={`text-sm font-medium group-hover:truncate ${isActive ? "text-white" : "text-slate-200"}`}>
                  {d.name}
                </p>
                {d.auth_type === "key" ? (
                  <KeyRound size={10} className="text-slate-500 flex-shrink-0" aria-label="SSH key" />
                ) : (
                  <Lock size={10} className="text-slate-600 flex-shrink-0" aria-label="Password" />
                )}
                {d.connection_type === "ssh" && (
                  <span className="text-[9px] bg-green-900/60 text-green-300 border border-green-700/50 rounded px-1 leading-4 flex-shrink-0">
                    SSH
                  </span>
                )}
                {d.connection_type === "sftp" && (
                  <span className="text-[9px] bg-purple-900/60 text-purple-300 border border-purple-700/50 rounded px-1 leading-4 flex-shrink-0">
                    SFTP
                  </span>
                )}
                {d.connection_type === "ftp" && (
                  <span className="text-[9px] bg-orange-900/60 text-orange-300 border border-orange-700/50 rounded px-1 leading-4 flex-shrink-0">
                    FTP
                  </span>
                )}
                {d.connection_type === "ftps" && (
                  <span className="text-[9px] bg-orange-900/60 text-orange-300 border border-orange-700/50 rounded px-1 leading-4 flex-shrink-0">
                    FTPS
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 truncate">
                {d.username}@{d.hostname}:{d.port}
              </p>
            </div>

            {/* Action icons */}
            {!isDeleting && (
              <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900/80 rounded pl-1">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleMoveDevice(d);
                  }}
                  className="icon-btn"
                  aria-label="Move to folder"
                >
                  <FolderOpen size={12} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit(d);
                  }}
                  className="icon-btn"
                  aria-label="Edit"
                >
                  <PencilLine size={12} />
                </button>
                <button
                  onClick={(e) => handleDeleteClick(e, d.id)}
                  className="icon-btn text-red-400 hover:text-red-300"
                  aria-label="Delete"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            )}
            {isDeleting && <RefreshCw size={12} className="text-slate-500 animate-spin flex-shrink-0" />}
          </div>

          {/* Inline confirm prompt */}
          {isConfirm && (
            <div className="absolute inset-0 bg-slate-900/95 flex items-center justify-between px-4 gap-2 z-10">
              <span className="text-xs text-slate-300 truncate">Delete "{d.name}"?</span>
              <div className="flex gap-1.5 flex-shrink-0">
                <button
                  onClick={() => setConfirmId(null)}
                  className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleDeleteConfirm(d.id)}
                  className="text-xs px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          )}
        </div>
      );
    });
  };

  const renderRootDevices = () => {
    const rootDevices = devices.filter((d) => !d.folder_id);
    return rootDevices.map((d) => {
      const isActive = activeDeviceId === d.id;
      const isDeleting = deletingId === d.id;
      const isConfirm = confirmId === d.id;

      return (
        <div key={d.id} className="relative">
          <div
            onClick={() => !isConfirm && onConnect(d)}
            className={`group flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors select-none
              ${isActive ? "bg-blue-600/20 border-l-2 border-blue-500" : "hover:bg-slate-800 border-l-2 border-transparent"}
              ${isConfirm ? "opacity-40 pointer-events-none" : ""}`}
          >
            {/* Status dot - only show when connected */}
            {isActive && <div className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-green-400" />}

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <p className={`text-sm font-medium group-hover:truncate ${isActive ? "text-white" : "text-slate-200"}`}>
                  {d.name}
                </p>
                {d.auth_type === "key" ? (
                  <KeyRound size={10} className="text-slate-500 flex-shrink-0" aria-label="SSH key" />
                ) : (
                  <Lock size={10} className="text-slate-600 flex-shrink-0" aria-label="Password" />
                )}
                {d.connection_type === "ssh" && (
                  <span className="text-[9px] bg-green-900/60 text-green-300 border border-green-700/50 rounded px-1 leading-4 flex-shrink-0">
                    SSH
                  </span>
                )}
                {d.connection_type === "sftp" && (
                  <span className="text-[9px] bg-purple-900/60 text-purple-300 border border-purple-700/50 rounded px-1 leading-4 flex-shrink-0">
                    SFTP
                  </span>
                )}
                {d.connection_type === "ftp" && (
                  <span className="text-[9px] bg-orange-900/60 text-orange-300 border border-orange-700/50 rounded px-1 leading-4 flex-shrink-0">
                    FTP
                  </span>
                )}
                {d.connection_type === "ftps" && (
                  <span className="text-[9px] bg-orange-900/60 text-orange-300 border border-orange-700/50 rounded px-1 leading-4 flex-shrink-0">
                    FTPS
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 truncate">
                {d.username}@{d.hostname}:{d.port}
              </p>
            </div>

            {/* Action icons */}
            {!isDeleting && (
              <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900/80 rounded pl-1">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleMoveDevice(d);
                  }}
                  className="icon-btn"
                  aria-label="Move to folder"
                >
                  <FolderOpen size={12} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit(d);
                  }}
                  className="icon-btn"
                  aria-label="Edit"
                >
                  <PencilLine size={12} />
                </button>
                <button
                  onClick={(e) => handleDeleteClick(e, d.id)}
                  className="icon-btn text-red-400 hover:text-red-300"
                  aria-label="Delete"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            )}
            {isDeleting && <RefreshCw size={12} className="text-slate-500 animate-spin flex-shrink-0" />}
          </div>

          {/* Inline confirm prompt */}
          {isConfirm && (
            <div className="absolute inset-0 bg-slate-900/95 flex items-center justify-between px-4 gap-2 z-10">
              <span className="text-xs text-slate-300 truncate">Delete "{d.name}"?</span>
              <div className="flex gap-1.5 flex-shrink-0">
                <button
                  onClick={() => setConfirmId(null)}
                  className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleDeleteConfirm(d.id)}
                  className="text-xs px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          )}
        </div>
      );
    });
  };

  return (
    <aside
      className={`flex-shrink-0 bg-slate-900 border-r border-slate-700 flex flex-col h-full transition-all duration-200
        ${collapsed ? "w-12" : "w-64"}`}
    >
      {collapsed ? (
        /* -- Collapsed: icon-only strip -- */
        <div className="flex flex-col items-center gap-2 py-3">
          <button
            onClick={onToggleCollapse}
            className="icon-btn text-slate-400 hover:text-white"
            title="Expand sidebar"
          >
            <ChevronsRight size={16} />
          </button>
          <div className="w-px h-px" /> {/* spacer */}
          <button onClick={onAdd} title="Add device" className="icon-btn text-blue-400 hover:text-blue-300">
            <Plus size={16} />
          </button>
          <button onClick={onRefresh} title="Refresh" className="icon-btn">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
          <div className="mt-2 flex flex-col items-center gap-1 w-full overflow-y-auto">
            {devices.map((d) => (
              <button
                key={d.id}
                onClick={() => onConnect(d)}
                title={d.name}
                className={`w-8 h-8 flex items-center justify-center rounded transition-colors
                  ${activeDeviceId === d.id ? "bg-blue-600/30 text-blue-300" : "text-slate-400 hover:bg-slate-800 hover:text-white"}`}
              >
                {d.connection_type === "sftp" || d.connection_type === "ftp" || d.connection_type === "ftps" ? (
                  <FolderIcon size={14} />
                ) : (
                  <Monitor size={14} />
                )}
              </button>
            ))}
          </div>
        </div>
      ) : (
        /* -- Expanded: full sidebar -- */
        <>
          {/* Header */}
          <div className="px-4 py-3.5 border-b border-slate-700 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Monitor size={16} className="text-blue-400" />
              <span className="font-semibold text-white text-sm">Devices</span>
            </div>
            <div className="flex items-center gap-1">
              <button onClick={onRefresh} title="Refresh" className="icon-btn">
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              </button>
              <button
                onClick={() => {
                  setEditingFolder(null);
                  setShowFolderModal(true);
                }}
                title="Create folder"
                className="icon-btn text-amber-400 hover:text-amber-300"
              >
                <FolderPlus size={16} />
              </button>
              <button onClick={onAdd} title="Add device" className="icon-btn text-blue-400 hover:text-blue-300">
                <Plus size={16} />
              </button>
              <button
                onClick={onToggleCollapse}
                className="icon-btn text-slate-400 hover:text-white"
                title="Collapse sidebar"
              >
                <ChevronsLeft size={16} />
              </button>
            </div>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto py-1">
            {devices.length === 0 && !loading && (
              <div className="flex flex-col items-center justify-center h-full text-center px-4 pb-8">
                <Monitor size={32} className="text-slate-700 mb-3" />
                <p className="text-slate-500 text-xs leading-relaxed">
                  No devices yet.
                  <br />
                  Click <strong className="text-slate-300">+</strong> to add your first server.
                </p>
              </div>
            )}

            {/* Root devices */}
            {renderRootDevices()}

            {/* Folders */}
            {folders.map((folder) => (
              <FolderTreeItem
                key={folder.id}
                folder={folder}
                level={0}
                activeDeviceId={activeDeviceId}
                selectedFolderId={selectedFolderId}
                expandedFolders={expandedFolders}
                onToggleExpand={handleToggleExpand}
                onSelectFolder={setSelectedFolderId}
                onEdit={(f) => {
                  setEditingFolder(f);
                  setShowFolderModal(true);
                }}
                onDelete={handleDeleteFolder}
                renderDevices={renderDeviceInFolder}
              />
            ))}
          </div>
        </>
      )}

      {/* Folder Modal */}
      <FolderModal
        isOpen={showFolderModal}
        editingFolder={editingFolder}
        availableFolders={getFlattenedFolders(folders)}
        onClose={() => {
          setShowFolderModal(false);
          setEditingFolder(null);
        }}
        onSave={handleFolderSaved}
      />

      {/* Move Device Modal */}
      {showMoveModal && movingDevice && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 w-96 max-w-[90vw]">
            <h3 className="text-lg font-semibold text-white mb-4">Move Device</h3>
            <p className="text-slate-300 mb-4">
              Move "{movingDevice.name}" to a folder:
            </p>
            
            <div className="space-y-2 mb-6 max-h-64 overflow-y-auto border border-slate-600 rounded p-2">
              <button
                onClick={() => handleMoveConfirm(null)}
                className="w-full text-left px-3 py-2 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors"
              >
                Root (no folder)
              </button>
              {renderFolderTreeForMove(folders)}
            </div>
            
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowMoveModal(false);
                  setMovingDevice(null);
                }}
                className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
