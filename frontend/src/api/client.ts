const BASE = "/api";
const TOKEN_EXPIRY_KEY = "cloudshell_token_expiry";

// -- Token helpers -------------------------------------------------------------

/** Store token expiry in sessionStorage for the countdown badge. */
function _storeTokenExpiry(expiresAt: string): void {
  try {
    const expiryTime = new Date(expiresAt).getTime();
    sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());
  } catch {
    // Ignore storage errors
  }
}

/** Return the UTC expiry Date for the stored token, or null. */
export function getTokenExpiry(): Date | null {
  try {
    const stored = sessionStorage.getItem(TOKEN_EXPIRY_KEY);
    if (!stored) return null;
    const timestamp = parseInt(stored, 10);
    if (isNaN(timestamp)) return null;
    return new Date(timestamp);
  } catch {
    return null;
  }
}

/** True if a token exists AND has not expired yet. */
export function isLoggedIn(): boolean {
  const exp = getTokenExpiry();
  if (!exp) return false;
  return exp > new Date();
}

function authHeaders(): HeadersInit {
  // httpOnly cookie is sent automatically by the browser
  // No need to manually add Authorization header
  return {};
}

// -- Core fetch wrapper --------------------------------------------------------

/** Called by the 401 interceptor — clears state and fires a global event. */
function _forceLogout(): void {
  sessionStorage.removeItem(TOKEN_EXPIRY_KEY);
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

// -- Auth ----------------------------------------------------------------------

export async function login(
  username: string,
  password: string,
  totpCode?: string,
  rememberDevice?: boolean,
): Promise<void> {
  const form = new URLSearchParams({ username, password });
  if (totpCode) {
    form.append("totp_code", totpCode);
  }
  if (rememberDevice) {
    form.append("remember_device", "true");
  }
  const res = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    if (res.status === 403 && errorData.detail === "2FA_REQUIRED") {
      throw new Error("2FA_REQUIRED");
    }
    if (res.status === 401 && errorData.detail === "Invalid 2FA code") {
      throw new Error("Invalid 2FA code");
    }
    throw new Error("Invalid credentials");
  }
  
  const data = await res.json();
  _storeTokenExpiry(data.expires_at);
}

