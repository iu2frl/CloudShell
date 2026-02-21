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

export type ConnectionType = "ssh" | "sftp";

export interface Device {
  id: number;
  name: string;
  hostname: string;
  port: number;
  username: string;
  auth_type: "password" | "key";
  connection_type: ConnectionType;
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
  connection_type: ConnectionType;
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

// ── Audit ─────────────────────────────────────────────────────────────────────

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  username: string;
  action: string;
  source_ip: string | null;
  detail: string | null;
}

export interface AuditLogPage {
  total: number;
  page: number;
  page_size: number;
  entries: AuditLogEntry[];
}

export const listAuditLogs = (page = 1, pageSize = 50): Promise<AuditLogPage> =>
  request(`/audit/logs?page=${page}&page_size=${pageSize}`);

// ── SFTP ──────────────────────────────────────────────────────────────────────

export interface SftpEntry {
  name: string;
  path: string;
  size: number;
  is_dir: boolean;
  permissions: string | null;
  modified: number;
}

export interface SftpListResponse {
  path: string;
  entries: SftpEntry[];
}

export async function openSftpSession(deviceId: number): Promise<string> {
  const data = await request<{ session_id: string }>(`/sftp/session/${deviceId}`, {
    method: "POST",
  });
  return data.session_id;
}

export async function closeSftpSession(sessionId: string): Promise<void> {
  await request<void>(`/sftp/session/${sessionId}`, { method: "DELETE" });
}

export async function sftpList(sessionId: string, path: string): Promise<SftpListResponse> {
  const encoded = encodeURIComponent(path);
  return request<SftpListResponse>(`/sftp/${sessionId}/list?path=${encoded}`);
}

export async function sftpDownload(sessionId: string, path: string): Promise<void> {
  const token = localStorage.getItem("token") ?? "";
  const encoded = encodeURIComponent(path);
  const res = await fetch(`${BASE}/sftp/${sessionId}/download?path=${encoded}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Download failed");
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : path.split("/").pop() ?? "download";
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function sftpUpload(
  sessionId: string,
  remotePath: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<void> {
  const token = localStorage.getItem("token") ?? "";
  const encoded = encodeURIComponent(remotePath);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/sftp/${sessionId}/upload?path=${encoded}`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        try {
          const err = JSON.parse(xhr.responseText);
          reject(new Error(err.detail ?? "Upload failed"));
        } catch {
          reject(new Error("Upload failed"));
        }
      }
    };

    xhr.onerror = () => reject(new Error("Network error during upload"));

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function sftpDelete(
  sessionId: string,
  path: string,
  isDir: boolean,
): Promise<void> {
  await request<void>(`/sftp/${sessionId}/delete`, {
    method: "POST",
    body: JSON.stringify({ path, is_dir: isDir }),
  });
}

export async function sftpRename(
  sessionId: string,
  oldPath: string,
  newPath: string,
): Promise<void> {
  await request<void>(`/sftp/${sessionId}/rename`, {
    method: "POST",
    body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
  });
}

export async function sftpMkdir(sessionId: string, path: string): Promise<void> {
  await request<void>(`/sftp/${sessionId}/mkdir`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}
