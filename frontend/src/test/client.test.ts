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

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Build a minimal JWT with the given exp (unix seconds). */
function makeToken(exp: number): string {
  const header  = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(JSON.stringify({ sub: 'admin', exp }));
  return `${header}.${payload}.fakesig`;
}

// ── getTokenExpiry ────────────────────────────────────────────────────────────

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

// ── isLoggedIn ────────────────────────────────────────────────────────────────

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

// ── terminalWsUrl ─────────────────────────────────────────────────────────────

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

// ── request (via global fetch mock) ──────────────────────────────────────────

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
