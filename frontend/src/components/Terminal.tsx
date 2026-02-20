import { useEffect, useRef, useState, useCallback } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { openSession, terminalWsUrl } from "../api/client";
import { RefreshCw, Wifi, WifiOff, Loader } from "lucide-react";

type ConnState = "connecting" | "connected" | "disconnected" | "error";

interface TerminalProps {
  deviceId: number;
}

export function Terminal({ deviceId }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const xtermRef    = useRef<XTerm | null>(null);
  const fitRef      = useRef<FitAddon | null>(null);
  const wsRef       = useRef<WebSocket | null>(null);
  const [connState, setConnState] = useState<ConnState>("connecting");

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

    // Close any existing socket first
    wsRef.current?.close();
    setConnState("connecting");
    term.writeln("\x1b[36mCloudShell\x1b[0m — connecting…");

    let sessionId: string;
    try {
      sessionId = await openSession(deviceId);
    } catch (err) {
      term.writeln(`\r\n\x1b[31m[connection failed: ${err}]\x1b[0m`);
      setConnState("error");
      return;
    }

    const url = terminalWsUrl(sessionId);
    const ws  = new WebSocket(url);
    ws.binaryType = "arraybuffer";   // receive raw bytes
    wsRef.current = ws;

    ws.onopen = () => {
      setConnState("connected");
      term.clear();
      // Send initial size
      const { rows, cols } = term;
      ws.send(JSON.stringify({ type: "resize", cols, rows }));
    };

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer
        ? new Uint8Array(e.data)
        : new TextEncoder().encode(e.data as string);
      term.write(data);
    };

    ws.onclose = (e) => {
      const clean = e.wasClean && e.code === 1000;
      setConnState(clean ? "disconnected" : "error");
      term.writeln(`\r\n\x1b[33m[disconnected${clean ? "" : ` code=${e.code}`}]\x1b[0m`);
    };

    ws.onerror = () => {
      setConnState("error");
    };

    // Forward keystrokes as raw bytes
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    // Resize observer → fit + notify SSH
    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* ignore */ }
      const { rows, cols } = term;
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols, rows }));
      }
    });
    if (containerRef.current) ro.observe(containerRef.current);

    // Cleanup when the component for this tab is hidden/removed
    ws.addEventListener("close", () => ro.disconnect());
  }, [deviceId]);

  // Initial connect
  useEffect(() => { connect(); }, [connect]);

  // ── Status badge ────────────────────────────────────────────────────────────
  const badge: Record<ConnState, { icon: React.ReactNode; label: string; cls: string }> = {
    connecting:   { icon: <Loader    size={12} className="animate-spin" />, label: "Connecting",   cls: "text-yellow-400 border-yellow-700" },
    connected:    { icon: <Wifi      size={12} />,                          label: "Connected",    cls: "text-green-400  border-green-700"  },
    disconnected: { icon: <WifiOff   size={12} />,                          label: "Disconnected", cls: "text-slate-400  border-slate-600"  },
    error:        { icon: <WifiOff   size={12} />,                          label: "Error",        cls: "text-red-400    border-red-700"    },
  };
  const b = badge[connState];

  return (
    <div className="flex flex-col h-full gap-0">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1 bg-slate-900 border border-slate-700 rounded-t-lg flex-shrink-0">
        <div className={`flex items-center gap-1.5 text-xs border rounded px-2 py-0.5 ${b.cls}`}>
          {b.icon}
          <span>{b.label}</span>
        </div>
        <button
          onClick={connect}
          title="Reconnect"
          className="icon-btn"
          disabled={connState === "connecting" || connState === "connected"}
        >
          <RefreshCw size={13} className={connState === "connecting" ? "animate-spin" : ""} />
        </button>
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
