import { useCallback, useEffect, useRef, useState } from "react";
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

  // panel pool: tabKey → the always-mounted wrapper div in the hidden pool
  const panelRefsMap = useRef<Map<number, HTMLDivElement>>(new Map());
  // cell mount-points: cellIndex → the empty slot div inside each GridCell
  const cellRefsMap  = useRef<Map<number, HTMLDivElement | null>>(new Map());
  // ref to the hidden pool container so we can reparent panels back to it
  const poolRef = useRef<HTMLDivElement>(null);
  const [, forceRender] = useState(0);
  const onContentRef = useCallback((cellIndex: number, el: HTMLDivElement | null) => {
    cellRefsMap.current.set(cellIndex, el);
    forceRender((n) => n + 1);
  }, []);

  // DOM-move effect: whenever assignments or cell refs change, physically move
  // each panel div into its assigned cell's mount-point (or back to the hidden
  // pool). No React reconciliation happens so no component re-mounts occur.
  useEffect(() => {
    const pool = poolRef.current;
    // First, hide all panels and return any that are outside the pool.
    // Guard with document.contains() — a panel whose tab was just closed may
    // already be detached from the document; attempting appendChild on a
    // detached node that React is mid-removing throws "removeChild" errors.
    for (const [key, panelEl] of panelRefsMap.current) {
      if (!document.contains(panelEl)) {
        // Node was removed by React — drop the stale ref and skip
        panelRefsMap.current.delete(key);
        continue;
      }
      panelEl.style.display = "none";
      if (pool && panelEl.parentElement !== pool) pool.appendChild(panelEl);
    }
    // Then move each assigned panel into its cell mount-point and show it
    for (const [cellIdx, key] of grid.assignments) {
      if (key === null) continue;
      const panelEl = panelRefsMap.current.get(key);
      const cellEl  = cellRefsMap.current.get(cellIdx);
      if (!panelEl || !cellEl) continue;
      if (!document.contains(panelEl)) {
        panelRefsMap.current.delete(key);
        continue;
      }
      const moved = panelEl.parentElement !== cellEl;
      if (moved) cellEl.appendChild(panelEl);
      panelEl.style.display = "";
      // Notify the Terminal inside that it should re-fit now that the panel
      // is visible.  The Terminal listener wraps the actual fit call in a
      // requestAnimationFrame so the browser resolves the new cell dimensions
      // before xterm measures them.  We dispatch on every show (not just moves)
      // to also cover display:none → visible transitions after tab switches.
      panelEl.dispatchEvent(new CustomEvent("terminal-fit", { bubbles: true }));
    }
  });

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
    // Evict the closed tab from all cells. Pass the remaining tab keys as
    // fallbacks so any vacated cell is immediately filled with another open
    // tab instead of showing the empty "Assign connection" picker.
    const remaining = tabs.filter((t) => t.key !== key).map((t) => t.key);
    grid.evictKeyWithFallback(key, remaining);
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
                // Highlight the cell that holds this tab; if not in any cell, auto-place it
                let found = false;
                for (const [idx, key] of grid.assignments) {
                  if (key === tab.key) { grid.setFocusedCell(idx); found = true; break; }
                }
                if (!found) grid.autoPlace(tab.key);
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
            All Terminal / FileManager instances live permanently in the hidden
            pool — they are NEVER unmounted on tab switch. When a tab is assigned
            to a grid cell, its pool div is physically moved (appendChild) into
            the cell's mount-point div so WebSocket connections and xterm state
            are fully preserved. When unassigned, the pool div returns to the
            hidden pool (display:none). No React reconciliation happens during
            the move, so no component re-mounts.
          */}
          <div className="h-full relative">
            {/* Hidden panel pool — one entry per open tab, always mounted */}
            <div ref={poolRef} className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
              {tabs.map((tab) => (
                <div
                  key={tab.key}
                  ref={(el) => {
                    if (el) {
                      panelRefsMap.current.set(tab.key, el);
                    } else {
                      // React is about to remove this node from the DOM.
                      // If our DOM-move effect moved it into a cell mount-point,
                      // React still thinks it lives in the pool and will call
                      // pool.removeChild(node) — which throws "not a child of
                      // this node" if the node is elsewhere.  Move it back to
                      // the pool first so React finds it where it expects it.
                      const panelEl = panelRefsMap.current.get(tab.key);
                      const pool    = poolRef.current;
                      if (panelEl && pool && panelEl.parentElement !== pool) {
                        pool.appendChild(panelEl);
                      }
                      panelRefsMap.current.delete(tab.key);
                    }
                  }}
                  className="h-full w-full pointer-events-auto"
                  style={{ display: "none" }}
                >
                  {tab.device.connection_type === "sftp"
                    ? <FileManager device={tab.device} />
                    : <Terminal device={tab.device} />
                  }
                </div>
              ))}
            </div>

            {/* Visible grid — cells provide borders, focus rings and mount-points */}
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
              onContentRef={onContentRef}
              emptyState={
                <div className="h-full flex flex-col items-center justify-center text-center gap-3">
                  <TerminalIcon size={44} className="text-slate-700" />
                  <p className="text-slate-500 text-sm max-w-xs">
                    Connect to a device from the sidebar to open an SSH terminal.
                  </p>
                </div>
              }
            />
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
