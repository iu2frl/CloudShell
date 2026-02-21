import { useEffect, useRef, useState, useCallback } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { Device, openSession, terminalWsUrl } from "../api/client";
import { RefreshCw, Wifi, WifiOff, Loader, Copy } from "lucide-react";
import { useToast } from "./Toast";

type ConnState = "connecting" | "connected" | "disconnected" | "error" | "failed";

const MAX_RETRIES = 3;

interface TerminalProps {
  device: Device;
}

export function Terminal({ device }: TerminalProps) {
  const containerRef   = useRef<HTMLDivElement>(null);
  const xtermRef       = useRef<XTerm | null>(null);
  const fitRef         = useRef<FitAddon | null>(null);
  const wsRef          = useRef<WebSocket | null>(null);
  const retriesRef     = useRef(0);
  const connectingRef  = useRef(false);
  const onDataDisposer = useRef<ReturnType<XTerm["onData"]> | null>(null);
  const [connState, setConnState] = useState<ConnState>("connecting");
  const toast = useToast();
  // Stable ref so connect() doesn't need toast in its dep array (prevents reconnect loop)
  const toastRef = useRef(toast);
  useEffect(() => { toastRef.current = toast; });

  // ── Build the xterm instance once ──────────────────────────────────────────
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

  // ── Connect / reconnect ─────────────────────────────────────────────────────
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
      sessionId = await openSession(device.id);
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

    const url = terminalWsUrl(sessionId);
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
      ro.disconnect();
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

    // Guard: only resize/send while the socket is still open to prevent the
    // ResizeObserver from spinning in a tight loop after the backend drops.
    // The observer is also disconnected on both close and error events.
    let resizing = false;
    const ro = new ResizeObserver(() => {
      if (ws.readyState !== WebSocket.OPEN) { ro.disconnect(); return; }
      if (resizing) return;
      resizing = true;
      try { fit.fit(); } catch { /* ignore */ }
      resizing = false;
      const { rows, cols } = term;
      ws.send(new TextEncoder().encode(JSON.stringify({ type: "resize", cols, rows })));
    });
    if (containerRef.current) ro.observe(containerRef.current);
    ws.addEventListener("close", () => ro.disconnect());
  // toast intentionally excluded — accessed via toastRef to keep connect() stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device.id, device.name]);

  useEffect(() => { connect(); }, [connect]);

  // ── Explicit cleanup on unmount (tab close) ──────────────────────────────────
  // Without this, closing the tab only removes the DOM node; the WebSocket
  // lingers in a half-open state and the server never receives a clean close
  // frame, so SESSION_ENDED is not written until the connection times out.
  useEffect(() => {
    return () => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        wsRef.current = null;   // prevent onclose handler from firing
        ws.close(1000, "tab closed");
      }
    };
  }, []);

  // ── Copy session info ────────────────────────────────────────────────────────
  const copyInfo = () => {
    navigator.clipboard.writeText(`${device.username}@${device.hostname}:${device.port}`);
    toastRef.current.info("Copied to clipboard");
  };

  // ── Status badge ────────────────────────────────────────────────────────────
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
        </div>
      </div>

      {/* xterm viewport */}
      <div
        ref={containerRef}
        className="flex-1 overflow-hidden border-x border-b border-slate-700 rounded-b-lg"
        style={{ background: "#0f1117" }}
      />
    </div>
  );
}
