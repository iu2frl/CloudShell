import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { openSession, terminalWsUrl } from "../api/client";

interface TerminalProps {
  deviceId: number;
}

export function Terminal({ deviceId }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new XTerm({
      theme: {
        background: "#0f1117",
        foreground: "#e2e8f0",
        cursor: "#3b82f6",
        selectionBackground: "#3b82f620",
        black: "#1a1d27",
        brightBlack: "#4a5568",
        red: "#fc8181",
        brightRed: "#feb2b2",
        green: "#68d391",
        brightGreen: "#9ae6b4",
        yellow: "#f6e05e",
        brightYellow: "#faf089",
        blue: "#63b3ed",
        brightBlue: "#90cdf4",
        magenta: "#d6bcfa",
        brightMagenta: "#e9d8fd",
        cyan: "#76e4f7",
        brightCyan: "#b2f5ea",
        white: "#e2e8f0",
        brightWhite: "#f7fafc",
      },
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 14,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: "block",
      scrollback: 5000,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());
    term.open(containerRef.current);
    fitAddon.fit();
    xtermRef.current = term;

    term.writeln("\x1b[36mCloudShell\x1b[0m — connecting…");

    let ws: WebSocket;

    const connect = async () => {
      try {
        const sessionId = await openSession(deviceId);
        const url = terminalWsUrl(sessionId);
        ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          term.clear();
          // Send initial terminal size
          const { rows, cols } = term;
          ws.send(`\x1b[8;${rows};${cols}t`);
        };

        ws.onmessage = (e) => term.write(e.data);

        ws.onclose = () => {
          term.writeln("\r\n\x1b[33m[disconnected]\x1b[0m");
        };

        ws.onerror = () => {
          term.writeln("\r\n\x1b[31m[connection error]\x1b[0m");
        };

        term.onData((data) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(data);
        });

        // Propagate resize
        const resizeObserver = new ResizeObserver(() => {
          fitAddon.fit();
          const { rows, cols } = term;
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(`\x1b[8;${rows};${cols}t`);
          }
        });
        if (containerRef.current) resizeObserver.observe(containerRef.current);
      } catch (err) {
        term.writeln(`\r\n\x1b[31m[error: ${err}]\x1b[0m`);
      }
    };

    connect();

    return () => {
      ws?.close();
      term.dispose();
    };
  }, [deviceId]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full rounded-lg overflow-hidden border border-slate-700"
      style={{ background: "#0f1117" }}
    />
  );
}
