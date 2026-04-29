import { Device } from "../api/client";
import { Trash2, PencilLine, RefreshCw, KeyRound, Lock, FolderOpen } from "lucide-react";

interface DeviceRowProps {
  device: Device;
  isActive: boolean;
  isDeleting: boolean;
  isConfirm: boolean;
  level?: number;
  onConnect: (d: Device) => void;
  onEdit: (d: Device) => void;
  onMove: (d: Device) => void;
  onDeleteClick: (e: React.MouseEvent, id: number) => void;
  onDeleteConfirm: (id: number) => void;
  onDeleteCancel: () => void;
}

export function DeviceRow({
  device,
  isActive,
  isDeleting,
  isConfirm,
  level = 0,
  onConnect,
  onEdit,
  onMove,
  onDeleteClick,
  onDeleteConfirm,
  onDeleteCancel,
}: DeviceRowProps) {
  return (
    <div className="relative">
      <div
        onClick={() => onConnect(device)}
        className={`group flex items-center gap-3 py-3 cursor-pointer transition-colors select-none
          ${isActive ? "bg-blue-600/20 border-l-2 border-blue-500" : "hover:bg-slate-800 border-l-2 border-transparent"}`}
        style={{ paddingLeft: `${16 + level * 12}px`, paddingRight: '16px' }}
      >
        {/* Status dot - only show when connected */}
        {isActive && <div className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-green-400" />}

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className={`text-sm font-medium group-hover:truncate ${isActive ? "text-white" : "text-slate-200"}`}>
              {device.name}
            </p>
            {device.auth_type === "key" ? (
              <KeyRound size={10} className="text-slate-500 flex-shrink-0" aria-label="SSH key" />
            ) : (
              <Lock size={10} className="text-slate-600 flex-shrink-0" aria-label="Password" />
            )}
            {device.connection_type === "ssh" && (
              <span className="text-[9px] bg-green-900/60 text-green-300 border border-green-700/50 rounded px-1 leading-4 flex-shrink-0">
                SSH
              </span>
            )}
            {device.connection_type === "sftp" && (
              <span className="text-[9px] bg-purple-900/60 text-purple-300 border border-purple-700/50 rounded px-1 leading-4 flex-shrink-0">
                SFTP
              </span>
            )}
            {device.connection_type === "ftp" && (
              <span className="text-[9px] bg-orange-900/60 text-orange-300 border border-orange-700/50 rounded px-1 leading-4 flex-shrink-0">
                FTP
              </span>
            )}
            {device.connection_type === "ftps" && (
              <span className="text-[9px] bg-orange-900/60 text-orange-300 border border-orange-700/50 rounded px-1 leading-4 flex-shrink-0">
                FTPS
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 truncate">
            {device.username}@{device.hostname}:{device.port}
          </p>
        </div>

        {/* Action icons */}
        {!isDeleting && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900/80 rounded pl-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onMove(device);
              }}
              className="icon-btn"
              aria-label="Move to folder"
            >
              <FolderOpen size={12} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onEdit(device);
              }}
              className="icon-btn"
              aria-label="Edit"
            >
              <PencilLine size={12} />
            </button>
            <button
              onClick={(e) => onDeleteClick(e, device.id)}
              className="icon-btn text-red-400 hover:text-red-300"
              aria-label="Delete"
            >
              <Trash2 size={12} />
            </button>
          </div>
        )}
        {isDeleting && <RefreshCw size={12} className="text-slate-500 animate-spin flex-shrink-0" />}
      </div>

      {/* Delete confirmation modal */}
      {isConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onDeleteCancel}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`device-delete-title-${device.id}`}
            className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-800 p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id={`device-delete-title-${device.id}`} className="text-lg font-semibold text-white">
              Delete device?
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-300">
              This will permanently remove the device and its saved credentials.
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              Are you sure you want to delete {device.name}?
            </p>
            <div className="mt-6 flex gap-3">
              <button
                onClick={onDeleteCancel}
                className="btn-secondary flex-1"
              >
                Cancel
              </button>
              <button
                onClick={() => onDeleteConfirm(device.id)}
                className="btn-danger flex-1"
              >
                Delete device
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
