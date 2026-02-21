import { useEffect, useState } from "react";
import { Device, listDevices, logout } from "../api/client";
import { DeviceList } from "../components/DeviceList";
import { DeviceForm } from "../components/DeviceForm";
import { Terminal } from "../components/Terminal";
import { FileManager } from "../components/FileManager";
import { SessionBadge } from "../components/SessionBadge";
import { ChangePasswordModal } from "../components/ChangePasswordModal";
import { AuditLogModal } from "../components/AuditLogModal";
import { useToast } from "../components/Toast";
import { SplitView, LayoutPicker, useGridLayout } from "../components/splitview";
import { ClipboardList, FolderOpen, KeyRound, LogOut, Terminal as TerminalIcon } from "lucide-react";

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
  const [showAuditLog, setShowAuditLog] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const toast = useToast();

  const grid = useGridLayout<number>({ rows: 1, cols: 1 });

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
    if (existing) {
      // If already in a cell just focus that cell; otherwise auto-place it
      let found = false;
      for (const [idx, key] of grid.assignments) {
        if (key === existing.key) { grid.setFocusedCell(idx); found = true; break; }
      }
      if (!found) grid.autoPlace(existing.key);
      setActiveTab(existing.key);
      return;
    }
    const tab: Tab = { device: d, key: ++tabCounter };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.key);
    grid.autoPlace(tab.key);
  };

  const handleCloseTab = (key: number) => {
    grid.evictKey(key);
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

  // The device shown in the focused cell (used to highlight sidebar entry)
  const focusedKey = grid.assignments.get(grid.focusedCell) ?? null;
  const focusedDevice = tabs.find((t) => t.key === focusedKey)?.device ?? null;

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
              onClick={() => {
                setActiveTab(tab.key);
                // Highlight the cell that holds this tab, if any
                for (const [idx, key] of grid.assignments) {
                  if (key === tab.key) { grid.setFocusedCell(idx); break; }
                }
              }}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs cursor-pointer select-none
                          whitespace-nowrap transition-colors flex-shrink-0
                ${activeTab === tab.key
                  ? "bg-blue-600/30 text-blue-300 border border-blue-600/50"
                  : "text-slate-400 hover:bg-slate-800 border border-transparent"
                }`}
            >
              {tab.device.connection_type === "sftp"
                ? <FolderOpen size={11} className="flex-shrink-0" />
                : <TerminalIcon size={11} className="flex-shrink-0" />
              }
              <span className="max-w-[120px] truncate">{tab.device.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleCloseTab(tab.key); }}
                className="text-slate-500 hover:text-slate-200 leading-none ml-0.5"
                title="Close tab"
              >
                x
              </button>
            </div>
          ))}
        </div>

        {/* Right: layout picker + session badge + audit log + change password + logout */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <div className="border-r border-slate-700 pr-2 mr-1">
            <LayoutPicker
              current={grid.layout}
              onSelect={grid.setLayout}
            />
          </div>
          <SessionBadge />
          <button
            onClick={() => setShowAuditLog(true)}
            className="icon-btn text-slate-400 hover:text-blue-400"
            title="Audit log"
          >
            <ClipboardList size={16} />
          </button>
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
          activeDeviceId={focusedDevice?.id ?? activeDevice?.id ?? null}
          loading={loading}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          onConnect={handleConnect}
          onAdd={() => { setEditDevice(undefined); setShowForm(true); }}
          onEdit={(d) => { setEditDevice(d); setShowForm(true); }}
          onDelete={(id) => {
            setDevices((prev) => prev.filter((d) => d.id !== id));
            // Close any open tab for this device and evict it from all cells
            setTabs((prev) => {
              const removed = prev.find((t) => t.device.id === id);
              if (removed) grid.evictKey(removed.key);
              const next = prev.filter((t) => t.device.id !== id);
              if (!next.find((t) => t.key === activeTab))
                setActiveTab(next.length > 0 ? next[next.length - 1].key : null);
              return next;
            });
          }}
          onRefresh={fetchDevices}
        />

        {/* ── Split-view main area ─────────────────────────────────────────── */}
        <main className="flex-1 overflow-hidden p-3 min-w-0">
          {/*
            All Terminal / FileManager instances are rendered (hidden) so their
            WebSocket connections stay alive even when not in the focused cell.
            SplitView renders each cell; the children callback receives a tab
            and renders the correct component.
          */}
          <div className="h-full relative">
            {/* Hidden panel pool — keeps all connections alive */}
            <div className="absolute inset-0 pointer-events-none" aria-hidden>
              {tabs.map((tab) => {
                // Only render if this tab is NOT currently visible in any cell
                // (if it IS visible, SplitView renders it directly)
                const isInGrid = Array.from(grid.assignments.values()).includes(tab.key);
                if (isInGrid) return null;
                return (
                  <div key={tab.key} style={{ display: "none" }}>
                    {tab.device.connection_type === "sftp"
                      ? <FileManager device={tab.device} />
                      : <Terminal device={tab.device} />
                    }
                  </div>
                );
              })}
            </div>

            {/* Visible grid */}
            <SplitView<number, Tab>
              layout={grid.layout}
              assignments={grid.assignments}
              items={tabs}
              getKey={(tab) => tab.key}
              getLabel={(tab) => tab.device.name}
              focusedCell={grid.focusedCell}
              onAssign={(cellIndex, key) => {
                grid.assignCell(cellIndex, key);
                if (key !== null) {
                  setActiveTab(key);
                  grid.setFocusedCell(cellIndex);
                }
              }}
              onFocus={(cellIndex) => {
                grid.setFocusedCell(cellIndex);
                const key = grid.assignments.get(cellIndex) ?? null;
                if (key !== null) setActiveTab(key);
              }}
              emptyState={
                <div className="h-full flex flex-col items-center justify-center text-center gap-3">
                  <TerminalIcon size={44} className="text-slate-700" />
                  <p className="text-slate-500 text-sm max-w-xs">
                    Connect to a device from the sidebar to open an SSH terminal.
                  </p>
                </div>
              }
            >
              {(tab) =>
                tab.device.connection_type === "sftp"
                  ? <FileManager device={tab.device} />
                  : <Terminal device={tab.device} />
              }
            </SplitView>
          </div>
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

      {/* Audit log modal */}
      {showAuditLog && (
        <AuditLogModal onClose={() => setShowAuditLog(false)} />
      )}
    </div>
  );
}
