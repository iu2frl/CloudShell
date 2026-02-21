import { useCallback, useEffect, useRef, useState } from "react";
import {
  Device,
  SftpEntry,
  closeSftpSession,
  openSftpSession,
  sftpDelete,
  sftpDownload,
  sftpList,
  sftpMkdir,
  sftpRename,
  sftpUpload,
} from "../api/client";
import {
  ArrowLeft,
  Download,
  File,
  Folder,
  FolderPlus,
  Loader,
  PencilLine,
  RefreshCw,
  Trash2,
  Upload,
  WifiOff,
  X,
} from "lucide-react";
import { useToast } from "./Toast";

interface FileManagerProps {
  device: Device;
}

type ModalState =
  | { type: "rename"; entry: SftpEntry }
  | { type: "mkdir"; currentPath: string }
  | { type: "delete"; entry: SftpEntry }
  | null;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatDate(ts: number): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString();
}

/** Build breadcrumb segments from an absolute path. */
function breadcrumbs(path: string): Array<{ label: string; path: string }> {
  const parts = path.split("/").filter(Boolean);
  const crumbs = [{ label: "/", path: "/" }];
  let accumulated = "";
  for (const part of parts) {
    accumulated += "/" + part;
    crumbs.push({ label: part, path: accumulated });
  }
  return crumbs;
}

