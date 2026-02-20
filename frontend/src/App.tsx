import { useCallback, useEffect, useState } from "react";
import { isLoggedIn, getTokenExpiry, refreshToken } from "./api/client";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { ToastProvider } from "./components/Toast";
import { ErrorBoundary } from "./components/ErrorBoundary";

/** Refresh the token when less than this many ms remain. */
const REFRESH_BEFORE_EXPIRY_MS = 10 * 60 * 1000; // 10 min

function App() {
  const [authed, setAuthed] = useState(isLoggedIn);
  const [backendDown, setBackendDown] = useState(false);

  const handleLogout = useCallback(() => setAuthed(false), []);

  // Check backend health on mount
  useEffect(() => {
    fetch("/api/health")
      .then((r) => { if (!r.ok) throw new Error(); setBackendDown(false); })
      .catch(() => setBackendDown(true));
  }, []);

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
        {backendDown && (
          <div className="fixed top-0 left-0 right-0 z-50 bg-red-900/90 border-b border-red-700
                          text-red-200 text-xs text-center py-1.5 px-4">
            ⚠ Cannot reach the CloudShell backend — check that the server is running.
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
