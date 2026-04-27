/**
 * Tests for tab highlighting in the Dashboard top bar.
 *
 * Three distinct visual states must be applied to each tab chip:
 *
 * 1. Focused  — the tab is assigned to the currently focused grid cell.
 *               CSS classes: bg-blue-600/30 text-blue-300 border-blue-600/50
 *               data attribute: data-tab-focused="true"
 *
 * 2. Visible  — the tab is assigned to a cell that is visible but NOT focused.
 *               CSS classes: bg-slate-700/50 text-slate-300 border-slate-600/50
 *               data attribute: data-tab-visible="true"
 *
 * 3. Inactive — the tab is open but not assigned to any visible cell.
 *               CSS classes: text-slate-400 hover:bg-slate-800
 *
 * In a single-pane layout, at most one tab is focused; all others are inactive.
 * In a split layout, the focused cell tab is "focused" and all other occupied
 * cells get the "visible" style.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Dashboard } from '../pages/Dashboard';
import { ToastProvider } from '../components/Toast';
import type { Device } from '../api/client';

// -- Mocks ---------------------------------------------------------------------

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    listDevices: vi.fn().mockResolvedValue([]),
    listFolders: vi.fn().mockResolvedValue([]),
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

vi.mock('../components/FtpFileManager', () => ({
  FtpFileManager: ({ device }: { device: Device }) => (
    <div data-testid={`ftpfilemanager-${device.id}`} />
  ),
}));

vi.mock('../components/DeviceListWithFolders', () => ({
  DeviceListWithFolders: (props: { onConnect: (d: Device) => void }) => (
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
      <button
        data-testid="connect-device-3"
        onClick={() =>
          props.onConnect({
            id: 3,
            name: 'Server Gamma',
            hostname: '10.0.0.3',
            port: 22,
            username: 'user',
            auth_type: 'password',
            connection_type: 'ssh',
            key_filename: null,
            created_at: '',
            updated_at: '',
          })
        }
      >
        Connect Gamma
      </button>
    </div>
  ),
}));

vi.mock('../components/DeviceForm',           () => ({ DeviceForm: () => null }));
vi.mock('../components/ChangePasswordModal',  () => ({ ChangePasswordModal: () => null }));
vi.mock('../components/AuditLogModal',        () => ({ AuditLogModal: () => null }));

// -- Helpers -------------------------------------------------------------------

function setup() {
  const onLogout = vi.fn();
  render(
    <ToastProvider>
      <Dashboard onLogout={onLogout} />
    </ToastProvider>,
  );
  return { onLogout };
}

async function setupAsync() {
  const result = setup();
  await waitFor(() => expect(document.querySelector('header')).toBeInTheDocument());
  return result;
}

/** Return the tab chip element for a given device name. */
function getTabChip(name: string) {
  return screen.getByText(name).closest('[data-tab-key]') as HTMLElement;
}

beforeEach(() => vi.clearAllMocks());

// -- Single-pane: first connection ---------------------------------------------

describe('Tab highlight — single pane, one open tab', () => {
  it('the connected tab has data-tab-focused="true"', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await waitFor(() => screen.getByText('Server Alpha'));

    const chip = getTabChip('Server Alpha');
    expect(chip).toHaveAttribute('data-tab-focused', 'true');
  });

  it('the connected tab does NOT have data-tab-visible', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await waitFor(() => screen.getByText('Server Alpha'));

    const chip = getTabChip('Server Alpha');
    expect(chip).not.toHaveAttribute('data-tab-visible');
  });

  it('the focused tab has the blue highlight classes', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await waitFor(() => screen.getByText('Server Alpha'));

    const chip = getTabChip('Server Alpha');
    expect(chip.className).toContain('bg-blue-600/30');
    expect(chip.className).toContain('text-blue-300');
    expect(chip.className).toContain('border-blue-600/50');
  });
});

// -- Single-pane: two open tabs ------------------------------------------------

