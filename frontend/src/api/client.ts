const BASE = "/api";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

// ── Auth ────────────────────────────────────────────────────────────────────

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

export function logout(): void {
  localStorage.removeItem("token");
}

export function isLoggedIn(): boolean {
  return !!localStorage.getItem("token");
}

// ── Devices ─────────────────────────────────────────────────────────────────

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

// ── Terminal ─────────────────────────────────────────────────────────────────

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