export async function logout(): Promise<void> {
  try {
    await request<void>("/auth/logout", { method: "POST" });
  } catch {
    // ignore errors — we're logging out regardless
  } finally {
    sessionStorage.removeItem(TOKEN_EXPIRY_KEY);
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
  _storeTokenExpiry(data.expires_at);
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

// -- Devices -------------------------------------------------------------------

export type ConnectionType = "ssh" | "sftp" | "ftp" | "ftps";

export interface Device {
  id: number;
  name: string;
  hostname: string;
  port: number;
  username: string;
  auth_type: "password" | "key";
  connection_type: ConnectionType;
  ssh_host_fingerprint?: string | null;
  key_filename?: string | null;
  ftps_cert_thumbprint?: string | null;
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

export interface DeviceUpdate extends Partial<DeviceCreate> {
  ssh_host_fingerprint?: string | null;
  ftps_cert_thumbprint?: string | null;
}

export const listDevices = (): Promise<Device[]> => request("/devices/");

export const createDevice = (d: DeviceCreate): Promise<Device> =>
  request("/devices/", { method: "POST", body: JSON.stringify(d) });

export const updateDevice = (id: number, d: DeviceUpdate): Promise<Device> =>
  request(`/devices/${id}`, { method: "PUT", body: JSON.stringify(d) });

export const deleteDevice = (id: number): Promise<void> =>
  request(`/devices/${id}`, { method: "DELETE" });

// -- Terminal ------------------------------------------------------------------

export type SshHostChallengeCode = "SSH_HOST_UNTRUSTED" | "SSH_HOST_CHANGED";

export interface SshHostChallengeDetail {
  code: SshHostChallengeCode;
  fingerprint: string;
  previous_fingerprint?: string;
}

export class SshHostChallengeError extends Error {
  readonly detail: SshHostChallengeDetail;

  constructor(detail: SshHostChallengeDetail) {
    super(detail.code);
    this.name = "SshHostChallengeError";
    this.detail = detail;
  }
}

function isSshHostChallengeDetail(value: unknown): value is SshHostChallengeDetail {
  if (!value || typeof value !== "object") return false;
  const detail = value as Record<string, unknown>;
  const code = detail.code;
  if (code !== "SSH_HOST_UNTRUSTED" && code !== "SSH_HOST_CHANGED") return false;
  return typeof detail.fingerprint === "string";
}

export async function openSession(
  deviceId: number,
  options?: { trustHost?: boolean },
): Promise<string> {
  const trustHost = options?.trustHost === true;
  const suffix = trustHost ? "?trust_host=true" : "";
  const res = await fetch(`${BASE}/terminal/session/${deviceId}${suffix}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });

  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }

  const data = await res.json().catch(() => ({ detail: res.statusText }));
  if (!res.ok) {
    if (res.status === 409 && isSshHostChallengeDetail(data.detail)) {
      throw new SshHostChallengeError(data.detail);
    }
    throw new Error(data.detail ?? "Request failed");
  }

  return (data as { session_id: string }).session_id;
}

export interface TerminalWsTicket {
  ticket: string;
  expires_in: number;
}

export async function createTerminalWsTicket(sessionId: string): Promise<TerminalWsTicket> {
  return request<TerminalWsTicket>(`/terminal/ws-ticket/${sessionId}`, {
    method: "POST",
  });
}

export function terminalWsUrl(sessionId: string, ticket: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const encodedTicket = encodeURIComponent(ticket);
  return `${proto}://${window.location.host}/api/terminal/ws/${sessionId}?ticket=${encodedTicket}`;
}

// -- Audit ---------------------------------------------------------------------

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

// -- SFTP ----------------------------------------------------------------------

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

export async function openSftpSession(
  deviceId: number,
  options?: { trustHost?: boolean },
): Promise<string> {
  const trustHost = options?.trustHost === true;
  const suffix = trustHost ? "?trust_host=true" : "";
  const res = await fetch(`${BASE}/sftp/session/${deviceId}${suffix}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });

  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }

  const data = await res.json().catch(() => ({ detail: res.statusText }));
  if (!res.ok) {
    if (res.status === 409 && isSshHostChallengeDetail(data.detail)) {
      throw new SshHostChallengeError(data.detail);
    }
    throw new Error(data.detail ?? "Request failed");
  }

  return (data as { session_id: string }).session_id;
}

export async function closeSftpSession(sessionId: string): Promise<void> {
  await request<void>(`/sftp/session/${sessionId}`, { method: "DELETE" });
}

export async function sftpList(sessionId: string, path: string): Promise<SftpListResponse> {
  const encoded = encodeURIComponent(path);
  return request<SftpListResponse>(`/sftp/${sessionId}/list?path=${encoded}`);
}

export async function sftpDownload(sessionId: string, path: string): Promise<void> {
  const encoded = encodeURIComponent(path);
  const res = await fetch(`${BASE}/sftp/${sessionId}/download?path=${encoded}`);
  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }
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
  const encoded = encodeURIComponent(remotePath);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/sftp/${sessionId}/upload?path=${encoded}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else if (xhr.status === 401) {
        _forceLogout();
        reject(new Error("Session expired"));
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

// -- FTP / FTPS ----------------------------------------------------------------

export type FtpsCertificateChallengeCode = "FTPS_CERT_UNTRUSTED" | "FTPS_CERT_CHANGED";

export interface FtpsCertificateChallengeDetail {
  code: FtpsCertificateChallengeCode;
  thumbprint: string;
  previous_thumbprint?: string;
}

export class FtpsCertificateChallengeError extends Error {
  readonly detail: FtpsCertificateChallengeDetail;

  constructor(detail: FtpsCertificateChallengeDetail) {
    super(detail.code);
    this.name = "FtpsCertificateChallengeError";
    this.detail = detail;
  }
}

function isFtpsCertificateChallengeDetail(value: unknown): value is FtpsCertificateChallengeDetail {
  if (!value || typeof value !== "object") return false;
  const detail = value as Record<string, unknown>;
  const code = detail.code;
  if (code !== "FTPS_CERT_UNTRUSTED" && code !== "FTPS_CERT_CHANGED") return false;
  return typeof detail.thumbprint === "string";
}

export async function openFtpSession(
  deviceId: number,
  options?: { trustCert?: boolean },
): Promise<string> {
  const trustCert = options?.trustCert === true;
  const suffix = trustCert ? "?trust_cert=true" : "";
  const res = await fetch(`${BASE}/ftp/session/${deviceId}${suffix}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });

  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }

  const err = await res.json().catch(() => ({ detail: res.statusText }));
  if (!res.ok) {
    if (res.status === 409 && isFtpsCertificateChallengeDetail(err.detail)) {
      throw new FtpsCertificateChallengeError(err.detail);
    }
    throw new Error(err.detail ?? "Request failed");
  }

  return (err as { session_id: string }).session_id;
}

export async function closeFtpSession(sessionId: string): Promise<void> {
  await request<void>(`/ftp/session/${sessionId}`, { method: "DELETE" });
}

export async function ftpList(sessionId: string, path: string): Promise<SftpListResponse> {
  const encoded = encodeURIComponent(path);
  return request<SftpListResponse>(`/ftp/${sessionId}/list?path=${encoded}`);
}

export async function ftpDownload(sessionId: string, path: string): Promise<void> {
  const encoded = encodeURIComponent(path);
  const res = await fetch(`${BASE}/ftp/${sessionId}/download?path=${encoded}`);
  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }
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

export async function ftpUpload(
  sessionId: string,
  remotePath: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<void> {
  const encoded = encodeURIComponent(remotePath);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/ftp/${sessionId}/upload?path=${encoded}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else if (xhr.status === 401) {
        _forceLogout();
        reject(new Error("Session expired"));
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

export async function ftpDelete(
  sessionId: string,
  path: string,
  isDir: boolean,
): Promise<void> {
  await request<void>(`/ftp/${sessionId}/delete`, {
    method: "POST",
    body: JSON.stringify({ path, is_dir: isDir }),
  });
}

export async function ftpRename(
  sessionId: string,
  oldPath: string,
  newPath: string,
): Promise<void> {
  await request<void>(`/ftp/${sessionId}/rename`, {
    method: "POST",
    body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
  });
}

export async function ftpMkdir(sessionId: string, path: string): Promise<void> {
  await request<void>(`/ftp/${sessionId}/mkdir`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

// -- Config transfer -----------------------------------------------------------

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: number;
  messages: string[];
}

export interface GeneratedKeyPair {
  private_key: string;
  public_key: string;
}

export const generateKeyPair = (): Promise<GeneratedKeyPair> =>
  request<GeneratedKeyPair>("/keys/generate", { method: "POST" });

/** Download the current device configuration as a JSON blob URL ready for saving. */
export async function exportConfig(): Promise<Blob> {
  const res = await fetch(`${BASE}/config/export`, {
    headers: { ...authHeaders() },
  });
  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Export failed");
  }
  return res.blob();
}

/** Upload a previously-exported JSON file and import its devices. */
export async function importConfig(file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/config/import`, {
    method: "POST",
    headers: { ...authHeaders() },
    body: form,
  });
  if (res.status === 401) {
    _forceLogout();
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Import failed");
  }
  return res.json() as Promise<ImportResult>;
}

// -- Two-Factor Auth -----------------------------------------------------------

export interface TOTPSetupResponse {
  qr_code: string;
  backup_codes: string[];
}

export interface TwoFAStatus {
  enabled: boolean;
}

export const get2FAStatus = (): Promise<TwoFAStatus> => request("/auth/2fa/status");

export const setup2FA = (): Promise<TOTPSetupResponse> =>
  request("/auth/2fa/setup", { method: "POST" });

export const enable2FA = (token: string): Promise<void> =>
  request<void>("/auth/2fa/enable", {
    method: "POST",
    body: JSON.stringify({ token }),
  });

export const disable2FA = (token: string): Promise<void> =>
  request<void>("/auth/2fa/disable", {
    method: "POST",
    body: JSON.stringify({ token }),
  });