import { useEffect, useState } from "react";
import { X, Key, AlertCircle, Check } from "lucide-react";
import { get2FAStatus, setup2FA, enable2FA, disable2FA } from "../api/client";

interface Props {
  onClose: () => void;
}

type SetupStep = "idle" | "setup" | "verify" | "success";

export function TwoFactorModal({ onClose }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [setupStep, setSetupStep] = useState<SetupStep>("idle");
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [verifyCode, setVerifyCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    try {
      const response = await get2FAStatus();
      setEnabled(response.enabled);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleSetupStart = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await setup2FA();
      setQrCode(response.qr_code);
      setSecret(response.secret);
      setBackupCodes(response.backup_codes);
      setSetupStep("setup");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleEnable = async (e: React.FormEvent) => {
    e.preventDefault();
    if (verifyCode.length !== 6) {
      setError("Please enter a 6-digit code");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await enable2FA(verifyCode);
      setSetupStep("success");
      setEnabled(true);
      setTimeout(() => {
        onClose();
      }, 2000);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    if (disableCode.length !== 6) {
      setError("Please enter a 6-digit code");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await disable2FA(disableCode);
      setEnabled(false);
      setDisableCode("");
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDownloadBackupCodes = () => {
    const text = backupCodes.join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cloudshell-backup-codes.txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
        <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-sm shadow-2xl p-6">
          <div className="text-center text-slate-400">Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-sm shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div className="flex items-center gap-2 text-white font-semibold">
            <Key size={16} className="text-blue-400" />
            Two-Factor Authentication
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {enabled ? (
            <div className="space-y-4">
              {/* Status badge */}
              <div className="bg-green-900/20 border border-green-700 rounded-lg px-4 py-3">
                <div className="flex items-center gap-2 text-green-300 text-sm font-medium">
                  <Check size={16} />
                  Two-factor authentication is enabled
                </div>
              </div>

              {/* Backup codes section */}
              <div className="space-y-3">
                <div className="text-sm text-slate-400">
                  <div className="font-medium mb-2">Backup codes</div>
                  <p className="text-xs mb-3">
                    Use these codes if you lose access to your authenticator app. Each code can be used once.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={handleDownloadBackupCodes}
                      className="btn-secondary text-sm flex-1"
                    >
                      Download
                    </button>
                    <button
                      onClick={() => navigator.clipboard.writeText(backupCodes.join("\n"))}
                      className="btn-secondary text-sm flex-1"
                    >
                      Copy
                    </button>
                  </div>
                </div>
              </div>

              {/* Disable section */}
              <div className="border-t border-slate-700 pt-4 space-y-3">
                <label className="text-xs font-medium text-slate-400 uppercase tracking-wide block">
                  Disable two-factor auth
                </label>
                <p className="text-xs text-slate-500">
                  Enter a code from your authenticator to disable 2FA.
                </p>
                <form onSubmit={handleDisable} className="space-y-3">
                  <input
                    className="input text-center text-2xl tracking-widest"
                    type="text"
                    placeholder="000000"
                    maxLength={6}
                    value={disableCode}
                    onChange={(e) =>
                      setDisableCode(e.target.value.replace(/[^\d]/g, ""))
                    }
                  />
                  {error && (
                    <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-3 py-2 text-xs">
                      {error}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={onClose}
                      className="btn-ghost flex-1"
                    >
                      Close
                    </button>
                    <button
                      type="submit"
                      disabled={saving || disableCode.length !== 6}
                      className="btn-danger flex-1"
                    >
                      {saving ? "Disabling..." : "Disable 2FA"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          ) : setupStep === "success" ? (
            <div className="text-center space-y-4">
              <div className="text-green-400 text-sm font-medium flex items-center justify-center gap-2">
                <Check size={16} />
                2FA enabled successfully!
              </div>
              <p className="text-xs text-slate-400">
                Your account is now protected with two-factor authentication.
              </p>
              <button onClick={onClose} className="btn-primary w-full">
                Close
              </button>
            </div>
          ) : setupStep === "setup" ? (
            <div className="space-y-4">
              <div className="bg-blue-900/20 border border-blue-700 rounded-lg px-4 py-3">
                <p className="text-blue-300 text-sm font-medium">
                  Scan this QR code with Google Authenticator or similar app
                </p>
              </div>

              {qrCode && (
                <div className="bg-white rounded-lg p-2 w-48 h-48 mx-auto flex items-center justify-center">
                  <img src={qrCode} alt="2FA QR Code" className="w-full h-full" />
                </div>
              )}

              <div className="space-y-2">
                <p className="text-xs text-slate-400 text-center">
                  Can't scan? Enter this key manually in your authenticator:
                </p>
                {secret && (
                  <div className="bg-slate-800 rounded px-3 py-2 font-mono text-xs text-slate-300 break-all text-center">
                    {secret}
                  </div>
                )}
              </div>

              <div className="border-t border-slate-700 pt-4 space-y-3">
                <label className="text-xs font-medium text-slate-400 uppercase tracking-wide block">
                  Enter 6-digit code to verify
                </label>
                <form onSubmit={handleEnable} className="space-y-3">
                  <input
                    className="input text-center text-2xl tracking-widest"
                    type="text"
                    placeholder="000000"
                    maxLength={6}
                    value={verifyCode}
                    onChange={(e) =>
                      setVerifyCode(e.target.value.replace(/[^\d]/g, ""))
                    }
                    autoFocus
                  />
                  {error && (
                    <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-3 py-2 text-xs">
                      {error}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setSetupStep("idle")}
                      className="btn-ghost flex-1"
                    >
                      Back
                    </button>
                    <button
                      type="submit"
                      disabled={saving || verifyCode.length !== 6}
                      className="btn-primary flex-1"
                    >
                      {saving ? "Verifying..." : "Enable 2FA"}
                    </button>
                  </div>
                </form>
              </div>

              {backupCodes.length > 0 && (
                <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg px-4 py-3 space-y-2">
                  <p className="text-xs font-medium text-yellow-300 flex items-center gap-2">
                    <AlertCircle size={14} />
                    Save your backup codes
                  </p>
                  <p className="text-xs text-yellow-200">
                    Each code can be used once if you lose your phone.
                  </p>
                  <button
                    onClick={handleDownloadBackupCodes}
                    className="btn-secondary text-xs w-full"
                  >
                    Download Backup Codes
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg px-4 py-3">
                <div className="flex items-center gap-2 text-yellow-300 text-sm font-medium">
                  <AlertCircle size={16} />
                  Two-factor authentication is disabled
                </div>
              </div>
              <p className="text-sm text-slate-400">
                Protect your account with two-factor authentication. You will be asked for a code from your phone whenever you log in.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={onClose}
                  className="btn-ghost flex-1"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSetupStart}
                  disabled={loading}
                  className="btn-primary flex-1"
                >
                  {loading ? "Loading..." : "Enable 2FA"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
