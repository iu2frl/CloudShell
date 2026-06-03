import { useCallback, useEffect, useRef, useState } from "react";
import {
  Device,
  FtpsCertificateChallengeDetail,
  FtpsCertificateChallengeError,
  SftpEntry,
  closeFtpSession,
  openFtpSession,
  ftpDelete,
  ftpDownload,
  ftpList,
  ftpMkdir,
  ftpRename,
  ftpUpload,
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
import { FingerprintTrustModal } from "./FingerprintTrustModal";

interface FtpFileManagerProps {
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

export function FtpFileManager({ device }: FtpFileManagerProps) {
  const [sessionId, setSessionId]     = useState<string | null>(null);
  const [connecting, setConnecting]   = useState(true);
  const [connError, setConnError]     = useState<string | null>(null);
  const [path, setPath]               = useState("/");
  const [entries, setEntries]         = useState<SftpEntry[]>([]);
  const [loadingDir, setLoadingDir]   = useState(false);
  const [modal, setModal]             = useState<ModalState>(null);
  const [uploadPct, setUploadPct]     = useState<number | null>(null);
  const [deletingInfo, setDeletingInfo] = useState<{ name: string; items: number } | null>(null);
  const fileInputRef                  = useRef<HTMLInputElement>(null);
  const sessionRef                    = useRef<string | null>(null);
  const challengeResolverRef          = useRef<((accepted: boolean) => void) | null>(null);
  const toast                         = useToast();
  const toastRef                      = useRef(toast);
  useEffect(() => { toastRef.current = toast; });

  const protocol = device.connection_type === "ftps" ? "FTPS" : "FTP";

  const [certificateChallenge, setCertificateChallenge] = useState<FtpsCertificateChallengeDetail | null>(null);

  const requestCertificateTrust = useCallback((err: FtpsCertificateChallengeError): Promise<boolean> => {
    setCertificateChallenge(err.detail);
    return new Promise((resolve) => {
      challengeResolverRef.current = resolve;
    });
  }, []);

  const resolveCertificateTrust = useCallback((accepted: boolean) => {
    setCertificateChallenge(null);
    const resolver = challengeResolverRef.current;
    challengeResolverRef.current = null;
    resolver?.(accepted);
  }, []);

  // -- Session lifecycle ----------------------------------------------------

  const connect = useCallback(async () => {
    setConnecting(true);
    setConnError(null);
    try {
      let sid: string;
      if (device.connection_type === "ftps") {
        try {
          sid = await openFtpSession(device.id);
        } catch (err) {
          if (!(err instanceof FtpsCertificateChallengeError)) {
            throw err;
          }
          const accepted = await requestCertificateTrust(err);
          if (!accepted) {
            throw new Error("Connection cancelled: FTPS certificate not trusted");
          }
          sid = await openFtpSession(device.id, { trustCert: true });
          toastRef.current.success("FTPS certificate trusted and saved for this device");
        }
      } else {
        sid = await openFtpSession(device.id);
      }

      setSessionId(sid);
      sessionRef.current = sid;
    } catch (err) {
      setConnError(String(err));
    } finally {
      setConnecting(false);
    }
  }, [device.connection_type, device.id, requestCertificateTrust]);

  useEffect(() => {
    connect();
    return () => {
      if (challengeResolverRef.current) {
        challengeResolverRef.current(false);
        challengeResolverRef.current = null;
      }
      if (sessionRef.current) {
        closeFtpSession(sessionRef.current).catch(() => undefined);
        sessionRef.current = null;
      }
    };
  }, [connect]);

  // -- Directory listing ----------------------------------------------------

  const loadDir = useCallback(
    async (targetPath: string, sid?: string | null) => {
      const id = sid ?? sessionRef.current;
      if (!id) return;
      setLoadingDir(true);
      try {
        const res = await ftpList(id, targetPath);
        setEntries(res.entries);
        setPath(res.path);
      } catch (err) {
        toastRef.current.error(`Failed to list directory: ${err}`);
      } finally {
        setLoadingDir(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    if (sessionId) loadDir("/", sessionId);
  }, [sessionId, loadDir]);

  // -- Navigation -----------------------------------------------------------

  const navigateTo = (targetPath: string) => loadDir(targetPath);

  const navigateUp = () => {
    const parts = path.replace(/\/+$/, "").split("/").filter(Boolean);
    parts.pop();
    navigateTo("/" + parts.join("/") || "/");
  };

  // -- Download -------------------------------------------------------------

  const handleDownload = async (entry: SftpEntry) => {
    if (!sessionId) return;
    try {
      await ftpDownload(sessionId, entry.path);
    } catch (err) {
      toastRef.current.error(`Download failed: ${err}`);
    }
  };

  // -- Upload ---------------------------------------------------------------

  const handleUploadChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length || !sessionId) return;
    e.target.value = "";

    for (const file of files) {
      setUploadPct(0);
      try {
        await ftpUpload(sessionId, path, file, setUploadPct);
        toastRef.current.success(`Uploaded ${file.name}`);
      } catch (err) {
        toastRef.current.error(`Upload failed: ${err}`);
      } finally {
        setUploadPct(null);
      }
    }
    await loadDir(path);
  };

  // -- Delete ---------------------------------------------------------------

  const confirmDelete = (entry: SftpEntry) => setModal({ type: "delete", entry });

  const handleDelete = async (entry: SftpEntry) => {
    if (!sessionId) return;
    setModal(null);
    if (entry.is_dir) {
      setDeletingInfo({ name: entry.name, items: 0 });
    }
    try {
      await ftpDelete(sessionId, entry.path, entry.is_dir, (items) => {
        setDeletingInfo((prev) => prev ? { ...prev, items } : null);
      });
      toastRef.current.success(`Deleted ${entry.name}`);
      await loadDir(path);
    } catch (err) {
      toastRef.current.error(`Delete failed: ${err}`);
    } finally {
      setDeletingInfo(null);
    }
  };

  // -- Rename ---------------------------------------------------------------

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
      await ftpRename(sessionId, modal.entry.path, newPath);
      toastRef.current.success("Renamed successfully");
      setModal(null);
      await loadDir(path);
    } catch (err) {
      toastRef.current.error(`Rename failed: ${err}`);
    }
  };

  // -- Mkdir ----------------------------------------------------------------

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
      await ftpMkdir(sessionId, newPath);
      toastRef.current.success(`Created folder ${mkdirValue}`);
      setModal(null);
      await loadDir(path);
    } catch (err) {
      toastRef.current.error(`Create folder failed: ${err}`);
    }
  };

  // -- Render ---------------------------------------------------------------

  const certificateTrustModal = certificateChallenge && (
    <FingerprintTrustModal
      title={certificateChallenge.code === "FTPS_CERT_UNTRUSTED" ? "Trust FTPS Certificate" : "FTPS Certificate Changed"}
      host={device.hostname}
      currentLabel="Presented certificate thumbprint (SHA-256)"
      currentFingerprint={certificateChallenge.thumbprint}
      previousLabel={certificateChallenge.code === "FTPS_CERT_CHANGED" ? "Previously trusted thumbprint" : undefined}
      previousFingerprint={certificateChallenge.code === "FTPS_CERT_CHANGED" ? certificateChallenge.previous_thumbprint : undefined}
      acceptLabel={certificateChallenge.code === "FTPS_CERT_UNTRUSTED" ? "Trust certificate" : "Trust new certificate"}
      onAccept={() => resolveCertificateTrust(true)}
      onCancel={() => resolveCertificateTrust(false)}
    />
  );

  if (connecting) {
    return (
      <>
        <div className="h-full flex flex-col items-center justify-center gap-3 text-slate-400">
          <Loader size={32} className="animate-spin" />
          <p className="text-sm">Connecting {protocol} to {device.hostname}...</p>
        </div>
        {certificateTrustModal}
      </>
    );
  }

  if (connError) {
    return (
      <>
        <div className="h-full flex flex-col items-center justify-center gap-4 text-center px-8">
          <WifiOff size={36} className="text-red-500" />
          <p className="text-sm text-red-400">{connError}</p>
          <button onClick={connect} className="btn-primary text-sm px-4 py-2">
            Retry
          </button>
        </div>
        {certificateTrustModal}
      </>
    );
  }

  const crumbs = breadcrumbs(path);

  return (
    <div className="h-full flex flex-col bg-slate-950 rounded-lg overflow-hidden border border-slate-800">
      {/* -- Toolbar -- */}
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

        {/* Protocol badge */}
        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded border border-orange-700/60 bg-orange-900/30 text-orange-300 flex-shrink-0">
          {protocol}
        </span>

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

      {/* -- Upload progress bar -- */}
      {uploadPct !== null && (
        <div className="flex items-center gap-3 px-3 py-2 bg-slate-900/50 border-b border-slate-800 flex-shrink-0">
          <div className="flex-1 flex items-center gap-2">
            <Loader size={14} className="animate-spin text-blue-400 flex-shrink-0" />
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-400">Uploading...</span>
                <span className="text-xs font-semibold text-blue-400">{uploadPct}%</span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-blue-500 to-blue-400 h-full transition-all ease-out"
                  style={{ width: `${uploadPct}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* -- Delete progress bar -- */}
      {deletingInfo && (
        <div className="flex items-center gap-3 px-3 py-2 bg-slate-900/50 border-b border-slate-800 flex-shrink-0">
          <div className="flex-1 flex items-center gap-2">
            <Loader size={14} className="animate-spin text-red-400 flex-shrink-0" />
            <span className="text-xs text-slate-400">
              Deleting &quot;{deletingInfo.name}&quot;...{" "}
              <span className="font-semibold text-red-400">
                {deletingInfo.items} item{deletingInfo.items !== 1 ? "s" : ""} removed
              </span>
            </span>
          </div>
        </div>
      )}

      {/* -- File table -- */}
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
                        disabled={deletingInfo !== null}
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

      {/* -- Status bar -- */}
      <div className="flex items-center px-4 py-1.5 bg-slate-900 border-t border-slate-800 text-[11px] text-slate-600 flex-shrink-0">
        <span>{entries.length} item{entries.length !== 1 ? "s" : ""}</span>
        {uploadPct !== null && (
          <span className="ml-3 text-blue-400">Uploading... {uploadPct}%</span>
        )}
        {deletingInfo && (
          <span className="ml-3 text-red-400">
            Deleting... {deletingInfo.items} item{deletingInfo.items !== 1 ? "s" : ""} removed
          </span>
        )}
      </div>

      {/* -- Modals -- */}

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
            ?{modal.entry.is_dir && " This will delete all contents inside."}
          </p>
        </SimpleModal>
      )}

      {certificateTrustModal}
    </div>
  );
}

// -- Reusable inline modal -----------------------------------------------------

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
