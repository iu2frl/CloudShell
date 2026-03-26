import { ShieldAlert, X } from "lucide-react";

interface Props {
  title: string;
  host: string;
  currentLabel: string;
  currentFingerprint: string;
  previousLabel?: string;
  previousFingerprint?: string;
  acceptLabel: string;
  onAccept: () => void;
  onCancel: () => void;
}

export function FingerprintTrustModal({
  title,
  host,
  currentLabel,
  currentFingerprint,
  previousLabel,
  previousFingerprint,
  acceptLabel,
  onAccept,
  onCancel,
}: Props) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div className="flex items-center gap-2 text-white font-semibold">
            <ShieldAlert size={16} className="text-amber-400" />
            {title}
          </div>
          <button onClick={onCancel} className="text-slate-400 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-slate-300">
            Verify this fingerprint for <span className="font-semibold text-white">{host}</span> before continuing.
          </p>

          {previousLabel && previousFingerprint && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">{previousLabel}</p>
              <p className="break-all rounded bg-slate-950 border border-slate-700 px-3 py-2 font-mono text-[11px] text-slate-300">
                {previousFingerprint}
              </p>
            </div>
          )}

          <div className="space-y-1">
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">{currentLabel}</p>
            <p className="break-all rounded bg-slate-950 border border-slate-700 px-3 py-2 font-mono text-[11px] text-slate-200">
              {currentFingerprint}
            </p>
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <button onClick={onCancel} className="btn-ghost">
              Cancel
            </button>
            <button onClick={onAccept} className="btn-primary">
              {acceptLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
