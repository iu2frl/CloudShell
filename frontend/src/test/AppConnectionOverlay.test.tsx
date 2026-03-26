import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockFns = vi.hoisted(() => ({
  mockIsLoggedIn: vi.fn(),
  mockGetTokenExpiry: vi.fn(),
  mockRefreshToken: vi.fn(),
  mockGetMe: vi.fn(),
}));

vi.mock('../api/client', () => ({
  isLoggedIn: mockFns.mockIsLoggedIn,
  getTokenExpiry: mockFns.mockGetTokenExpiry,
  refreshToken: mockFns.mockRefreshToken,
  getMe: mockFns.mockGetMe,
}));

vi.mock('../pages/Login', () => ({
  Login: ({ onLogin }: { onLogin: () => void }) => (
    <div>
      <span>LOGIN_PAGE</span>
      <button onClick={onLogin}>login</button>
    </div>
  ),
}));

vi.mock('../pages/Dashboard', () => ({
  Dashboard: ({ onLogout }: { onLogout: () => void }) => (
    <div>
      <span>DASHBOARD_PAGE</span>
      <button onClick={onLogout}>logout</button>
    </div>
  ),
}));

import App from '../App';

describe('App connection overlay and session recovery', () => {
  beforeEach(() => {
    mockFns.mockIsLoggedIn.mockReturnValue(true);
    mockFns.mockGetTokenExpiry.mockReturnValue(new Date(Date.now() + 60 * 60 * 1000));
    mockFns.mockRefreshToken.mockResolvedValue(undefined);
    mockFns.mockGetMe.mockResolvedValue({ username: 'admin', expires_at: new Date().toISOString() });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows connection-lost overlay when backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

    render(<App />);

    expect(await screen.findByText('Connection lost')).toBeInTheDocument();
    expect(screen.getByText(/Cannot reach the CloudShell backend/i)).toBeInTheDocument();
  });

  it('recovers session after reconnection and keeps dashboard', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ ok: true } as Response);
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByText('Connection lost')).toBeInTheDocument();

    window.dispatchEvent(new Event('online'));

    await waitFor(() => {
      expect(mockFns.mockRefreshToken).toHaveBeenCalled();
      expect(mockFns.mockGetMe).toHaveBeenCalled();
    });

    expect(screen.getByText('DASHBOARD_PAGE')).toBeInTheDocument();
  });

  it('goes back to login if session recovery fails', async () => {
    mockFns.mockGetMe.mockRejectedValue(new Error('session invalid'));

    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ ok: true } as Response);
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByText('Connection lost')).toBeInTheDocument();

    window.dispatchEvent(new Event('online'));

    await waitFor(() => {
      expect(mockFns.mockRefreshToken).toHaveBeenCalled();
      expect(mockFns.mockGetMe).toHaveBeenCalled();
      expect(screen.getByText('LOGIN_PAGE')).toBeInTheDocument();
    });
  });
});
