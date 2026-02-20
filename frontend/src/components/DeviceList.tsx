import { Device, deleteDevice } from "../api/client";
import { Monitor, Trash2, PencilLine, Plus, RefreshCw } from "lucide-react";

interface Props {
  devices: Device[];
  activeDeviceId: number | null;
  loading: boolean;
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
  onConnect,
  onAdd,
  onEdit,
  onDelete,
  onRefresh,
}: Props) {
  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    if (!confirm("Delete this device?")) return;
    await deleteDevice(id);
    onDelete(id);
  };

  return (
    <aside className="w-72 flex-shrink-0 bg-slate-900 border-r border-slate-700 flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-4 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Monitor size={18} className="text-blue-400" />
          <span className="font-semibold text-white text-sm">Devices</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            title="Refresh"
            className="icon-btn"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
          <button onClick={onAdd} title="Add device" className="icon-btn text-blue-400">
            <Plus size={18} />
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto py-2">
        {devices.length === 0 && !loading && (
          <p className="text-slate-500 text-sm text-center mt-8 px-4">
            No devices yet.
            <br />
            Click <strong className="text-slate-300">+</strong> to add one.
          </p>
        )}
        {devices.map((d) => (
          <div
            key={d.id}
            onClick={() => onConnect(d)}
            className={`group flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors
              ${activeDeviceId === d.id
                ? "bg-blue-600/20 border-l-2 border-blue-500"
                : "hover:bg-slate-800 border-l-2 border-transparent"
              }`}
          >
            <div
              className={`w-2 h-2 rounded-full flex-shrink-0 ${
                activeDeviceId === d.id ? "bg-green-400" : "bg-slate-600"
              }`}
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-200 truncate">{d.name}</p>
              <p className="text-xs text-slate-500 truncate">
                {d.username}@{d.hostname}:{d.port}
              </p>
            </div>
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(d); }}
                className="icon-btn"
                title="Edit"
              >
                <PencilLine size={13} />
              </button>
              <button
                onClick={(e) => handleDelete(e, d.id)}
                className="icon-btn text-red-400 hover:text-red-300"
                title="Delete"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
