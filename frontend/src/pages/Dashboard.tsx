import { useEffect, useState } from "react";
import { Device, listDevices, logout } from "../api/client";
import { DeviceList } from "../components/DeviceList";
import { DeviceForm } from "../components/DeviceForm";
import { Terminal } from "../components/Terminal";
import { SessionBadge } from "../components/SessionBadge";
import { ChangePasswordModal } from "../components/ChangePasswordModal";
import { useToast } from "../components/Toast";
import { KeyRound, LogOut, Terminal as TerminalIcon } from "lucide-react";

interface Props {
  onLogout: () => void;
}

interface Tab {
  device: Device;
  key: number;
}

let tabCounter = 0;

export function Dashboard({ onLogout }: Props) {
  const [devices, setDevices]       = useState<Device[]>([]);
  const [loading, setLoading]       = useState(true);
  const [tabs, setTabs]             = useState<Tab[]>([]);
  const [activeTab, setActiveTab]   = useState<number | null>(null);
  const [showForm, setShowForm]     = useState(false);
  const [editDevice, setEditDevice] = useState<Device | undefined>();
  const [showChangePw, setShowChangePw] = useState(false);
  const toast = useToast();

  const fetchDevices = async () => {
    setLoading(true);
    try {
      setDevices(await listDevices());
    } catch {
      toast.error("Failed to load devices");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDevices(); }, []);

  const handleConnect = (d: Device) => {
    const existing = tabs.find((t) => t.device.id === d.id);
    if (existing) { setActiveTab(existing.key); return; }
    const tab: Tab = { device: d, key: ++tabCounter };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.key);
  };

  const handleCloseTab = (key: number) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.key !== key);
      if (activeTab === key)
        setActiveTab(next.length > 0 ? next[next.length - 1].key : null);
      return next;
    });
  };

  const handleLogout = async () => {
    await logout();
    onLogout();
  };

  const activeDevice = tabs.find((t) => t.key === activeTab)?.device ?? null;

  return (
    <div className="flex flex-col h-screen bg-surface overflow-hidden">
      {/* ── Top bar ────────────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-700 flex-shrink-0 gap-2">
        {/* Logo */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <TerminalIcon size={18} className="text-blue-400" />
          <span className="font-bold text-white text-sm tracking-tight hidden sm:block">CloudShell by IU2FRL</span>
        </div>

        {/* Tab strip */}
        <div className="flex items-center gap-1 overflow-x-auto flex-1 min-w-0 scrollbar-none">
          {tabs.map((tab) => (
            <div
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs cursor-pointer select-none
                          whitespace-nowrap transition-colors flex-shrink-0
                ${activeTab === tab.key
                  ? "bg-blue-600/30 text-blue-300 border border-blue-600/50"
                  : "text-slate-400 hover:bg-slate-800 border border-transparent"
                }`}
            >
              <span className="max-w-[120px] truncate">{tab.device.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleCloseTab(tab.key); }}
                className="text-slate-500 hover:text-slate-200 leading-none ml-0.5"
                title="Close tab"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        {/* Right: session badge + change password + logout */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <SessionBadge />
          <button
            onClick={() => setShowChangePw(true)}
            className="icon-btn text-slate-400 hover:text-blue-400"
            title="Change password"
          >
            <KeyRound size={16} />
          </button>
          <button
            onClick={handleLogout}
            className="icon-btn text-slate-400 hover:text-red-400"
            title="Sign out"
          >
            <LogOut size={16} />
          </button>
        </div>
      </header>

      {/* ── Body ───────────────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        <DeviceList
          devices={devices}
          activeDeviceId={activeDevice?.id ?? null}
          loading={loading}
          onConnect={handleConnect}
          onAdd={() => { setEditDevice(undefined); setShowForm(true); }}
          onEdit={(d) => { setEditDevice(d); setShowForm(true); }}
          onDelete={(id) => {
            setDevices((prev) => prev.filter((d) => d.id !== id));
            // Close any open tab for this device
            setTabs((prev) => {
              const next = prev.filter((t) => t.device.id !== id);
              if (!next.find((t) => t.key === activeTab))
                setActiveTab(next.length > 0 ? next[next.length - 1].key : null);
              return next;
            });
          }}
          onRefresh={fetchDevices}
        />

        {/* Terminal area */}
        <main className="flex-1 overflow-hidden p-3 min-w-0">
          {tabs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center gap-3">
              <TerminalIcon size={44} className="text-slate-700" />
              <p className="text-slate-500 text-sm max-w-xs">
                Connect to a device from the sidebar to open an SSH terminal.
              </p>
            </div>
          ) : (
            tabs.map((tab) => (
              <div
                key={tab.key}
                className="h-full"
                style={{ display: tab.key === activeTab ? "block" : "none" }}
              >
                <Terminal device={tab.device} />
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
            toast.success(editDevice ? "Device updated" : "Device added");
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