describe('Tab highlight — single pane, two open tabs', () => {
  it('only the most recently connected tab is focused', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    expect(getTabChip('Server Beta')).toHaveAttribute('data-tab-focused', 'true');
    expect(getTabChip('Server Alpha')).not.toHaveAttribute('data-tab-focused');
  });

  it('the other tab is inactive (no visible or focused attribute)', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    const alphaChip = getTabChip('Server Alpha');
    expect(alphaChip).not.toHaveAttribute('data-tab-focused');
    expect(alphaChip).not.toHaveAttribute('data-tab-visible');
  });

  it('the inactive tab has the default (non-highlighted) classes', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    const alphaChip = getTabChip('Server Alpha');
    expect(alphaChip.className).toContain('text-slate-400');
    expect(alphaChip.className).not.toContain('bg-blue-600/30');
    expect(alphaChip.className).not.toContain('bg-slate-700/50');
  });

  it('clicking the inactive tab makes it focused', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    await userEvent.click(getTabChip('Server Alpha'));
    await waitFor(() =>
      expect(getTabChip('Server Alpha')).toHaveAttribute('data-tab-focused', 'true'),
    );
    expect(getTabChip('Server Beta')).not.toHaveAttribute('data-tab-focused');
  });
});

// -- Grid layout: split pane (1|1) --------------------------------------------

describe('Tab highlight — split layout, two visible tabs', () => {
  /**
   * Switch to the vertical split layout via the LayoutPicker.
   * The LayoutPicker renders buttons whose accessible names contain the
   * layout description text (e.g. "Vertical split").
   */
  async function switchToVerticalSplit() {
    const splitBtn = screen.getByTitle('Vertical split');
    await userEvent.click(splitBtn);
  }

  it('in split mode the focused tab has data-tab-focused="true"', async () => {
    await setupAsync();
    await switchToVerticalSplit();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    // After two connections in split mode the last one is in the focused cell
    expect(getTabChip('Server Beta')).toHaveAttribute('data-tab-focused', 'true');
  });

  it('in split mode the other visible tab has data-tab-visible="true"', async () => {
    await setupAsync();
    await switchToVerticalSplit();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    expect(getTabChip('Server Alpha')).toHaveAttribute('data-tab-visible', 'true');
  });

  it('in split mode the visible-but-not-focused tab has the slate highlight classes', async () => {
    await setupAsync();
    await switchToVerticalSplit();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    const alphaChip = getTabChip('Server Alpha');
    expect(alphaChip.className).toContain('bg-slate-700/50');
    expect(alphaChip.className).toContain('text-slate-300');
    expect(alphaChip.className).not.toContain('bg-blue-600/30');
  });

  it('in split mode a third tab replaces the focused cell and becomes focused', async () => {
    await setupAsync();
    await switchToVerticalSplit();
    // Fill both cells
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));
    // Open a third connection — no empty cell, so it replaces the focused cell
    await userEvent.click(screen.getByTestId('connect-device-3'));
    await waitFor(() => screen.getByText('Server Gamma'));

    // Gamma is placed in the focused cell, so it becomes the focused tab
    const gammaChip = getTabChip('Server Gamma');
    expect(gammaChip).toHaveAttribute('data-tab-focused', 'true');
    expect(gammaChip.className).toContain('bg-blue-600/30');

    // The evicted tab (the one that was in the focused cell) is now inactive
    // (it is still open but no longer in any cell)
    const evictedChip = document.querySelector(
      '[data-tab-key]:not([data-tab-focused]):not([data-tab-visible])',
    ) as HTMLElement | null;
    expect(evictedChip).not.toBeNull();
    expect(evictedChip!.className).toContain('text-slate-400');
  });
});

// -- data-tab-key attribute ----------------------------------------------------

describe('Tab highlight — data-tab-key attribute', () => {
  it('every tab chip carries a numeric data-tab-key', async () => {
    await setupAsync();
    await userEvent.click(screen.getByTestId('connect-device-1'));
    await userEvent.click(screen.getByTestId('connect-device-2'));
    await waitFor(() => screen.getByText('Server Beta'));

    const chips = document.querySelectorAll('[data-tab-key]');
    expect(chips.length).toBe(2);
    chips.forEach((chip) => {
      expect(chip.getAttribute('data-tab-key')).toMatch(/^\d+$/);
    });
  });
});
