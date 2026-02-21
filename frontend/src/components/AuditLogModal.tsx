import { useCallback, useEffect, useRef, useState } from "react";
import { X, ClipboardList, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { listAuditLogs, AuditLogEntry, AuditLogPage } from "../api/client";

const PAGE_SIZE = 50;
/** Poll for new entries every N seconds while the modal is open. */
const POLL_INTERVAL_MS = 10_000;

const ACTION_LABELS: Record<string, string> = {
  LOGIN: "Logged in",
  LOGOUT: "Logged out",
  PASSWORD_CHANGED: "Changed password",
  SESSION_STARTED: "Session started",
  SESSION_ENDED: "Session ended",
};

const ACTION_COLORS: Record<string, string> = {
  LOGIN: "text-green-400",
  LOGOUT: "text-yellow-400",
  PASSWORD_CHANGED: "text-orange-400",
  SESSION_STARTED: "text-blue-400",
  SESSION_ENDED: "text-slate-400",
};

function formatUtc(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
  } catch {
    return iso;
  }
}

interface Props {
  onClose: () => void;
}

export function AuditLogModal({ onClose }: Props) {
  const [page, setPage]             = useState(1);
  const [data, setData]             = useState<AuditLogPage | null>(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const pageRef = useRef(page);
  pageRef.current = page;

  const load = useCallback(async (p: number, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const result = await listAuditLogs(p, PAGE_SIZE);
      setData(result);
      setPage(p);
      setLastRefresh(new Date());
    } catch (err) {
      setError(String(err));
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => { load(1); }, [load]);

  // Poll silently every POLL_INTERVAL_MS, staying on the current page
  useEffect(() => {
    const timer = setInterval(() => load(pageRef.current, true), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Reload when the browser tab regains visibility (e.g. user switches back)
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") load(pageRef.current, true); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 flex-shrink-0">
          <div className="flex items-center gap-2 text-white font-semibold">
            <ClipboardList size={16} className="text-blue-400" />
            Audit Log
            {data && (
              <span className="text-slate-400 font-normal text-xs ml-1">
                ({data.total} {data.total === 1 ? "entry" : "entries"})
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="text-slate-500 text-xs hidden sm:block">
                Updated {lastRefresh.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => load(page, false)}
              disabled={loading}
              className="text-slate-400 hover:text-blue-400 transition-colors disabled:opacity-40"
              title="Refresh"
            >
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            </button>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white transition-colors"
              title="Close"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-400 text-sm">
              Loading...
            </div>
          )}

          {error && !loading && (
            <div className="flex items-center justify-center py-16 text-red-400 text-sm">
              {error}
            </div>
          )}

          {!loading && !error && data && data.entries.length === 0 && (
            <div className="flex items-center justify-center py-16 text-slate-500 text-sm">
              No audit log entries yet.
            </div>
          )}

          {!loading && !error && data && data.entries.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700 sticky top-0 bg-slate-900">
                  <th className="text-left px-4 py-2 font-medium whitespace-nowrap">Timestamp (UTC)</th>
                  <th className="text-left px-4 py-2 font-medium">User</th>
                  <th className="text-left px-4 py-2 font-medium">Action</th>
                  <th className="text-left px-4 py-2 font-medium">Source IP</th>
                  <th className="text-left px-4 py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry: AuditLogEntry) => (
                  <tr
                    key={entry.id}
                    className="border-b border-slate-800 hover:bg-slate-800/40 transition-colors"
                  >
                    <td className="px-4 py-2 font-mono text-slate-300 whitespace-nowrap">
                      {formatUtc(entry.timestamp)}
                    </td>
                    <td className="px-4 py-2 text-slate-200 whitespace-nowrap">
                      {entry.username}
                    </td>
                    <td className={`px-4 py-2 font-medium whitespace-nowrap ${ACTION_COLORS[entry.action] ?? "text-slate-300"}`}>
                      {ACTION_LABELS[entry.action] ?? entry.action}
                    </td>
                    <td className="px-4 py-2 font-mono text-slate-400 whitespace-nowrap">
                      {entry.source_ip ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-slate-400">
                      {entry.detail ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination footer */}
        {!loading && !error && data && totalPages > 1 && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-slate-700 flex-shrink-0">
            <button
              onClick={() => load(page - 1)}
              disabled={page <= 1}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft size={14} />
              Previous
            </button>
            <span className="text-xs text-slate-400">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => load(page + 1)}
              disabled={page >= totalPages}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              Next
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
