/**
 * Tests for the Dashboard header — portrait (mobile) layout
 *
 * The header uses flex-wrap + CSS order to reflow into two rows on small
 * screens. Because jsdom has no real CSS engine we cannot test the visual
 * reflow directly, but we CAN assert on:
 *
 * - The header element is present
 * - The logo, tab strip container, and action-icon group all exist within
 *   the header
 * - Each group carries the correct responsive Tailwind order / width classes
 *   that drive the two-row layout on mobile
 * - Open tabs appear as tab chips inside the tab-strip container
 * - Closing a tab removes it from the strip
 * - Action buttons (audit log, change password, sign out) are present in the
 *   actions group (i.e. they share row 1 with the logo on mobile)
 * - The layout picker is present inside the actions group
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Dashboard } from '../pages/Dashboard';
import { ToastProvider } from '../components/Toast';
import type { Device } from '../api/client';

// ── Mocks ─────────────────────────────────────────────────────────────────────

// Stub every heavy component / API so the test can mount Dashboard cheaply.
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    listDevices: vi.fn().mockResolvedValue([]),
    logout: vi.fn().mockResolvedValue(undefined),
    getTokenExpiry: vi.fn().mockReturnValue(new Date(Date.now() + 60 * 60 * 1000)),
  };
});

vi.mock('../components/Terminal', () => ({
  Terminal: ({ device }: { device: Device }) => (
    <div data-testid={`terminal-${device.id}`} />
  ),
}));

vi.mock('../components/FileManager', () => ({
  FileManager: ({ device }: { device: Device }) => (
    <div data-testid={`filemanager-${device.id}`} />
  ),
}));

vi.mock('../components/DeviceList', () => ({
  DeviceList: (props: { onConnect: (d: Device) => void }) => (
    <div data-testid="device-list">
      <button
        data-testid="connect-device-1"
        onClick={() =>
          props.onConnect({
            id: 1,
            name: 'Server Alpha',
            hostname: '10.0.0.1',
            port: 22,
            username: 'root',
            auth_type: 'password',
            connection_type: 'ssh',
            key_filename: null,
            created_at: '',
            updated_at: '',
          })
        }
      >
        Connect Alpha
      </button>
      <button
        data-testid="connect-device-2"
        onClick={() =>
          props.onConnect({
            id: 2,
            name: 'Server Beta',
            hostname: '10.0.0.2',
            port: 22,
            username: 'admin',
            auth_type: 'password',
            connection_type: 'ssh',
            key_filename: null,
            created_at: '',
            updated_at: '',
          })
        }
      >
        Connect Beta
      </button>
    </div>
  ),
}));

vi.mock('../components/DeviceForm',       () => ({ DeviceForm: () => null }));
vi.mock('../components/ChangePasswordModal', () => ({ ChangePasswordModal: () => null }));
vi.mock('../components/AuditLogModal',    () => ({ AuditLogModal: () => null }));

// ── Helpers ───────────────────────────────────────────────────────────────────

function setup() {
  const onLogout = vi.fn();
  render(
    <ToastProvider>
      <Dashboard onLogout={onLogout} />
    </ToastProvider>,
  );
  return { onLogout };
}

beforeEach(() => vi.clearAllMocks());

// ── Header structure ──────────────────────────────────────────────────────────

describe('Dashboard header — structure', () => {
  it('renders the <header> element', () => {
    setup();
    expect(document.querySelector('header')).toBeInTheDocument();
  });

  it('header has flex-wrap class for mobile two-row reflow', () => {
    setup();
    const header = document.querySelector('header')!;
    expect(header.className).toContain('flex-wrap');
  });

  it('header has sm:flex-nowrap class to restore single row on wider screens', () => {
    setup();
    const header = document.querySelector('header')!;
    expect(header.className).toContain('sm:flex-nowrap');
  });
});

// ── Logo group ────────────────────────────────────────────────────────────────

describe('Dashboard header — logo group', () => {
  it('is rendered inside the header', () => {
    setup();
    const header = document.querySelector('header')!;
    // The CloudShell icon and text are both inside the header
    expect(within(header).getByText('CloudShell by IU2FRL')).toBeInTheDocument();
  });

  it('logo group has order-1 so it is first in both rows', () => {
    setup();
    const header = document.querySelector('header')!;
    const logoGroup = within(header).getByText('CloudShell by IU2FRL').closest('div')!;
    expect(logoGroup.className).toContain('order-1');
  });
});

// ── Actions group (row 1 on mobile) ───────────────────────────────────────────

describe('Dashboard header — actions group', () => {
  it('contains the audit log button', () => {
    setup();
    expect(screen.getByTitle('Audit log')).toBeInTheDocument();
  });

  it('contains the change password button', () => {
    setup();
    expect(screen.getByTitle('Change password')).toBeInTheDocument();
  });

  it('contains the sign out button', () => {
    setup();
    expect(screen.getByTitle('Sign out')).toBeInTheDocument();
  });

  it('actions group has order-2 (row 1 on mobile, right-hand side)', () => {
    setup();
    const signOutBtn = screen.getByTitle('Sign out');
    const actionsGroup = signOutBtn.closest('div')!;
    expect(actionsGroup.className).toContain('order-2');
  });

  it('actions group has ml-auto to push it to the right edge on mobile', () => {
    setup();
    const signOutBtn = screen.getByTitle('Sign out');
    const actionsGroup = signOutBtn.closest('div')!;
    expect(actionsGroup.className).toContain('ml-auto');
  });

  it('actions group has sm:ml-0 to remove the auto-margin on wider screens', () => {
    setup();
    const signOutBtn = screen.getByTitle('Sign out');
    const actionsGroup = signOutBtn.closest('div')!;
    expect(actionsGroup.className).toContain('sm:ml-0');
  });
});

// ── Tab strip (row 2 on mobile) ───────────────────────────────────────────────

describe('Dashboard header — tab strip', () => {
  it('tab strip container has order-3 (second row on mobile)', async () => {
    setup();
    // Wait for the initial listDevices promise to settle
    await waitFor(() => expect(document.querySelector('[class*="order-3"]')).toBeInTheDocument());
    const tabStrip = document.querySelector('[class*="order-3"]')!;
    expect(tabStrip.className).toContain('order-3');
  });

  it('tab strip container has w-full to span the full width on mobile', async () => {
    setup();
    await waitFor(() => expect(document.querySelector('[class*="order-3"]')).toBeInTheDocument());
    const tabStrip = document.querySelector('[class*="order-3"]')!;
    expect(tabStrip.className).toContain('w-full');
  });

  it('tab strip container has sm:w-auto so it shrinks back on wider screens', async () => {
    setup();
    await waitFor(() => expect(document.querySelector('[class*="order-3"]')).toBeInTheDocument());
    const tabStrip = document.querySelector('[class*="order-3"]')!;
    expect(tabStrip.className).toContain('sm:w-auto');
  });

  it('tab strip container has sm:order-2 to restore inline position on wider screens', async () => {
    setup();
    await waitFor(() => expect(document.querySelector('[class*="order-3"]')).toBeInTheDocument());
    const tabStrip = document.querySelector('[class*="order-3"]')!;
    expect(tabStrip.className).toContain('sm:order-2');
  });

  it('tab strip is empty when no connections are open', async () => {
    setup();
    await waitFor(() => expect(document.querySelector('[class*="order-3"]')).toBeInTheDocument());
    const tabStrip = document.querySelector('[class*="order-3"]')!;
    expect(tabStrip.children).toHaveLength(0);
  });

  it('shows a tab chip when a device is connected', async () => {
    setup();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await waitFor(() => screen.getByText('Server Alpha'));
    expect(screen.getByText('Server Alpha')).toBeInTheDocument();
  });

  it('shows multiple tab chips when multiple devices are connected', async () => {
    setup();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));
    expect(screen.getByText('Server Alpha')).toBeInTheDocument();
    expect(screen.getByText('Server Beta')).toBeInTheDocument();
  });

  it('removes the tab chip when the close button is clicked', async () => {
    setup();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await waitFor(() => screen.getByText('Server Alpha'));

    // Each tab chip has a close button labelled "Close tab"
    const closeBtn = screen.getByTitle('Close tab');
    await userEvent.click(closeBtn);

    await waitFor(() =>
      expect(screen.queryByText('Server Alpha')).not.toBeInTheDocument(),
    );
  });

  it('does not remove other tabs when one is closed', async () => {
    setup();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    const closeBtns = screen.getAllByTitle('Close tab');
    // Close the first tab (Server Alpha)
    await userEvent.click(closeBtns[0]);

    await waitFor(() =>
      expect(screen.queryByText('Server Alpha')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('Server Beta')).toBeInTheDocument();
  });
});

// ── Sign out ──────────────────────────────────────────────────────────────────

describe('Dashboard header — sign out', () => {
  it('calls onLogout when the sign out button is clicked', async () => {
    const { onLogout } = setup();
    await userEvent.click(screen.getByTitle('Sign out'));
    await waitFor(() => expect(onLogout).toHaveBeenCalledTimes(1));
  });
});
