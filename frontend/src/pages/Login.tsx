import { useEffect, useState } from "react";
import { login } from "../api/client";
import { Terminal } from "lucide-react";

interface Props {
  onLogin: () => void;
}

export function Login({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [requires2FA, setRequires2FA] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => setVersion(d.version ?? null))
      .catch(() => { /* version stays null */ });
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password, requires2FA ? totpCode : undefined);
      onLogin();
    } catch (err: any) {
      if (err.message === "2FA_REQUIRED") {
        setRequires2FA(true);
      } else {
        setError(err.message || "Invalid username or password");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8 gap-3">
          <div className="w-14 h-14 rounded-2xl bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-900/40">
            <Terminal size={28} className="text-white" />
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-bold text-white">CloudShell by IU2FRL</h1>
            <p className="text-slate-400 text-sm mt-1">Self-hosted SSH gateway</p>
          </div>
        </div>

        {/* Card */}
        <div className="bg-slate-900 border border-slate-700 rounded-2xl p-8 shadow-2xl">
          {error && (
            <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-2 text-sm mb-5">
              {error}
            </div>
          )}
          <form onSubmit={submit} className="space-y-5">
            {!requires2FA ? (
              <>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                    Username
                  </label>
                  <input
                    className="input"
                    required
                    autoFocus
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="admin"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                    Password
                  </label>
                  <input
                    className="input"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                  />
                </div>
              </>
            ) : (
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                  Two-Factor Authentication
                </label>
                <input
                  className="input tracking-widest"
                  required
                  autoFocus
                  placeholder="000000"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/[^\d-a-zA-Z]/g, ""))}
                />
                <p className="text-xs text-slate-500 mt-2">
                  Enter the 6-digit code from your authenticator app, or a backup code.
                </p>
              </div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full mt-2"
            >
              {loading ? "Signing in…" : requires2FA ? "Verify Code" : "Sign in"}
            </button>
            {requires2FA && (
              <button
                type="button"
                onClick={() => {
                  setRequires2FA(false);
                  setTotpCode("");
                  setError(null);
                }}
                className="btn-ghost w-full mt-2"
              >
                Back to login
              </button>
            )}
          </form>
        </div>

        <p className="text-center text-slate-600 text-xs mt-6">
          CloudShell{version ? ` v${version}` : ""}
        </p>
      </div>
    </div>
  );
}
