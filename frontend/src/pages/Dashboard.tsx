import { useEffect, useState } from "react";
import { Device, listDevices, logout } from "../api/client";
import { DeviceList } from "../components/DeviceList";
import { DeviceForm } from "../components/DeviceForm";
import { Terminal } from "../components/Terminal";
import { SessionBadge } from "../components/SessionBadge";
import { ChangePasswordModal } from "../components/ChangePasswordModal";
import { LogOut, Terminal as TerminalIcon } from "lucide-react";

interface Props {
  onLogout: () => void;
}

interface Tab {
  device: Device;
  key: number;
}

let tabCounter = 0;

export function Dashboard({ onLogout }: Props) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTab, setActiveTab] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editDevice, setEditDevice] = useState<Device | undefined>();
  const [showChangePw, setShowChangePw] = useState(false);

  const fetchDevices = async () => {
    setLoading(true);
    try {
      setDevices(await listDevices());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDevices();
  }, []);

  const handleConnect = (d: Device) => {
    // If already open, switch to that tab
    const existing = tabs.find((t) => t.device.id === d.id);
    if (existing) {
      setActiveTab(existing.key);
      return;
    }
    const tab: Tab = { device: d, key: ++tabCounter };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.key);
  };

  const handleCloseTab = (key: number) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.key !== key);
      if (activeTab === key) {
        setActiveTab(next.length > 0 ? next[next.length - 1].key : null);
      }
      return next;
    });
  };

  const handleLogout = () => {
    logout();
    onLogout();
  };

  const activeDevice = tabs.find((t) => t.key === activeTab)?.device ?? null;

  return (
    <div className="flex flex-col h-screen bg-surface overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          <TerminalIcon size={18} className="text-blue-400" />
          <span className="font-bold text-white text-sm tracking-tight">CloudShell</span>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 overflow-x-auto flex-1 mx-4">
          {tabs.map((tab) => (
            <div
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-3 py-1 rounded-md text-xs cursor-pointer select-none whitespace-nowrap transition-colors
                ${activeTab === tab.key
                  ? "bg-blue-600/30 text-blue-300 border border-blue-600/50"
                  : "text-slate-400 hover:bg-slate-800"
                }`}
            >
              <span>{tab.device.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleCloseTab(tab.key); }}
                className="text-slate-500 hover:text-slate-200 leading-none"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <button
          onClick={handleLogout}
          className="icon-btn text-slate-400 hover:text-red-400 flex items-center gap-2"
          title="Sign out"
        >
          <SessionBadge onClick={() => setShowChangePw(true)} />
          <LogOut size={16} />
        </button>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        <DeviceList
          devices={devices}
          activeDeviceId={activeDevice?.id ?? null}
          loading={loading}
          onConnect={handleConnect}
          onAdd={() => { setEditDevice(undefined); setShowForm(true); }}
          onEdit={(d) => { setEditDevice(d); setShowForm(true); }}
          onDelete={(id) => setDevices((prev) => prev.filter((d) => d.id !== id))}
          onRefresh={fetchDevices}
        />

        {/* Terminal area */}
        <main className="flex-1 overflow-hidden p-3">
          {tabs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <TerminalIcon size={48} className="text-slate-700 mb-4" />
              <p className="text-slate-500 text-sm">
                Select a device from the sidebar to open a terminal.
              </p>
            </div>
          ) : (
            tabs.map((tab) => (
              <div
                key={tab.key}
                className="h-full"
                style={{ display: tab.key === activeTab ? "block" : "none" }}
              >
                <Terminal deviceId={tab.device.id} />
              </div>
            ))
          )}
        </main>
      </div>

      {/* Device form modal */}
      {showForm && (
        <DeviceForm
          device={editDevice}
          onSave={(saved) => {
            setDevices((prev) =>
              editDevice
                ? prev.map((d) => (d.id === saved.id ? saved : d))
                : [...prev, saved]
            );
            setShowForm(false);
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Change password modal */}
      {showChangePw && (
        <ChangePasswordModal onClose={() => setShowChangePw(false)} />
      )}
    </div>
  );
}
