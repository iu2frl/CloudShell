import { useCallback, useEffect, useRef, useState } from "react";
import { getMe, getTokenExpiry, isLoggedIn, refreshToken } from "./api/client";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { ToastProvider } from "./components/Toast";
import { ErrorBoundary } from "./components/ErrorBoundary";

/** Refresh the token when less than this many ms remain. */
const REFRESH_BEFORE_EXPIRY_MS = 10 * 60 * 1000; // 10 min
const HEALTH_CHECK_INTERVAL_MS = 5000;

function App() {
  const [authed, setAuthed] = useState(isLoggedIn);
  const [connectionLost, setConnectionLost] = useState(false);
  const [recoveringSession, setRecoveringSession] = useState(false);
  const shouldRecoverSessionRef = useRef(false);

  const handleLogout = useCallback(() => setAuthed(false), []);

  const probeBackend = useCallback(async () => {
    if (!navigator.onLine) {
      setConnectionLost(true);
      return;
    }

    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) {
        throw new Error("Backend health check failed");
      }
      setConnectionLost(false);
    } catch {
      setConnectionLost(true);
    }
  }, []);

  const recoverSession = useCallback(async () => {
    try {
      await refreshToken();
      await getMe();
      setAuthed(true);
      return true;
    } catch {
      return false;
    }
  }, []);

  // Continuously monitor backend reachability and browser online/offline status.
  useEffect(() => {
    void probeBackend();

    const intervalId = window.setInterval(() => {
      void probeBackend();
    }, HEALTH_CHECK_INTERVAL_MS);

    const handleOnline = () => {
      void probeBackend();
    };

    const handleOffline = () => {
      setConnectionLost(true);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [probeBackend]);

  // If the app was authenticated when connection drops, request recovery on reconnect.
  useEffect(() => {
    if (connectionLost && authed) {
      shouldRecoverSessionRef.current = true;
    }
  }, [authed, connectionLost]);

  // On reconnect, recover session first. If recovery fails, return to login.
  useEffect(() => {
    if (connectionLost || !shouldRecoverSessionRef.current) {
      return;
    }

    shouldRecoverSessionRef.current = false;
    let cancelled = false;
    setRecoveringSession(true);

    (async () => {
      const recovered = await recoverSession();
      if (cancelled) {
        return;
      }
      setRecoveringSession(false);
      if (!recovered) {
        setAuthed(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [connectionLost, recoverSession]);

  // Listen for the global "session expired" event fired by the 401 interceptor
  useEffect(() => {
    const handler = () => setAuthed(false);
    window.addEventListener("cloudshell:session-expired", handler);
    return () => window.removeEventListener("cloudshell:session-expired", handler);
  }, []);

  // Background token-refresh timer
  useEffect(() => {
    if (!authed) return;

    const scheduleRefresh = () => {
      const exp = getTokenExpiry();
      if (!exp) return null;
      const msUntilRefresh = exp.getTime() - Date.now() - REFRESH_BEFORE_EXPIRY_MS;
      if (msUntilRefresh <= 0) {
        refreshToken();
        return null;
      }
      return setTimeout(async () => {
        await refreshToken();
        scheduleRefresh();
      }, msUntilRefresh);
    };

    const timer = scheduleRefresh();
    return () => { if (timer) clearTimeout(timer); };
  }, [authed]);

  return (
    <ErrorBoundary>
      <ToastProvider>
        {connectionLost && (
          <div className="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-6">
            <div className="w-full max-w-md rounded-xl border border-red-700 bg-red-950/70 p-5 text-center">
              <h2 className="text-lg font-semibold text-red-200">Connection lost</h2>
              <p className="mt-2 text-sm text-red-300">
                Cannot reach the CloudShell backend. We will automatically retry.
              </p>
            </div>
          </div>
        )}
        {recoveringSession && (
          <div className="fixed inset-0 z-50 bg-slate-950/75 backdrop-blur-sm flex items-center justify-center p-6">
            <div className="w-full max-w-md rounded-xl border border-slate-600 bg-slate-900 p-5 text-center">
              <h2 className="text-lg font-semibold text-white">Connection restored</h2>
              <p className="mt-2 text-sm text-slate-300">
                Recovering your session.
              </p>
            </div>
          </div>
        )}
        {authed ? (
          <Dashboard onLogout={handleLogout} />
        ) : (
          <Login onLogin={() => setAuthed(true)} />
        )}
      </ToastProvider>
    </ErrorBoundary>
  );
}

export default App;
