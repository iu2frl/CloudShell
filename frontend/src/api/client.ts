const BASE = "/api";

// ── Token helpers ─────────────────────────────────────────────────────────────

/** Decode the JWT payload without verifying the signature (client-side only). */
function _decodePayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    return JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

/** Return the UTC expiry Date for the stored token, or null. */
export function getTokenExpiry(): Date | null {
  const token = localStorage.getItem("token");
  if (!token) return null;
  const payload = _decodePayload(token);
  if (!payload || typeof payload.exp !== "number") return null;
  return new Date(payload.exp * 1000);
}

/** True if a token exists AND has not expired yet. */
export function isLoggedIn(): boolean {
  const exp = getTokenExpiry();
  if (!exp) return false;
  return exp > new Date();
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────

/** Called by the 401 interceptor — clears state and fires a global event. */
function _forceLogout(): void {
  localStorage.removeItem("token");
  window.dispatchEvent(new Event("cloudshell:session-expired"));
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });
  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username, password });
  const res = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) throw new Error("Invalid credentials");
  const data = await res.json();
  localStorage.setItem("token", data.access_token);
}

export async function logout(): Promise<void> {
  try {
    await request<void>("/auth/logout", { method: "POST" });
  } catch {
    // ignore errors — we're logging out regardless
  } finally {
    localStorage.removeItem("token");
  }
}

export async function refreshToken(): Promise<void> {
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!res.ok) {
    _forceLogout();
    return;
  }
  const data = await res.json();
  localStorage.setItem("token", data.access_token);
}

export interface MeInfo {
  username: string;
  expires_at: string;
}

export const getMe = (): Promise<MeInfo> => request("/auth/me");

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  await request<void>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

// ── Devices ───────────────────────────────────────────────────────────────────

export interface Device {
  id: number;
  name: string;
  hostname: string;
  port: number;
  username: string;
  auth_type: "password" | "key";
  key_filename?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeviceCreate {
  name: string;
  hostname: string;
  port: number;
  username: string;
  auth_type: "password" | "key";
  password?: string;
  private_key?: string;
}

export const listDevices = (): Promise<Device[]> => request("/devices/");

export const createDevice = (d: DeviceCreate): Promise<Device> =>
  request("/devices/", { method: "POST", body: JSON.stringify(d) });

export const updateDevice = (id: number, d: Partial<DeviceCreate>): Promise<Device> =>
  request(`/devices/${id}`, { method: "PUT", body: JSON.stringify(d) });

export const deleteDevice = (id: number): Promise<void> =>
  request(`/devices/${id}`, { method: "DELETE" });

// ── Terminal ──────────────────────────────────────────────────────────────────

export async function openSession(deviceId: number): Promise<string> {
  const data = await request<{ session_id: string }>(`/terminal/session/${deviceId}`, {
    method: "POST",
  });
  return data.session_id;
}

export function terminalWsUrl(sessionId: string): string {
  const token = localStorage.getItem("token") ?? "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/terminal/ws/${sessionId}?token=${token}`;
}