export function FileManager({ device }: FileManagerProps) {
  const [sessionId, setSessionId]     = useState<string | null>(null);
  const [connecting, setConnecting]   = useState(true);
  const [connError, setConnError]     = useState<string | null>(null);
  const [path, setPath]               = useState("/");
  const [entries, setEntries]         = useState<SftpEntry[]>([]);
  const [loadingDir, setLoadingDir]   = useState(false);
  const [modal, setModal]             = useState<ModalState>(null);
  const [uploadPct, setUploadPct]     = useState<number | null>(null);
  const fileInputRef                  = useRef<HTMLInputElement>(null);
  const sessionRef                    = useRef<string | null>(null);
  const toast                         = useToast();

  // ── Session lifecycle ────────────────────────────────────────────────────

  const connect = useCallback(async () => {
    setConnecting(true);
    setConnError(null);
    try {
      const sid = await openSftpSession(device.id);
      setSessionId(sid);
      sessionRef.current = sid;
    } catch (err) {
      setConnError(String(err));
    } finally {
      setConnecting(false);
    }
  }, [device.id]);

  useEffect(() => {
    connect();
    return () => {
      if (sessionRef.current) {
        closeSftpSession(sessionRef.current).catch(() => undefined);
        sessionRef.current = null;
      }
    };
  }, [connect]);

  // ── Directory listing ────────────────────────────────────────────────────

  const loadDir = useCallback(
    async (targetPath: string, sid?: string | null) => {
      const id = sid ?? sessionRef.current;
      if (!id) return;
      setLoadingDir(true);
      try {
        const res = await sftpList(id, targetPath);
        setEntries(res.entries);
        setPath(res.path);
      } catch (err) {
        toast.error(`Failed to list directory: ${err}`);
      } finally {
        setLoadingDir(false);
      }
    },
    [toast],
  );

  // Load root once session is open
  useEffect(() => {
    if (sessionId) loadDir("/", sessionId);
  }, [sessionId, loadDir]);

  // ── Navigation ───────────────────────────────────────────────────────────

  const navigateTo = (targetPath: string) => loadDir(targetPath);

  const navigateUp = () => {
    const parts = path.replace(/\/+$/, "").split("/").filter(Boolean);
    parts.pop();
    navigateTo("/" + parts.join("/") || "/");
  };

  // ── Download ─────────────────────────────────────────────────────────────

  const handleDownload = async (entry: SftpEntry) => {
    if (!sessionId) return;
    try {
      await sftpDownload(sessionId, entry.path);
    } catch (err) {
      toast.error(`Download failed: ${err}`);
    }
  };

  // ── Upload ───────────────────────────────────────────────────────────────

  const handleUploadChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length || !sessionId) return;
    e.target.value = "";

    for (const file of files) {
      setUploadPct(0);
      try {
        await sftpUpload(sessionId, path, file, setUploadPct);
        toast.success(`Uploaded ${file.name}`);
      } catch (err) {
        toast.error(`Upload failed: ${err}`);
      } finally {
        setUploadPct(null);
      }
    }
    await loadDir(path);
  };

  // ── Delete ───────────────────────────────────────────────────────────────

  const confirmDelete = (entry: SftpEntry) => setModal({ type: "delete", entry });

  const handleDelete = async (entry: SftpEntry) => {
    if (!sessionId) return;
    setModal(null);
    try {
      await sftpDelete(sessionId, entry.path, entry.is_dir);
      toast.success(`Deleted ${entry.name}`);
      await loadDir(path);
    } catch (err) {
      toast.error(`Delete failed: ${err}`);
    }
  };

  // ── Rename ───────────────────────────────────────────────────────────────

  const [renameValue, setRenameValue] = useState("");

  const openRename = (entry: SftpEntry) => {
    setRenameValue(entry.name);
    setModal({ type: "rename", entry });
  };

  const handleRename = async () => {
    if (modal?.type !== "rename" || !sessionId) return;
    const dir = path.endsWith("/") ? path : path + "/";
    const newPath = dir + renameValue.trim();
    try {
      await sftpRename(sessionId, modal.entry.path, newPath);
      toast.success("Renamed successfully");
      setModal(null);
      await loadDir(path);
    } catch (err) {
      toast.error(`Rename failed: ${err}`);
    }
  };

  // ── Mkdir ────────────────────────────────────────────────────────────────

  const [mkdirValue, setMkdirValue] = useState("");

  const openMkdir = () => {
    setMkdirValue("");
    setModal({ type: "mkdir", currentPath: path });
  };

  const handleMkdir = async () => {
    if (modal?.type !== "mkdir" || !sessionId) return;
    const dir = path.endsWith("/") ? path : path + "/";
    const newPath = dir + mkdirValue.trim();
    try {
      await sftpMkdir(sessionId, newPath);
      toast.success(`Created folder ${mkdirValue}`);
      setModal(null);
      await loadDir(path);
    } catch (err) {
      toast.error(`Create folder failed: ${err}`);
    }
  };

  // ── Render ───────────────────────────────────────────────────────────────

  if (connecting) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-slate-400">
        <Loader size={32} className="animate-spin" />
        <p className="text-sm">Connecting SFTP to {device.hostname}...</p>
      </div>
    );
  }

  if (connError) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4 text-center px-8">
        <WifiOff size={36} className="text-red-500" />
        <p className="text-sm text-red-400">{connError}</p>
        <button onClick={connect} className="btn-primary text-sm px-4 py-2">
          Retry
        </button>
      </div>
    );
  }

  const crumbs = breadcrumbs(path);

  return (
    <div className="h-full flex flex-col bg-slate-950 rounded-lg overflow-hidden border border-slate-800">
      {/* ── Toolbar ── */}
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-900 border-b border-slate-800 flex-shrink-0">
        {/* Navigate up */}
        <button
          onClick={navigateUp}
          disabled={path === "/"}
          className="icon-btn disabled:opacity-30"
          title="Go up"
        >
          <ArrowLeft size={15} />
        </button>

        {/* Refresh */}
        <button
          onClick={() => loadDir(path)}
          className="icon-btn"
          title="Refresh"
          disabled={loadingDir}
        >
          <RefreshCw size={14} className={loadingDir ? "animate-spin" : ""} />
        </button>

        {/* Breadcrumbs */}
        <div className="flex items-center gap-0.5 flex-1 min-w-0 overflow-x-auto scrollbar-none text-xs">
          {crumbs.map((crumb, i) => (
            <span key={crumb.path} className="flex items-center gap-0.5 flex-shrink-0">
              {i > 0 && <span className="text-slate-600">/</span>}
              <button
                onClick={() => navigateTo(crumb.path)}
                className="text-slate-400 hover:text-white transition-colors px-0.5 rounded"
              >
                {crumb.label}
              </button>
            </span>
          ))}
        </div>

        {/* Upload */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleUploadChange}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors px-2 py-1"
          title="Upload file"
          disabled={uploadPct !== null}
        >
          {uploadPct !== null ? (
            <><Loader size={13} className="animate-spin" />{uploadPct}%</>
          ) : (
            <><Upload size={13} /> Upload</>
          )}
        </button>

        {/* New folder */}
        <button
          onClick={openMkdir}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors px-2 py-1"
          title="New folder"
        >
          <FolderPlus size={13} /> New folder
        </button>
      </div>

      {/* ── File table ── */}
      <div className="flex-1 overflow-auto">
        {loadingDir && entries.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <Loader size={24} className="animate-spin text-slate-600" />
          </div>
        ) : entries.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-600 text-sm">
            Empty directory
          </div>
        ) : (
          <table className="w-full text-xs text-slate-300">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-800 text-slate-500 uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-right px-4 py-2 font-medium w-24">Size</th>
                <th className="text-left px-4 py-2 font-medium w-40">Modified</th>
                <th className="text-left px-4 py-2 font-medium w-28">Permissions</th>
                <th className="px-4 py-2 w-24" />
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr
                  key={entry.path}
                  className="border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors group"
                >
                  {/* Name */}
                  <td className="px-4 py-2">
                    {entry.is_dir ? (
                      <button
                        onClick={() => navigateTo(entry.path)}
                        className="flex items-center gap-2 text-blue-400 hover:text-blue-300 font-medium transition-colors"
                      >
                        <Folder size={14} className="flex-shrink-0 text-yellow-400" />
                        {entry.name}
                      </button>
                    ) : (
                      <span className="flex items-center gap-2 text-slate-300">
                        <File size={14} className="flex-shrink-0 text-slate-500" />
                        {entry.name}
                      </span>
                    )}
                  </td>

                  {/* Size */}
                  <td className="px-4 py-2 text-right text-slate-500 tabular-nums">
                    {entry.is_dir ? "-" : formatSize(entry.size)}
                  </td>

                  {/* Modified */}
                  <td className="px-4 py-2 text-slate-500">
                    {formatDate(entry.modified)}
                  </td>

                  {/* Permissions */}
                  <td className="px-4 py-2 text-slate-600 font-mono">
                    {entry.permissions ?? "-"}
                  </td>

                  {/* Actions */}
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity justify-end">
                      {!entry.is_dir && (
                        <button
                          onClick={() => handleDownload(entry)}
                          className="icon-btn text-blue-400 hover:text-blue-300"
                          title="Download"
                        >
                          <Download size={12} />
                        </button>
                      )}
                      <button
                        onClick={() => openRename(entry)}
                        className="icon-btn"
                        title="Rename"
                      >
                        <PencilLine size={12} />
                      </button>
                      <button
                        onClick={() => confirmDelete(entry)}
                        className="icon-btn text-red-400 hover:text-red-300"
                        title="Delete"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Status bar ── */}
      <div className="flex items-center px-4 py-1.5 bg-slate-900 border-t border-slate-800 text-[11px] text-slate-600 flex-shrink-0">
        <span>{entries.length} item{entries.length !== 1 ? "s" : ""}</span>
        {uploadPct !== null && (
          <span className="ml-3 text-blue-400">Uploading... {uploadPct}%</span>
        )}
      </div>

      {/* ── Modals ── */}

      {/* Rename modal */}
      {modal?.type === "rename" && (
        <SimpleModal
          title={`Rename "${modal.entry.name}"`}
          onClose={() => setModal(null)}
          onConfirm={handleRename}
          confirmLabel="Rename"
        >
          <input
            className="input w-full"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleRename()}
            autoFocus
          />
        </SimpleModal>
      )}

      {/* Mkdir modal */}
      {modal?.type === "mkdir" && (
        <SimpleModal
          title="New folder"
          onClose={() => setModal(null)}
          onConfirm={handleMkdir}
          confirmLabel="Create"
        >
          <input
            className="input w-full"
            placeholder="folder-name"
            value={mkdirValue}
            onChange={(e) => setMkdirValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleMkdir()}
            autoFocus
          />
        </SimpleModal>
      )}

      {/* Delete confirm modal */}
      {modal?.type === "delete" && (
        <SimpleModal
          title="Confirm delete"
          onClose={() => setModal(null)}
          onConfirm={() => handleDelete(modal.entry)}
          confirmLabel="Delete"
          destructive
        >
          <p className="text-sm text-slate-300">
            Delete{" "}
            <span className="font-semibold text-white">
              {modal.entry.is_dir ? "folder" : "file"} &quot;{modal.entry.name}&quot;
            </span>
            ?{modal.entry.is_dir && " The directory must be empty."}
          </p>
        </SimpleModal>
      )}
    </div>
  );
}

// ── Reusable inline modal ─────────────────────────────────────────────────────

interface ModalProps {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  onConfirm: () => void;
  confirmLabel?: string;
  destructive?: boolean;
}

function SimpleModal({
  title,
  children,
  onClose,
  onConfirm,
  confirmLabel = "OK",
  destructive = false,
}: ModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-sm shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-700">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3">
          {children}
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} className="btn-ghost text-sm">
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className={`text-sm px-4 py-1.5 rounded-md font-medium transition-colors ${
                destructive
                  ? "bg-red-700 hover:bg-red-600 text-white"
                  : "btn-primary"
              }`}
            >
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
