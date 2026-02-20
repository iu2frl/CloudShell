import { useCallback, useEffect, useState } from "react";
import { isLoggedIn, getTokenExpiry, refreshToken } from "./api/client";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";

/** Refresh the token when less than this many ms remain. */
const REFRESH_BEFORE_EXPIRY_MS = 10 * 60 * 1000; // 10 min

function App() {
  const [authed, setAuthed] = useState(isLoggedIn);

  const handleLogout = useCallback(() => setAuthed(false), []);

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
        // Already within the refresh window — do it immediately
        refreshToken();
        return null;
      }
      return setTimeout(async () => {
        await refreshToken();
        scheduleRefresh(); // reschedule after the new token is stored
      }, msUntilRefresh);
    };

    const timer = scheduleRefresh();
    return () => { if (timer) clearTimeout(timer); };
  }, [authed]);

  return authed ? (
    <Dashboard onLogout={handleLogout} />
  ) : (
    <Login onLogin={() => setAuthed(true)} />
  );
}

export default App;
