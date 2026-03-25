import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { get2FAStatus } from "../api/client";

interface Props {
  onClick: () => void;
}

export function TwoFactorButton({ onClick }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const status = await get2FAStatus();
        setEnabled(status.enabled);
      } catch {
        // ignore errors
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
    
    // Refresh status every 10 seconds
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  // Show yellow/warning color if 2FA is disabled, blue if enabled
  const colorClass = enabled
    ? "text-blue-400"
    : "text-yellow-400 border-yellow-700/50 hover:border-yellow-500/70";

  return (
    <button
      onClick={onClick}
      disabled={loading}
      title={enabled ? "Two-factor auth is enabled" : "Two-factor auth is disabled (warning)"}
      className={`icon-btn ${colorClass}`}
    >
      <Lock size={16} />
    </button>
  );
}
