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
 * - terminalWsUrl: embeds session id and token in the URL
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

/** Build a minimal JWT with the given exp (unix seconds). */
function makeToken(exp: number): string {
  const header  = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(JSON.stringify({ sub: 'admin', exp }));
  return `${header}.${payload}.fakesig`;
}

// -- getTokenExpiry ------------------------------------------------------------

describe('getTokenExpiry', () => {
  beforeEach(() => localStorage.clear());

  it('returns null when no token is stored', () => {
    expect(getTokenExpiry()).toBeNull();
  });

  it('returns a Date matching the exp claim', () => {
    const expSec = Math.floor(Date.now() / 1000) + 3600;
    localStorage.setItem('token', makeToken(expSec));
    const result = getTokenExpiry();
    expect(result).toBeInstanceOf(Date);
    expect(result!.getTime()).toBe(expSec * 1000);
  });

  it('returns null for a token with no dots (malformed)', () => {
    localStorage.setItem('token', 'notavalidjwt');
    expect(getTokenExpiry()).toBeNull();
  });

  it('returns null for a token whose payload is not valid base64 JSON', () => {
    localStorage.setItem('token', 'header.!!invalid!!.sig');
    expect(getTokenExpiry()).toBeNull();
  });

  it('returns null when payload has no exp field', () => {
    const payload = btoa(JSON.stringify({ sub: 'admin' })); // no exp
    localStorage.setItem('token', `header.${payload}.sig`);
    expect(getTokenExpiry()).toBeNull();
  });
});

// -- isLoggedIn ----------------------------------------------------------------

describe('isLoggedIn', () => {
  beforeEach(() => localStorage.clear());

  it('returns false when no token is stored', () => {
    expect(isLoggedIn()).toBe(false);
  });

  it('returns false when the token is expired', () => {
    const expSec = Math.floor(Date.now() / 1000) - 60; // expired 1 min ago
    localStorage.setItem('token', makeToken(expSec));
    expect(isLoggedIn()).toBe(false);
  });

  it('returns true when the token is valid and not expired', () => {
    const expSec = Math.floor(Date.now() / 1000) + 3600; // expires in 1 hour
    localStorage.setItem('token', makeToken(expSec));
    expect(isLoggedIn()).toBe(true);
  });
});

// -- terminalWsUrl -------------------------------------------------------------

describe('terminalWsUrl', () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', { value: originalLocation, writable: true });
    localStorage.clear();
  });

  function mockProtocol(protocol: 'http:' | 'https:') {
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { protocol, host: 'localhost:8080' },
    });
  }

  it('uses ws:// when the page is served over http', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('sess-1')).toMatch(/^ws:\/\//);
  });

  it('uses wss:// when the page is served over https', () => {
    mockProtocol('https:');
    expect(terminalWsUrl('sess-1')).toMatch(/^wss:\/\//);
  });

  it('embeds the session id in the URL path', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('my-session-id')).toContain('/my-session-id');
  });

  it('appends the stored token as a query parameter', () => {
    mockProtocol('http:');
    localStorage.setItem('token', 'testtoken123');
    expect(terminalWsUrl('s')).toContain('token=testtoken123');
  });

  it('uses an empty token when none is stored', () => {
    mockProtocol('http:');
    expect(terminalWsUrl('s')).toContain('token=');
  });
});

// -- request (via global fetch mock) ------------------------------------------

describe('request (via login helper)', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it('stores the access_token in localStorage on successful login', async () => {
    const { login } = await import('../api/client');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ access_token: 'tok-abc' }),
    }));
    await login('admin', 'admin');
    expect(localStorage.getItem('token')).toBe('tok-abc');
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
    // Put a token so authHeaders() has something
    localStorage.setItem('token', 'expired-token');
    const events: string[] = [];
    window.addEventListener('cloudshell:session-expired', () => events.push('fired'));

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Unauthorized' }),
    }));

    await expect(listDevices()).rejects.toThrow('Session expired');
    expect(events).toContain('fired');
    expect(localStorage.getItem('token')).toBeNull();
  });

  it('throws the detail message from the error JSON body', async () => {
    const { listDevices } = await import('../api/client');
    localStorage.setItem('token', 'tok');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: 'Validation error' }),
    }));
    await expect(listDevices()).rejects.toThrow('Validation error');
  });
});

// -- FTP / FTPS API functions --------------------------------------------------

describe('FTP API functions', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('token', 'test-token');
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
    expect(onProgress).toHaveBeenCalledWith(50);
  });
});
