import { useEffect, useRef, useState, useCallback } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { Device, SshHostChallengeDetail, SshHostChallengeError, createTerminalWsTicket, openSession, terminalWsUrl } from "../api/client";
import { RefreshCw, Wifi, WifiOff, Loader, Copy, Plus, Settings2, Send, Trash2 } from "lucide-react";
import { useToast } from "./Toast";
import { FingerprintTrustModal } from "./FingerprintTrustModal";
import {
  MAX_QUICK_COMMANDS,
  QuickCommand,
  buildQuickCommandsStorageKey,
  normalizeQuickCommands,
  parseQuickCommands,
} from "./terminalQuickCommands";

type ConnState = "connecting" | "connected" | "disconnected" | "error" | "failed";

const MAX_RETRIES = 3;

interface TerminalProps {
  device: Device;
  terminalKey: number;
}

export function Terminal({ device, terminalKey }: TerminalProps) {
  const containerRef   = useRef<HTMLDivElement>(null);
  const xtermRef       = useRef<XTerm | null>(null);
  const fitRef         = useRef<FitAddon | null>(null);
  const wsRef          = useRef<WebSocket | null>(null);
  const retriesRef     = useRef(0);
  const connectingRef  = useRef(false);
  const onDataDisposer = useRef<ReturnType<XTerm["onData"]> | null>(null);
  const challengeResolverRef = useRef<((accepted: boolean) => void) | null>(null);
  const [connState, setConnState] = useState<ConnState>("connecting");
  const [sshChallenge, setSshChallenge] = useState<SshHostChallengeDetail | null>(null);
  const [quickCommands, setQuickCommands] = useState<QuickCommand[]>([]);
  const [showQuickEditor, setShowQuickEditor] = useState(false);
  const [quickDrafts, setQuickDrafts] = useState<QuickCommand[]>([]);
  const toast = useToast();
  // Stable ref so connect() doesn't need toast in its dep array (prevents reconnect loop)
  const toastRef = useRef(toast);
  useEffect(() => { toastRef.current = toast; });

  const requestSshHostTrust = useCallback((err: SshHostChallengeError): Promise<boolean> => {
    setSshChallenge(err.detail);
    return new Promise((resolve) => {
      challengeResolverRef.current = resolve;
    });
  }, []);

  const resolveSshHostTrust = useCallback((accepted: boolean) => {
    setSshChallenge(null);
    const resolver = challengeResolverRef.current;
    challengeResolverRef.current = null;
    resolver?.(accepted);
  }, []);

  const nextQuickCommandId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  };

  useEffect(() => {
    const storageKey = buildQuickCommandsStorageKey(terminalKey);
    let loaded: QuickCommand[] = [];
    try {
      loaded = parseQuickCommands(localStorage.getItem(storageKey));
    } catch {
      loaded = [];
    }
    setQuickCommands(loaded);
    setQuickDrafts(loaded);
    setShowQuickEditor(false);
  }, [terminalKey]);

  const persistQuickCommands = useCallback((commands: QuickCommand[]) => {
    const storageKey = buildQuickCommandsStorageKey(terminalKey);
    try {
      localStorage.setItem(storageKey, JSON.stringify(commands));
    } catch {
      toastRef.current.error("Could not save quick commands");
    }
    setQuickCommands(commands);
  }, [terminalKey]);

  const addQuickDraft = () => {
    setQuickDrafts((prev) => {
      if (prev.length >= MAX_QUICK_COMMANDS) return prev;
      return [...prev, { id: nextQuickCommandId(), label: "", command: "" }];
    });
  };

  const updateQuickDraft = (id: string, field: "label" | "command", value: string) => {
    setQuickDrafts((prev) => prev.map((item) => (
      item.id === id ? { ...item, [field]: value } : item
    )));
  };

  const removeQuickDraft = (id: string) => {
    setQuickDrafts((prev) => prev.filter((item) => item.id !== id));
  };

  const saveQuickDrafts = () => {
    const normalized = normalizeQuickCommands(quickDrafts);
    persistQuickCommands(normalized);
    setQuickDrafts(normalized);
    setShowQuickEditor(false);
  };

  const runQuickCommand = (command: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toastRef.current.error("Terminal is not connected");
      return;
    }
    const payload = command.endsWith("\n") ? command : `${command}\n`;
    ws.send(new TextEncoder().encode(payload));
  };

  // -- Build the xterm instance once ------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;

    const term = new XTerm({
      theme: {
        background:          "#0f1117",
        foreground:          "#e2e8f0",
        cursor:              "#3b82f6",
        cursorAccent:        "#0f1117",
        selectionBackground: "#3b82f640",
        black:        "#1a1d27", brightBlack:   "#4a5568",
        red:          "#fc8181", brightRed:     "#feb2b2",
        green:        "#68d391", brightGreen:   "#9ae6b4",
        yellow:       "#f6e05e", brightYellow:  "#faf089",
        blue:         "#63b3ed", brightBlue:    "#90cdf4",
        magenta:      "#d6bcfa", brightMagenta: "#e9d8fd",
        cyan:         "#76e4f7", brightCyan:    "#b2f5ea",
        white:        "#e2e8f0", brightWhite:   "#f7fafc",
      },
      fontFamily:  "'JetBrains Mono', 'Fira Code', monospace",
      fontSize:    14,
      lineHeight:  1.4,
      cursorBlink: true,
      cursorStyle: "block",
      scrollback:  5000,
      allowProposedApi: true,
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(containerRef.current);
    fit.fit();

    xtermRef.current = term;
    fitRef.current   = fit;

    return () => { term.dispose(); };
  }, []);

  // -- Connect / reconnect -----------------------------------------------------
  const connect = useCallback(async () => {
    const term = xtermRef.current;
    const fit  = fitRef.current;
    if (!term || !fit) return;

    // Prevent concurrent connect() calls (e.g. from effect double-fire)
    if (connectingRef.current) return;
    connectingRef.current = true;

    if (retriesRef.current >= MAX_RETRIES) {
      term.writeln(`\r\n\x1b[31m[max retries (${MAX_RETRIES}) reached — click reconnect to try again]\x1b[0m`);
      setConnState("failed");
      connectingRef.current = false;
      return;
    }

    // Close the previous socket first, then null the ref so its onclose
    // handler cannot fire against the new connection we are about to create.
    const prev = wsRef.current;
    wsRef.current = null;
    prev?.close();

    setConnState("connecting");
    term.writeln("\x1b[36mCloudShell\x1b[0m — connecting…");

    let sessionId: string;
    try {
      try {
        sessionId = await openSession(device.id);
      } catch (err) {
        if (!(err instanceof SshHostChallengeError)) {
          throw err;
        }
        const accepted = await requestSshHostTrust(err);
        if (!accepted) {
          throw new Error("Connection cancelled: SSH host key not trusted");
        }
        sessionId = await openSession(device.id, { trustHost: true });
        toastRef.current.success("SSH host key trusted and saved for this device");
      }
    } catch (err) {
      retriesRef.current += 1;
      const msg = String(err);
      term.writeln(`\r\n\x1b[31m[connection failed: ${msg}]\x1b[0m`);
      if (retriesRef.current >= MAX_RETRIES) {
        term.writeln(`\r\n\x1b[31m[max retries (${MAX_RETRIES}) reached — click reconnect to try again]\x1b[0m`);
        setConnState("failed");
      } else {
        setConnState("error");
      }
      toastRef.current.error(`${device.name}: ${msg}`);
      connectingRef.current = false;
      return;
    }

    let wsTicket: string;
    try {
      const ticketResponse = await createTerminalWsTicket(sessionId);
      wsTicket = ticketResponse.ticket;
    } catch (err) {
      retriesRef.current += 1;
      const msg = String(err);
      term.writeln(`\r\n\x1b[31m[websocket ticket failed: ${msg}]\x1b[0m`);
      if (retriesRef.current >= MAX_RETRIES) {
        term.writeln(`\r\n\x1b[31m[max retries (${MAX_RETRIES}) reached — click reconnect to try again]\x1b[0m`);
        setConnState("failed");
      } else {
        setConnState("error");
      }
      toastRef.current.error(`${device.name}: ${msg}`);
      connectingRef.current = false;
      return;
    }

    const url = terminalWsUrl(sessionId, wsTicket);
    const ws  = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    connectingRef.current = false;

    ws.onopen = () => {
      retriesRef.current = 0;
      setConnState("connected");
      term.clear();
      const { rows, cols } = term;
      ws.send(new TextEncoder().encode(JSON.stringify({ type: "resize", cols, rows })));
    };

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer
        ? new Uint8Array(e.data)
        : new TextEncoder().encode(e.data as string);
      term.write(data);
    };

    ws.onclose = (e) => {
      // Ignore close events from a socket that has already been superseded
      if (wsRef.current !== ws) return;
      const clean = e.wasClean && e.code === 1000;
      setConnState(clean ? "disconnected" : "error");
      term.writeln(`\r\n\x1b[33m[disconnected${clean ? "" : ` code=${e.code}`}]\x1b[0m`);
      if (!clean) toastRef.current.info(`${device.name}: connection closed`);
    };

    ws.onerror = () => {
      if (wsRef.current !== ws) return;
      setConnState("error");
    };

    // Dispose any previous onData listener before registering a new one to
    // prevent multiple handlers accumulating across reconnects.
    onDataDisposer.current?.dispose();
    onDataDisposer.current = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });
  // toast intentionally excluded — accessed via toastRef to keep connect() stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device.id, device.name, requestSshHostTrust]);

  useEffect(() => { connect(); }, [connect]);

  // -- Persistent ResizeObserver — handles all size-change scenarios -----------
  // Kept separate from connect() so it survives reconnects and fires even
  // when the panel is shown for the first time after being hidden in the pool.
  //
  // The Dashboard DOM-move effect dispatches "terminal-fit" on the panel wrapper
  // after appending it into a cell.  We schedule the actual fit inside a
  // requestAnimationFrame so the browser has completed layout before we measure,
  // which covers both the display:none→visible transition and split-view
  // dimension changes.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let rafId = 0;
    const doFit = () => {
      try {
        fitRef.current?.fit();
      } catch { /* ignore if xterm not yet attached */ }
      // If connected, also sync the new size to the server
      const ws   = wsRef.current;
      const term = xtermRef.current;
      if (ws && ws.readyState === WebSocket.OPEN && term) {
        const { rows, cols } = term;
        ws.send(new TextEncoder().encode(JSON.stringify({ type: "resize", cols, rows })));
      }
    };

    // ResizeObserver: fires on every genuine size change (window resize,
    // split-view column drag, panel re-show after tab switch, …)
    let resizing = false;
    const ro = new ResizeObserver(() => {
      if (resizing) return;
      resizing = true;
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => { doFit(); resizing = false; });
    });
    ro.observe(container);

    // "terminal-fit" event: fired by the DOM-move effect right after it moves
    // the panel from display:none into a live cell mount-point.  We also wrap
    // it in rAF so the new cell dimensions have been resolved by the browser.
    const onFitEvent = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(doFit);
    };
    container.addEventListener("terminal-fit", onFitEvent);

    return () => {
      ro.disconnect();
      container.removeEventListener("terminal-fit", onFitEvent);
      cancelAnimationFrame(rafId);
    };
  }, []);

  // -- Explicit cleanup on unmount (tab close) ----------------------------------
  // Without this, closing the tab only removes the DOM node; the WebSocket
  // lingers in a half-open state and the server never receives a clean close
  // frame, so SESSION_ENDED is not written until the connection times out.
  useEffect(() => {
    return () => {
      if (challengeResolverRef.current) {
        challengeResolverRef.current(false);
        challengeResolverRef.current = null;
      }
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        wsRef.current = null;   // prevent onclose handler from firing
        ws.close(1000, "tab closed");
      }
    };
  }, []);

  // -- Copy session info --------------------------------------------------------
  const copyInfo = () => {
    navigator.clipboard.writeText(`${device.username}@${device.hostname}:${device.port}`);
    toastRef.current.info("Copied to clipboard");
  };

  // -- Status badge ------------------------------------------------------------
  const badge: Record<ConnState, { icon: React.ReactNode; label: string; cls: string }> = {
    connecting:   { icon: <Loader  size={12} className="animate-spin" />, label: "Connecting",   cls: "text-yellow-400 border-yellow-700" },
    connected:    { icon: <Wifi    size={12} />,                          label: "Connected",    cls: "text-green-400  border-green-700"  },
    disconnected: { icon: <WifiOff size={12} />,                          label: "Disconnected", cls: "text-slate-400  border-slate-600"  },
    error:        { icon: <WifiOff size={12} />,                          label: "Error",        cls: "text-red-400    border-red-700"    },
    failed:       { icon: <WifiOff size={12} />,                          label: "Failed",       cls: "text-red-600    border-red-800"    },
  };
  const b = badge[connState];

  return (
    <div className="flex flex-col h-full gap-0">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border border-slate-700 rounded-t-lg flex-shrink-0 gap-3">
        {/* Device label */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-slate-200 truncate">{device.name}</span>
          <span className="text-xs text-slate-500 truncate hidden sm:block">
            {device.username}@{device.hostname}:{device.port}
          </span>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* SSH protocol badge */}
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded border border-green-700/60 bg-green-900/30 text-green-300 flex-shrink-0">
            SSH
          </span>

          {/* Status badge */}
          <div className={`flex items-center gap-1.5 text-xs border rounded px-2 py-0.5 ${b.cls}`}>
            {b.icon}
            <span className="hidden sm:inline">{b.label}</span>
          </div>

          {/* Copy SSH target */}
          <button onClick={copyInfo} title="Copy SSH target" className="icon-btn">
            <Copy size={12} />
          </button>

          {/* Reconnect */}
          <button
            onClick={() => { retriesRef.current = 0; connectingRef.current = false; connect(); }}
            title="Reconnect"
            className="icon-btn"
            disabled={connState === "connecting" || connState === "connected"}
          >
            <RefreshCw size={13} className={connState === "connecting" ? "animate-spin" : ""} />
          </button>

          {/* Quick commands */}
          <button
            type="button"
            onClick={() => {
              setQuickDrafts(quickCommands);
              setShowQuickEditor((prev) => !prev);
            }}
            title="Configure quick commands"
            className={`icon-btn ${showQuickEditor ? "text-blue-300 bg-slate-700" : ""}`}
          >
            <Settings2 size={13} />
          </button>
        </div>
      </div>

      {(quickCommands.length > 0 || showQuickEditor) && (
        <div className="border-x border-slate-700 bg-slate-900/70 px-2 py-2 space-y-2">
          {quickCommands.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {quickCommands.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded border border-slate-600 bg-slate-800 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-50"
                  onClick={() => runQuickCommand(item.command)}
                  disabled={connState !== "connected"}
                  title={item.command}
                >
                  <Send size={11} />
                  {item.label}
                </button>
              ))}
            </div>
          )}

          {showQuickEditor && (
            <div className="rounded border border-slate-700 bg-slate-900 p-2 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                  Quick Commands ({quickDrafts.length}/{MAX_QUICK_COMMANDS})
                </p>
                <button
                  type="button"
                  className="icon-btn"
                  onClick={addQuickDraft}
                  disabled={quickDrafts.length >= MAX_QUICK_COMMANDS}
                  title="Add quick command"
                >
                  <Plus size={12} />
                </button>
              </div>

              {quickDrafts.length === 0 && (
                <p className="text-xs text-slate-500">Add buttons for common commands like apt update.</p>
              )}

              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {quickDrafts.map((item) => (
                  <div key={item.id} className="grid grid-cols-[1fr_2fr_auto] gap-1.5 items-center">
                    <input
                      className="input !py-1.5 !text-xs"
                      placeholder="Label"
                      maxLength={24}
                      value={item.label}
                      onChange={(e) => updateQuickDraft(item.id, "label", e.target.value)}
                    />
                    <input
                      className="input !py-1.5 !text-xs font-mono"
                      placeholder="Command"
                      maxLength={160}
                      value={item.command}
                      onChange={(e) => updateQuickDraft(item.id, "command", e.target.value)}
                    />
                    <button
                      type="button"
                      className="icon-btn text-red-400 hover:text-red-300"
                      onClick={() => removeQuickDraft(item.id)}
                      aria-label="Remove quick command"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  className="btn-ghost !px-3 !py-1.5"
                  onClick={() => {
                    setQuickDrafts(quickCommands);
                    setShowQuickEditor(false);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn-primary !px-3 !py-1.5"
                  onClick={saveQuickDrafts}
                >
                  Save
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* xterm viewport */}
      <div
        ref={containerRef}
        className="flex-1 overflow-hidden border-x border-b border-slate-700 rounded-b-lg"
        style={{ background: "#0f1117" }}
      />

      {sshChallenge && (
        <FingerprintTrustModal
          title={sshChallenge.code === "SSH_HOST_UNTRUSTED" ? "Trust SSH Host Key" : "SSH Host Key Changed"}
          host={device.hostname}
          currentLabel="Presented fingerprint (SHA-256)"
          currentFingerprint={sshChallenge.fingerprint}
          previousLabel={sshChallenge.code === "SSH_HOST_CHANGED" ? "Previously trusted fingerprint" : undefined}
          previousFingerprint={sshChallenge.code === "SSH_HOST_CHANGED" ? sshChallenge.previous_fingerprint : undefined}
          acceptLabel={sshChallenge.code === "SSH_HOST_UNTRUSTED" ? "Trust host key" : "Trust new host key"}
          onAccept={() => resolveSshHostTrust(true)}
          onCancel={() => resolveSshHostTrust(false)}
        />
      )}
    </div>
  );
}
