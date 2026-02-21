import { useState } from "react";
import { Device, deleteDevice } from "../api/client";
import { Monitor, Trash2, PencilLine, Plus, RefreshCw, KeyRound, Lock, ChevronsLeft, ChevronsRight } from "lucide-react";
import { useToast } from "./Toast";

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
}

export function DeviceList({
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
}: Props) {
  const toast = useToast();
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmId,  setConfirmId]  = useState<number | null>(null);

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

  return (
    <aside
      className={`flex-shrink-0 bg-slate-900 border-r border-slate-700 flex flex-col h-full transition-all duration-200
        ${collapsed ? "w-12" : "w-64"}`}
    >
      {collapsed ? (
        /* ── Collapsed: icon-only strip ── */
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
                  ${activeDeviceId === d.id
                    ? "bg-blue-600/30 text-blue-300"
                    : "text-slate-400 hover:bg-slate-800 hover:text-white"
                  }`}
              >
                <Monitor size={14} />
              </button>
            ))}
          </div>
        </div>
      ) : (
        /* ── Expanded: full sidebar ── */
        <>
          {/* Header */}
          <div className="px-4 py-3.5 border-b border-slate-700 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Monitor size={16} className="text-blue-400" />
              <span className="font-semibold text-white text-sm">Devices</span>
              {devices.length > 0 && (
                <span className="text-[10px] bg-slate-700 text-slate-400 rounded-full px-1.5 py-0.5">
                  {devices.length}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button onClick={onRefresh} title="Refresh" className="icon-btn">
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
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
                  No devices yet.<br />
                  Click <strong className="text-slate-300">+</strong> to add your first server.
                </p>
              </div>
            )}

            {devices.map((d) => {
              const isActive   = activeDeviceId === d.id;
              const isDeleting = deletingId === d.id;
              const isConfirm  = confirmId === d.id;

              return (
                <div key={d.id} className="relative">
                  <div
                    onClick={() => !isConfirm && onConnect(d)}
                    className={`group flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors select-none
                      ${isActive
                        ? "bg-blue-600/20 border-l-2 border-blue-500"
                        : "hover:bg-slate-800 border-l-2 border-transparent"
                      } ${isConfirm ? "opacity-40 pointer-events-none" : ""}`}
                  >
                    {/* Status dot */}
                    <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      isActive ? "bg-green-400" : "bg-slate-600"
                    }`} />

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <p className={`text-sm font-medium truncate ${
                          isActive ? "text-white" : "text-slate-200"
                        }`}>{d.name}</p>
                        {d.auth_type === "key"
                          ? <KeyRound size={10} className="text-slate-500 flex-shrink-0" aria-label="SSH key" />
                          : <Lock     size={10} className="text-slate-600 flex-shrink-0" aria-label="Password" />
                        }
                      </div>
                      <p className="text-[11px] text-slate-500 truncate">
                        {d.username}@{d.hostname}:{d.port}
                      </p>
                    </div>

                    {/* Action icons */}
                    {!isDeleting && (
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => { e.stopPropagation(); onEdit(d); }}
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
                    {isDeleting && (
                      <RefreshCw size={12} className="text-slate-500 animate-spin flex-shrink-0" />
                    )}
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
            })}
          </div>
        </>
      )}
    </aside>
  );
}
