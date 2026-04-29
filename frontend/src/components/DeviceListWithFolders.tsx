import { useState, useEffect } from "react";
import { Device, FolderWithChildren, deleteDevice, listFolders, updateDevice } from "../api/client";
import { Monitor, Plus, RefreshCw, ChevronsLeft, ChevronsRight, FolderPlus, HardDrive } from "lucide-react";
import { useToast } from "./Toast";
import { FolderTreeItem } from "./FolderTreeItem";
import { FolderModal } from "./FolderModal";
import { DeviceRow } from "./DeviceRow";

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
  const folderIdsWithDevices = new Set(
    devices
      .filter((d) => d.folder_id != null)
      .map((d) => d.folder_id as number),
  );

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
      const data = await listFolders();
      setFolders(data);
      onFoldersChanged?.();
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

  const renderDevices = (deviceList: Device[], level: number) => {
    return deviceList.map((d) => (
      <DeviceRow
        key={d.id}
        device={d}
        isActive={activeDeviceId === d.id}
        isDeleting={deletingId === d.id}
        isConfirm={confirmId === d.id}
        level={level}
        onConnect={onConnect}
        onEdit={onEdit}
        onMove={handleMoveDevice}
        onDeleteClick={handleDeleteClick}
        onDeleteConfirm={handleDeleteConfirm}
        onDeleteCancel={() => setConfirmId(null)}
      />
    ));
  };

  const renderDeviceInFolder = (folderId: number, level: number) => {
    const devicesInFolder = devices.filter((d) => d.folder_id === folderId);
    return renderDevices(devicesInFolder, level + 1);
  };

  const renderRootDevices = () => {
    const rootDevices = devices.filter((d) => !d.folder_id);
    return renderDevices(rootDevices, 0);
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
                  <HardDrive size={14} />
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
            {devices.length === 0 && folders.length === 0 && !loading && (
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
                folderIdsWithDevices={folderIdsWithDevices}
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="move-device-title"
            className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-800 p-6 shadow-xl"
          >
            <h3 id="move-device-title" className="text-lg font-semibold text-white mb-4">Move Device</h3>
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
                className="btn-secondary"
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
