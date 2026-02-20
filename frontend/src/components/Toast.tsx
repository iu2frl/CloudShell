/**
 * Toast notification system.
 *
 * Usage:
 *   import { useToast } from "./Toast";
 *   const toast = useToast();
 *   toast.success("Saved!");
 *   toast.error("Something went wrong");
 *   toast.info("Connecting…");
 *
 * Wrap your app (or the Dashboard) in <ToastProvider>.
 */
import { createContext, useCallback, useContext, useState, useRef } from "react";
import { X, CheckCircle2, AlertCircle, Info } from "lucide-react";

type Variant = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  variant: Variant;
}

interface ToastAPI {
  success: (msg: string) => void;
  error:   (msg: string) => void;
  info:    (msg: string) => void;
}

const ToastContext = createContext<ToastAPI | null>(null);
let _nextId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const t = timers.current.get(id);
    if (t) { clearTimeout(t); timers.current.delete(id); }
  }, []);

  const push = useCallback((message: string, variant: Variant) => {
    const id = ++_nextId;
    setToasts((prev) => [...prev.slice(-4), { id, message, variant }]);
    timers.current.set(id, setTimeout(() => dismiss(id), variant === "error" ? 6000 : 3500));
  }, [dismiss]);

  const api: ToastAPI = {
    success: (msg) => push(msg, "success"),
    error:   (msg) => push(msg, "error"),
    info:    (msg) => push(msg, "info"),
  };

  const icons: Record<Variant, React.ReactNode> = {
    success: <CheckCircle2 size={15} className="text-green-400 flex-shrink-0" />,
    error:   <AlertCircle  size={15} className="text-red-400   flex-shrink-0" />,
    info:    <Info         size={15} className="text-blue-400  flex-shrink-0" />,
  };

  const borders: Record<Variant, string> = {
    success: "border-green-700/60",
    error:   "border-red-700/60",
    info:    "border-blue-700/60",
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Toast stack — bottom-right */}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2.5 bg-slate-900 border ${borders[t.variant]}
              rounded-lg shadow-xl px-4 py-3 text-sm text-slate-200 max-w-sm
              animate-[slideIn_0.15s_ease-out]`}
          >
            {icons[t.variant]}
            <span className="flex-1 leading-snug">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="text-slate-500 hover:text-slate-300 transition-colors ml-1 flex-shrink-0"
            >
              <X size={13} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastAPI {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
