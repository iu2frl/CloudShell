/**
 * SessionBadge — shows remaining session time in the topbar as a clickable
 * button. Clicking it opens a small popover that explains the JWT session
 * model and the automatic silent-refresh behaviour.
 *
 * Colour coding:
 * - Green:  > 30 min remaining
 * - Yellow: 10–30 min remaining
 * - Red:    < 10 min remaining (pulses)
 */
import { useEffect, useRef, useState } from "react";
import { Clock, X } from "lucide-react";
import { getTokenExpiry } from "../api/client";

function formatRemaining(ms: number): string {
  if (ms <= 0) return "expired";
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function SessionBadge() {
  const [remaining, setRemaining] = useState<number>(0);
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const tick = () => {
      const exp = getTokenExpiry();
      setRemaining(exp ? Math.max(0, exp.getTime() - Date.now()) : 0);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Close the popover when clicking outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current && !popoverRef.current.contains(e.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const colorClass =
    remaining > 30 * 60 * 1000
      ? "text-green-400 border-green-700/50 hover:border-green-500/70"
      : remaining > 10 * 60 * 1000
      ? "text-yellow-400 border-yellow-700/50 hover:border-yellow-500/70"
      : "text-red-400 border-red-700/50 hover:border-red-500/70 animate-pulse";

  const expiresAt = getTokenExpiry();
  const expiresAtStr = expiresAt
    ? expiresAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div className="relative">
      {/* Trigger button — clock icon only, no countdown text */}
      <button
        ref={buttonRef}
        onClick={() => setOpen((v) => !v)}
        title="Session info"
        className={`flex items-center justify-center border rounded p-1.5
                    bg-transparent transition-colors cursor-pointer ${colorClass}`}
      >
        <Clock size={15} className="flex-shrink-0" />
      </button>

      {/* Popover — full-screen overlay, panel centered */}
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          <div
            ref={popoverRef}
            className="w-80 bg-slate-800 border border-slate-600 rounded-xl shadow-2xl
                       text-slate-300 text-xs leading-relaxed p-4"
            role="dialog"
            aria-label="Session information"
          >
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 font-semibold text-slate-100 text-sm">
              <Clock size={14} className={colorClass.split(" ")[0]} />
              Session timeout
            </div>
            <button
              onClick={() => setOpen(false)}
              className="icon-btn text-slate-500 hover:text-slate-200"
              aria-label="Close"
            >
              <X size={13} />
            </button>
          </div>

          {/* Live countdown */}
          <div className={`font-mono text-lg font-bold mb-3 ${colorClass.split(" ")[0]}`}>
            {formatRemaining(remaining)}
            {expiresAtStr && (
              <span className="text-slate-500 font-sans font-normal text-[11px] ml-2 normal-case tracking-normal">
                (expires at {expiresAtStr})
              </span>
            )}
          </div>

          {/* Explanation */}
          <p className="text-slate-400 mb-2">
            CloudShell uses a short-lived <span className="text-slate-200 font-medium">JSON Web Token (JWT)</span> to
            authenticate your browser session. The token lifetime is set by the server administrator
            via the <code className="bg-slate-700 px-1 rounded text-slate-300">TOKEN_TTL_HOURS</code> environment variable (default: 8 h).
          </p>
          <p className="text-slate-400 mb-2">
            The frontend <span className="text-slate-200 font-medium">automatically refreshes</span> the token
            10 minutes before it expires — as long as the tab stays open, your session will renew itself silently
            without interrupting active SSH connections.
          </p>
          <p className="text-slate-400">
            If the token expires (e.g. the tab was closed for too long), you will be redirected to the login page
            and all active terminal sessions will be terminated.
          </p>
          </div>
        </div>
      )}
    </div>
  );
}

