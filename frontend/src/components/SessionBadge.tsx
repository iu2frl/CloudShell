/**
 * SessionBadge — shows remaining session time in the topbar.
 *
 * - Green:  > 30 min remaining
 * - Yellow: 10–30 min remaining
 * - Red:    < 10 min remaining (pulses)
 */
import { useEffect, useState } from "react";
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

  useEffect(() => {
    const tick = () => {
      const exp = getTokenExpiry();
      setRemaining(exp ? Math.max(0, exp.getTime() - Date.now()) : 0);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const color =
    remaining > 30 * 60 * 1000
      ? "text-green-400 border-green-700/50"
      : remaining > 10 * 60 * 1000
      ? "text-yellow-400 border-yellow-700/50"
      : "text-red-400 border-red-700/50 animate-pulse";

  return (
    <div
      title="Session time remaining"
      className={`flex items-center gap-1.5 text-[10px] font-mono border rounded px-2 py-0.5 ${color}`}
    >
      <span className="text-slate-500 font-sans normal-case tracking-normal" style={{ fontSize: "10px" }}>Session timeout:</span>
      {formatRemaining(remaining)}
    </div>
  );
}
