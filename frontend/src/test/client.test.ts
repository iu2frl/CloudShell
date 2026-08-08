/**
 * tests for api/client.ts — pure client-side logic only.
 *
 * Covers:
 * - getTokenExpiry: returns null when no token stored
 * - getTokenExpiry: decodes a real JWT-shaped token and returns a Date
 * - getTokenExpiry: returns null for a malformed token
 * - isLoggedIn: false when no token
 * - isLoggedIn: false when token is expired
 * - isLoggedIn: true when token is valid and not yet expired
 * - terminalWsUrl: uses ws:// on http:
 * - terminalWsUrl: uses wss:// on https:
 * - terminalWsUrl: embeds session id and short-lived ticket in the URL
 * - request: throws "Session expired" on 401 and fires cloudshell:session-expired
 * - request: throws parsed detail message on non-ok response
 * - request: returns undefined on 204
 * - request: returns parsed JSON on 200
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  getTokenExpiry,
  isLoggedIn,
  terminalWsUrl,
} from '../api/client';

// -- Helpers -------------------------------------------------------------------

// -- getTokenExpiry ------------------------------------------------------------

describe('getTokenExpiry', () => {
  beforeEach(() => sessionStorage.clear());

  it('returns null when no token is stored', () => {
    expect(getTokenExpiry()).toBeNull();
  });

  it('returns a Date matching the exp claim', () => {
    const expSec = Math.floor(Date.now() / 1000) + 3600;
    const expMs = expSec * 1000;
    sessionStorage.setItem('cloudshell_token_expiry', expMs.toString());
    const result = getTokenExpiry();
    expect(result).toBeInstanceOf(Date);
    expect(result!.getTime()).toBe(expMs);
  });

  it('returns null for a malformed expiry timestamp', () => {
    sessionStorage.setItem('cloudshell_token_expiry', 'notanumber');
    expect(getTokenExpiry()).toBeNull();
  });

  it('returns null for a non-numeric expiry', () => {
    sessionStorage.setItem('cloudshell_token_expiry', '');
    expect(getTokenExpiry()).toBeNull();
  });

  it('returns null when expiry key is missing', () => {
    sessionStorage.clear();
    expect(getTokenExpiry()).toBeNull();
  });
});

// -- isLoggedIn ----------------------------------------------------------------

describe('isLoggedIn', () => {
  beforeEach(() => sessionStorage.clear());

  it('returns false when no token is stored', () => {
    expect(isLoggedIn()).toBe(false);
  });

  it('returns false when the token is expired', () => {
    const expSec = Math.floor(Date.now() / 1000) - 60; // expired 1 min ago
    const expMs = expSec * 1000;
    sessionStorage.setItem('cloudshell_token_expiry', expMs.toString());
    expect(isLoggedIn()).toBe(false);
  });

  it('returns true when the token is valid and not expired', () => {
    const expSec = Math.floor(Date.now() / 1000) + 3600; // expires in 1 hour
    const expMs = expSec * 1000;
    sessionStorage.setItem('cloudshell_token_expiry', expMs.toString());
    expect(isLoggedIn()).toBe(true);
  });
});

// -- terminalWsUrl -------------------------------------------------------------

describe('terminalWsUrl', () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', { value: originalLocation, writable: true });
    sessionStorage.clear();
  });

  function mockProtocol(protocol: 'http:' | 'https:') {
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { protocol, host: 'localhost:8080' },
    });
  }

  it('uses ws:// when the page is served over http', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('sess-1', 'ticket')).toMatch(/^ws:\/\//);
  });

  it('uses wss:// when the page is served over https', () => {
    mockProtocol('https:');
    expect(terminalWsUrl('sess-1', 'ticket')).toMatch(/^wss:\/\//);
  });

  it('embeds the session id in the URL path', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('my-session-id', 'ticket-123')).toContain('/my-session-id');
  });

  it('appends the provided ticket as a query parameter', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('s', 'ticket-abc')).toContain('ticket=ticket-abc');
  });

  it('URL-encodes the ticket query parameter', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('s', 'a b/c?d')).toContain('ticket=a%20b%2Fc%3Fd');
  });
});

// -- request (via global fetch mock) ------------------------------------------

describe('request (via login helper)', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it('stores the token expiry in sessionStorage on successful login', async () => {
    const { login } = await import('../api/client');
    const futureDate = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ access_token: 'tok-abc', expires_at: futureDate }),
    }));
    await login('admin', 'admin');
    const stored = sessionStorage.getItem('cloudshell_token_expiry');
    expect(stored).toBeTruthy();
    expect(isLoggedIn()).toBe(true);
  });

  it('throws "Invalid credentials" on non-ok login response', async () => {
    const { login } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    }));
    await expect(login('admin', 'wrong')).rejects.toThrow('Invalid credentials');
  });

  it('sends remember_device=true when rememberDevice is selected', async () => {
    const { login } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ access_token: 'tok-remember' }),
    }));

    await login('admin', 'admin', '123456', true);

    const [, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = (opts as RequestInit).body as URLSearchParams;
    expect(body.get('remember_device')).toBe('true');
  });

  it('fires cloudshell:session-expired event on 401 from request()', async () => {
    const { listDevices } = await import('../api/client');
    // Put an expiry so getTokenExpiry() has something
    sessionStorage.setItem('cloudshell_token_expiry', Date.now().toString());
    const events: string[] = [];
    window.addEventListener('cloudshell:session-expired', () => events.push('fired'));

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Unauthorized' }),
    }));

    await expect(listDevices()).rejects.toThrow('Session expired');
    expect(events).toContain('fired');
    expect(sessionStorage.getItem('cloudshell_token_expiry')).toBeNull();
  });

  it('throws the detail message from the error JSON body', async () => {
    const { listDevices } = await import('../api/client');
    sessionStorage.setItem('cloudshell_token_expiry', (Date.now() + 3600000).toString());
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: 'Validation error' }),
    }));
    await expect(listDevices()).rejects.toThrow('Validation error');
  });
});

// -- SSH / SFTP host trust challenge API functions ----------------------------

describe('SSH host trust challenge API functions', () => {
  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.setItem('cloudshell_token_expiry', (Date.now() + 3600000).toString());
    vi.restoreAllMocks();
  });

  afterEach(() => vi.restoreAllMocks());

  it('openSession appends trust_host=true when requested', async () => {
    const { openSession } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ session_id: 'ssh-sess-1' }),
    }));

    const id = await openSession(7, { trustHost: true });
    expect(id).toBe('ssh-sess-1');
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain('/terminal/session/7?trust_host=true');
  });

  it('openSftpSession appends trust_host=true when requested', async () => {
    const { openSftpSession } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ session_id: 'sftp-sess-1' }),
    }));

    const id = await openSftpSession(9, { trustHost: true });
    expect(id).toBe('sftp-sess-1');
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain('/sftp/session/9?trust_host=true');
  });

  it('createTerminalWsTicket returns ticket payload', async () => {
    const { createTerminalWsTicket } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ticket: 'ws-ticket-1', expires_in: 30 }),
    }));

    const data = await createTerminalWsTicket('sess-123');
    expect(data.ticket).toBe('ws-ticket-1');
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain('/terminal/ws-ticket/sess-123');
  });

  it('openSession throws SshHostChallengeError on 409 challenge', async () => {
    const { openSession, SshHostChallengeError } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: { code: 'SSH_HOST_UNTRUSTED', fingerprint: 'AA:BB' } }),
    }));

    await expect(openSession(11)).rejects.toBeInstanceOf(SshHostChallengeError);
  });

  it('openSftpSession throws SshHostChallengeError on 409 challenge', async () => {
    const { openSftpSession, SshHostChallengeError } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: { code: 'SSH_HOST_CHANGED', fingerprint: 'AA:BB', previous_fingerprint: 'CC:DD' } }),
    }));

    await expect(openSftpSession(12)).rejects.toBeInstanceOf(SshHostChallengeError);
  });
});

// -- FTP / FTPS API functions --------------------------------------------------

describe('FTP API functions', () => {
  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.setItem('cloudshell_token_expiry', (Date.now() + 3600000).toString());
    vi.restoreAllMocks();
  });

  afterEach(() => vi.restoreAllMocks());

  function mockFetch(body: unknown, status = 200) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      blob: async () => new Blob(['data']),
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="test.txt"' }),
    }));
  }

  it('openFtpSession returns session_id', async () => {
    const { openFtpSession } = await import('../api/client');
    mockFetch({ session_id: 'ftp-sess-1' });
    const id = await openFtpSession(42);
    expect(id).toBe('ftp-sess-1');
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain('/ftp/session/42');
  });

  it('openFtpSession appends trust_cert=true when requested', async () => {
    const { openFtpSession } = await import('../api/client');
    mockFetch({ session_id: 'ftp-sess-2' });
    const id = await openFtpSession(42, { trustCert: true });
    expect(id).toBe('ftp-sess-2');
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain('/ftp/session/42?trust_cert=true');
  });

  it('openFtpSession throws FtpsCertificateChallengeError on 409 challenge', async () => {
    const { openFtpSession, FtpsCertificateChallengeError } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: { code: 'FTPS_CERT_UNTRUSTED', thumbprint: 'AA:BB' } }),
    }));
    await expect(openFtpSession(42)).rejects.toBeInstanceOf(FtpsCertificateChallengeError);
  });

  it('closeFtpSession calls DELETE on the session endpoint', async () => {
    const { closeFtpSession } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => undefined,
    }));
    await closeFtpSession('sess-abc');
    const [url, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/ftp/session/sess-abc');
    expect((opts as RequestInit).method).toBe('DELETE');
  });

  it('ftpList encodes the path and returns entries', async () => {
    const { ftpList } = await import('../api/client');
    mockFetch({ path: '/some dir', entries: [] });
    const res = await ftpList('sess-1', '/some dir');
    expect(res.path).toBe('/some dir');
    const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain(encodeURIComponent('/some dir'));
  });

  it('ftpDownload triggers a file download on success', async () => {
    const { ftpDownload } = await import('../api/client');
    // Spy on anchor click behavior
    const clickSpy = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreate(tag);
      if (tag === 'a') {
        Object.defineProperty(el, 'click', { value: clickSpy });
      }
      return el;
    });
    mockFetch({ /* blob stream */ });
    await ftpDownload('sess-1', '/test.txt');
    expect(clickSpy).toHaveBeenCalled();
  });

  it('ftpDownload throws on non-ok response', async () => {
    const { ftpDownload } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'File not found' }),
      headers: new Headers(),
    }));
    await expect(ftpDownload('sess-1', '/missing.txt')).rejects.toThrow('File not found');
  });

  it('ftpDelete sends a POST with path and is_dir', async () => {
    const { ftpDelete } = await import('../api/client');
    mockFetch({});
    await ftpDelete('sess-1', '/old.txt', false);
    const [url, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/ftp/sess-1/delete');
    const body = JSON.parse((opts as RequestInit).body as string);
    expect(body).toEqual({ path: '/old.txt', is_dir: false });
  });

  it('ftpRename sends a POST with old_path and new_path', async () => {
    const { ftpRename } = await import('../api/client');
    mockFetch({});
    await ftpRename('sess-1', '/old.txt', '/new.txt');
    const [url, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/ftp/sess-1/rename');
    const body = JSON.parse((opts as RequestInit).body as string);
    expect(body).toEqual({ old_path: '/old.txt', new_path: '/new.txt' });
  });

  it('ftpMkdir sends a POST with path', async () => {
    const { ftpMkdir } = await import('../api/client');
    mockFetch({});
    await ftpMkdir('sess-1', '/newdir');
    const [url, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/ftp/sess-1/mkdir');
    const body = JSON.parse((opts as RequestInit).body as string);
    expect(body).toEqual({ path: '/newdir' });
  });

  it('ftpUpload resolves on XHR 200', async () => {
    const { ftpUpload } = await import('../api/client');
    const xhrMock = {
      open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown, onerror: null as unknown,
      status: 200, responseText: '{}',
    };
    class FakeXHR { constructor() { return xhrMock as unknown as FakeXHR; } }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const file = new File(['content'], 'file.txt');
    const promise = ftpUpload('sess-1', '/uploads', file);
    (xhrMock.onload as () => void)();
    await expect(promise).resolves.toBeUndefined();
  });

  it('ftpUpload rejects with error detail on XHR failure', async () => {
    const { ftpUpload } = await import('../api/client');
    const xhrMock = {
      open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown, onerror: null as unknown,
      status: 500, responseText: '{"detail":"Upload failed"}',
    };
    class FakeXHR { constructor() { return xhrMock as unknown as FakeXHR; } }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const file = new File(['content'], 'file.txt');
    const promise = ftpUpload('sess-1', '/uploads', file);
    (xhrMock.onload as () => void)();
    await expect(promise).rejects.toThrow('Upload failed');
  });

  it('ftpUpload rejects on network error', async () => {
    const { ftpUpload } = await import('../api/client');
    const xhrMock = {
      open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown, onerror: null as unknown,
      status: 0, responseText: '',
    };
    class FakeXHR { constructor() { return xhrMock as unknown as FakeXHR; } }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const file = new File(['content'], 'file.txt');
    const promise = ftpUpload('sess-1', '/uploads', file);
    (xhrMock.onerror as () => void)();
    await expect(promise).rejects.toThrow('Network error during upload');
  });

  it('ftpUpload calls onProgress callback', async () => {
    const { ftpUpload } = await import('../api/client');
    const xhrMock = {
      open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown, onerror: null as unknown,
      status: 200, responseText: '{}',
    };
    class FakeXHR { constructor() { return xhrMock as unknown as FakeXHR; } }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const onProgress = vi.fn();
    const file = new File(['content'], 'file.txt');
    const promise = ftpUpload('sess-1', '/uploads', file, onProgress);
    (xhrMock.upload.onprogress as (e: ProgressEvent) => void)(
      { lengthComputable: true, loaded: 50, total: 100 } as ProgressEvent,
    );
    (xhrMock.onload as () => void)();
    await promise;
    expect(onProgress).toHaveBeenCalledWith(25);
  });
});

describe('client additional coverage', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('getTokenExpiry returns null when storage throws', () => {
    const getItemSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });
    expect(getTokenExpiry()).toBeNull();
    getItemSpy.mockRestore();
  });

  it('login throws 2FA_REQUIRED for 403 challenge', async () => {
    const { login } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: '2FA_REQUIRED' }),
    }));
    await expect(login('admin', 'pw')).rejects.toThrow('2FA_REQUIRED');
  });

  it('login throws Invalid 2FA code for 401 challenge', async () => {
    const { login } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Invalid 2FA code' }),
    }));
    await expect(login('admin', 'pw', '000000')).rejects.toThrow('Invalid 2FA code');
  });

  it('logout clears token even if API fails', async () => {
    const { logout } = await import('../api/client');
    sessionStorage.setItem('cloudshell_token_expiry', (Date.now() + 60000).toString());
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Error',
      json: async () => ({ detail: 'boom' }),
    }));
    await logout();
    expect(sessionStorage.getItem('cloudshell_token_expiry')).toBeNull();
  });

  it('refreshToken logs out when refresh fails', async () => {
    const { refreshToken } = await import('../api/client');
    sessionStorage.setItem('cloudshell_token_expiry', (Date.now() + 60000).toString());
    const events: string[] = [];
    window.addEventListener('cloudshell:session-expired', () => events.push('fired'));

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'expired' }),
    }));

    await refreshToken();
    expect(events).toContain('fired');
    expect(sessionStorage.getItem('cloudshell_token_expiry')).toBeNull();
  });

  it('refreshToken stores updated expiry on success', async () => {
    const { refreshToken } = await import('../api/client');
    const futureDate = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ expires_at: futureDate }),
    }));
    await refreshToken();
    expect(getTokenExpiry()).toBeInstanceOf(Date);
  });

  it('changePassword posts expected payload', async () => {
    const { changePassword } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => undefined,
    }));

    await changePassword('old', 'new');

    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/auth/change-password');
    const body = JSON.parse((options as RequestInit).body as string);
    expect(body).toEqual({ current_password: 'old', new_password: 'new' });
  });

  it('covers basic device and folder endpoint wrappers', async () => {
    const {
      listDevices,
      createDevice,
      updateDevice,
      deleteDevice,
      listFolders,
      getFolder,
      createFolder,
      updateFolder,
      deleteFolder,
      getMe,
      listAuditLogs,
      generateKeyPair,
    } = await import('../api/client');

    const responses = [
      { ok: true, status: 200, json: async () => [] },
      { ok: true, status: 200, json: async () => ({ id: 1 }) },
      { ok: true, status: 200, json: async () => ({ id: 1 }) },
      { ok: true, status: 204, json: async () => undefined },
      { ok: true, status: 200, json: async () => [] },
      { ok: true, status: 200, json: async () => ({ id: 7, children: [], device_count: 0 }) },
      { ok: true, status: 200, json: async () => ({ id: 8 }) },
      { ok: true, status: 200, json: async () => ({ id: 8 }) },
      { ok: true, status: 204, json: async () => undefined },
      { ok: true, status: 200, json: async () => ({ username: 'u', expires_at: 'x' }) },
      { ok: true, status: 200, json: async () => ({ total: 0, page: 1, page_size: 50, entries: [] }) },
      { ok: true, status: 200, json: async () => ({ private_key: 'a', public_key: 'b' }) },
    ];

    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(responses.shift())));

    await listDevices();
    await createDevice({ name: 'n', hostname: 'h', port: 22, username: 'u', auth_type: 'password', connection_type: 'ssh', password: 'p' });
    await updateDevice(1, { name: 'x' });
    await deleteDevice(1);
    await listFolders();
    await getFolder(7);
    await createFolder({ name: 'f' });
    await updateFolder(8, { description: 'd' });
    await deleteFolder(8);
    await getMe();
    await listAuditLogs();
    await generateKeyPair();

    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(12);
  });

  it('covers SFTP wrappers and download fallback filename', async () => {
    const { closeSftpSession, sftpList, sftpDownload, sftpDelete, sftpRename, sftpMkdir } = await import('../api/client');

    const clickSpy = vi.fn();
    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = originalCreate(tag);
      if (tag === 'a') {
        Object.defineProperty(el, 'click', { value: clickSpy });
      }
      return el;
    });
    const objectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    const responses = [
      { ok: true, status: 204, json: async () => undefined },
      { ok: true, status: 200, json: async () => ({ path: '/', entries: [] }) },
      {
        ok: true,
        status: 200,
        headers: new Headers(),
        blob: async () => new Blob(['abc']),
      },
      { ok: true, status: 204, json: async () => undefined },
      { ok: true, status: 204, json: async () => undefined },
      { ok: true, status: 204, json: async () => undefined },
    ];

    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(responses.shift())));

    await closeSftpSession('s1');
    await sftpList('s1', '/');
    await sftpDownload('s1', '/folder/file.txt');
    await sftpDelete('s1', '/old.txt', false);
    await sftpRename('s1', '/a', '/b');
    await sftpMkdir('s1', '/new');

    expect(clickSpy).toHaveBeenCalled();
    expect(objectUrlSpy).toHaveBeenCalled();
    expect(revokeSpy).toHaveBeenCalled();
  });

  it('sftpDownload throws session expired on 401', async () => {
    const { sftpDownload } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'unauthorized' }),
      headers: new Headers(),
    }));
    await expect(sftpDownload('sess', '/x')).rejects.toThrow('Session expired');
  });

  it('sftpUpload handles 401, parse error, and network error', async () => {
    const { sftpUpload } = await import('../api/client');

    const base = {
      open: vi.fn(),
      setRequestHeader: vi.fn(),
      send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown,
      onerror: null as unknown,
      status: 0,
      responseText: '',
    };

    const runCase = async (status: number, responseText: string, event: 'load' | 'error') => {
      const xhrMock = { ...base, status, responseText, onload: null as unknown, onerror: null as unknown };
      class FakeXHR {
        constructor() {
          return xhrMock as unknown as FakeXHR;
        }
      }
      vi.stubGlobal('XMLHttpRequest', FakeXHR);
      const file = new File(['x'], 'x.txt');
      const p = sftpUpload('sess', '/up', file);
      if (event === 'load') {
        (xhrMock.onload as () => void)();
      } else {
        (xhrMock.onerror as () => void)();
      }
      return p;
    };

    await expect(runCase(401, '{}', 'load')).rejects.toThrow('Session expired');
    await expect(runCase(500, '{bad-json', 'load')).rejects.toThrow('Upload failed');
    await expect(runCase(0, '', 'error')).rejects.toThrow('Network error during upload');
  });

  it('ftpDownload throws session expired on 401', async () => {
    const { ftpDownload } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'unauthorized' }),
      headers: new Headers(),
    }));
    await expect(ftpDownload('sess', '/x')).rejects.toThrow('Session expired');
  });

  it('openSession and openSftpSession surface non-challenge object detail', async () => {
    const { openSession, openSftpSession } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: { code: 'SSH_HOST_UNTRUSTED' } }) })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: { code: 'SSH_HOST_CHANGED' } }) }));

    await expect(openSession(1)).rejects.toThrow('[object Object]');
    await expect(openSftpSession(2)).rejects.toThrow('[object Object]');
  });

  it('exportConfig and importConfig cover success and errors', async () => {
    const { exportConfig, importConfig } = await import('../api/client');

    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        blob: async () => new Blob(['cfg']),
        json: async () => ({}),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 1, skipped: 0, errors: 0, messages: [] }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ detail: 'expired' }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        json: async () => ({ detail: 'Import failed hard' }),
      }));

    const blob = await exportConfig();
    expect(blob).toBeInstanceOf(Blob);

    const result = await importConfig(new File(['{}'], 'config.json'));
    expect(result.imported).toBe(1);

    await expect(exportConfig()).rejects.toThrow('Session expired');
    await expect(importConfig(new File(['{}'], 'bad.json'))).rejects.toThrow('Import failed hard');
  });

  it('2FA endpoints call expected routes', async () => {
    const { get2FAStatus, setup2FA, enable2FA, disable2FA } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ enabled: true }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ qr_code: 'qr', backup_codes: ['a'] }) })
      .mockResolvedValueOnce({ ok: true, status: 204, json: async () => undefined })
      .mockResolvedValueOnce({ ok: true, status: 204, json: async () => undefined }));

    const status = await get2FAStatus();
    expect(status.enabled).toBe(true);
    const setup = await setup2FA();
    expect(setup.qr_code).toBe('qr');
    await enable2FA('111111');
    await disable2FA('111111');

    const urls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(urls.some((u) => u.includes('/auth/2fa/status'))).toBe(true);
    expect(urls.some((u) => u.includes('/auth/2fa/setup'))).toBe(true);
    expect(urls.some((u) => u.includes('/auth/2fa/enable'))).toBe(true);
    expect(urls.some((u) => u.includes('/auth/2fa/disable'))).toBe(true);
  });

  it('exportConfig and importConfig use statusText fallback when error JSON parse fails', async () => {
    const { exportConfig, importConfig } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Export Status Text',
        json: async () => {
          throw new Error('bad json');
        },
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Import Status Text',
        json: async () => {
          throw new Error('bad json');
        },
      }));

    await expect(exportConfig()).rejects.toThrow('Export Status Text');
    await expect(importConfig(new File(['{}'], 'bad.json'))).rejects.toThrow('Import Status Text');
  });

  it('ftpDelete handles 401, non-ok, no delete_id, 404 poll, and failed poll branches', async () => {
    const { ftpDelete } = await import('../api/client');

    // 401
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
      status: 401,
      ok: false,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'unauthorized' }),
    }));
    await expect(ftpDelete('s', '/a', false)).rejects.toThrow('Session expired');

    // non-ok + detail
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
      status: 500,
      ok: false,
      statusText: 'Server Error',
      json: async () => ({ detail: 'Delete exploded' }),
    }));
    await expect(ftpDelete('s', '/a', false)).rejects.toThrow('Delete exploded');

    // non-ok + fallback detail
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
      status: 500,
      ok: false,
      statusText: 'Delete Status Text',
      json: async () => {
        throw new Error('bad');
      },
    }));
    await expect(ftpDelete('s', '/a', false)).rejects.toThrow('Delete Status Text');

    // no delete_id returns
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
      status: 200,
      ok: true,
      json: async () => ({}),
    }));
    await expect(ftpDelete('s', '/a', true)).resolves.toBeUndefined();

    // poll 404 returns
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ delete_id: 'd1' }) })
      .mockResolvedValueOnce({ status: 404, ok: false, json: async () => ({}) }));
    const p404 = ftpDelete('s', '/a', true);
    await vi.advanceTimersByTimeAsync(500);
    await expect(p404).resolves.toBeUndefined();
    vi.useRealTimers();

    // poll failed branch (no explicit error uses terminal default message)
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ delete_id: 'd2' }) })
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ status: 'failed' }) }));
    const pFailed = ftpDelete('s', '/a', true);
    const failedExpectation = expect(pFailed).rejects.toThrow('Delete failed on server');
    await vi.advanceTimersByTimeAsync(500);
    await failedExpectation;
    vi.useRealTimers();
  });

  it('ftpDelete polling supports progress callback and completion', async () => {
    const { ftpDelete } = await import('../api/client');
    const progress = vi.fn();
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ delete_id: 'd3' }) })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: async () => ({ status: 'completed', deleted_items: 7 }),
      }));

    const p = ftpDelete('s', '/a', true, progress);
    await vi.advanceTimersByTimeAsync(500);
    await expect(p).resolves.toBeUndefined();
    expect(progress).toHaveBeenCalledWith(7);
    vi.useRealTimers();
  });

  it('ftpUpload covers polling completed, failed, 404, poll error, parse error and 401 branches', async () => {
    const { ftpUpload } = await import('../api/client');
    const file = new File(['content'], 'file.txt');

    const makeXhr = (status: number, responseText: string) => {
      const xhrMock = {
        open: vi.fn(),
        setRequestHeader: vi.fn(),
        send: vi.fn(),
        upload: { onprogress: null as unknown },
        onload: null as unknown,
        onerror: null as unknown,
        status,
        responseText,
      };
      class FakeXHR {
        constructor() {
          return xhrMock as unknown as FakeXHR;
        }
      }
      vi.stubGlobal('XMLHttpRequest', FakeXHR);
      return xhrMock;
    };

    // completed polling path
    {
      const onProgress = vi.fn();
      const xhr = makeXhr(200, JSON.stringify({ upload_id: 'u1' }));
      vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'completed', percent: 50 }),
      }));
      const p = ftpUpload('s', '/p', file, onProgress);
      (xhr.onload as () => void)();
      await expect(p).resolves.toBeUndefined();
      expect(onProgress).toHaveBeenCalledWith(75);
      expect(onProgress).toHaveBeenCalledWith(100);
    }

    // failed polling path
    {
      const xhr = makeXhr(200, JSON.stringify({ upload_id: 'u2' }));
      vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'failed', error: 'server upload failed' }),
      }));
      const p = ftpUpload('s', '/p', file, vi.fn());
      (xhr.onload as () => void)();
      await expect(p).rejects.toThrow('server upload failed');
    }

    // 404 status polling resolves
    {
      const xhr = makeXhr(200, JSON.stringify({ upload_id: 'u3' }));
      vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({}),
      }));
      const p = ftpUpload('s', '/p', file, vi.fn());
      (xhr.onload as () => void)();
      await expect(p).resolves.toBeUndefined();
    }

    // polling fetch throws and resolves
    {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const xhr = makeXhr(200, JSON.stringify({ upload_id: 'u4' }));
      vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('poll exploded')));
      const p = ftpUpload('s', '/p', file, vi.fn());
      (xhr.onload as () => void)();
      await expect(p).resolves.toBeUndefined();
      expect(warnSpy).toHaveBeenCalled();
      warnSpy.mockRestore();
    }

    // parse error branch
    {
      const xhr = makeXhr(200, '{bad-json');
      const p = ftpUpload('s', '/p', file, vi.fn());
      (xhr.onload as () => void)();
      await expect(p).rejects.toThrow('Failed to parse upload response');
    }

    // xhr 401 branch
    {
      const xhr = makeXhr(401, '{}');
      const p = ftpUpload('s', '/p', file, vi.fn());
      (xhr.onload as () => void)();
      await expect(p).rejects.toThrow('Session expired');
    }

    // xhr non-401 parse fallback branch
    {
      const xhr = makeXhr(500, '{broken-json');
      const p = ftpUpload('s', '/p', file, vi.fn());
      (xhr.onload as () => void)();
      await expect(p).rejects.toThrow('Upload failed');
    }
  });

  it('openSession/openSftpSession use statusText fallback when response json parsing fails', async () => {
    const { openSession, openSftpSession } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'terminal status text',
        json: async () => {
          throw new Error('bad json');
        },
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'sftp status text',
        json: async () => {
          throw new Error('bad json');
        },
      }));

    await expect(openSession(1)).rejects.toThrow('terminal status text');
    await expect(openSftpSession(2)).rejects.toThrow('sftp status text');
  });

  it('openFtpSession handles 401 and generic non-ok error', async () => {
    const { openFtpSession } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ detail: 'unauthorized' }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        json: async () => ({ detail: 'FTP failed generic' }),
      }));

    await expect(openFtpSession(7)).rejects.toThrow('Session expired');
    await expect(openFtpSession(7)).rejects.toThrow('FTP failed generic');
  });

  it('sftpDownload falls back to basename when content-disposition filename is absent', async () => {
    const { sftpDownload } = await import('../api/client');
    const clickSpy = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreate(tag);
      if (tag === 'a') {
        Object.defineProperty(el, 'click', { value: clickSpy });
      }
      return el;
    });
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:sftp');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      blob: async () => new Blob(['x']),
    }));

    await sftpDownload('s', '/deep/path/name.txt');
    expect(clickSpy).toHaveBeenCalled();
  });

  it('sftpUpload reports progress when length is computable', async () => {
    const { sftpUpload } = await import('../api/client');
    const progress = vi.fn();
    const xhrMock = {
      open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown, onerror: null as unknown,
      status: 200, responseText: '{}',
    };
    class FakeXHR {
      constructor() {
        return xhrMock as unknown as FakeXHR;
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const p = sftpUpload('s', '/r', new File(['x'], 'x.txt'), progress);
    (xhrMock.upload.onprogress as (e: ProgressEvent) => void)(
      { lengthComputable: true, loaded: 25, total: 100 } as ProgressEvent,
    );
    (xhrMock.onload as () => void)();
    await expect(p).resolves.toBeUndefined();
    expect(progress).toHaveBeenCalledWith(25);
  });

  it('ftpUpload polling covers loop increment and timeout branch', async () => {
    const { ftpUpload } = await import('../api/client');
    const file = new File(['content'], 'file.txt');

    const xhrMock = {
      open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
      upload: { onprogress: null as unknown },
      onload: null as unknown, onerror: null as unknown,
      status: 200, responseText: JSON.stringify({ upload_id: 'u-timeout' }),
    };
    class FakeXHR {
      constructor() {
        return xhrMock as unknown as FakeXHR;
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);

    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'running' }),
    }));

    const p = ftpUpload('s', '/p', file, vi.fn());
    const timeoutExpectation = expect(p).rejects.toThrow('Upload progress polling timeout');
    (xhrMock.onload as () => void)();
    await vi.advanceTimersByTimeAsync(1800 * 1000);
    await timeoutExpectation;
    vi.useRealTimers();
  });

  it('ftpDelete polling continues after transient error and can timeout', async () => {
    const { ftpDelete } = await import('../api/client');

    // Transient poll error then completed
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ delete_id: 'd-transient' }) })
      .mockRejectedValueOnce(new Error('temporary poll error'))
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ status: 'completed' }) }));
    const transient = ftpDelete('s', '/a', true);
    await vi.advanceTimersByTimeAsync(1000);
    await expect(transient).resolves.toBeUndefined();
    vi.useRealTimers();

    // Timeout branch
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ delete_id: 'd-timeout' }) })
      .mockResolvedValue({ status: 200, ok: true, json: async () => ({ status: 'running' }) }));
    const timeout = ftpDelete('s', '/a', true);
    const timeoutExpectation = expect(timeout).rejects.toThrow('Delete progress polling timeout');
    await vi.advanceTimersByTimeAsync(1800 * 500);
    await timeoutExpectation;
    vi.useRealTimers();
  });
});
