/**
 * tests for components/DeviceList.tsx
 *
 * Covers:
 * - renders an empty state message when devices array is empty
 * - renders a device name, host, user@host:port
 * - renders the device count badge
 * - calls onConnect when a device row is clicked
 * - calls onAdd when the + button is clicked
 * - calls onEdit when the edit (pencil) button is clicked
 * - shows delete confirm prompt when delete icon is clicked
 * - calls onDelete after confirming deletion (via mock deleteDevice)
 * - hides confirm prompt when Cancel is clicked
 * - collapsed mode: shows ChevronsRight toggle button
 * - collapsed mode: clicking the toggle calls onToggleCollapse
 * - collapsed mode: renders device icon buttons instead of full rows
 * - shows SFTP badge for sftp connection type
 * - shows SSH key icon for key auth type
 * - device name does not have truncate class at rest (no hover)
 * - action buttons container is absolutely positioned (does not consume layout space at rest)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeviceList } from '../components/DeviceList';
import { ToastProvider } from '../components/Toast';
import type { Device } from '../api/client';

// Mock the deleteDevice API call so tests stay offline
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, deleteDevice: vi.fn().mockResolvedValue(undefined) };
});

const makeDevice = (overrides: Partial<Device> = {}): Device => ({
  id: 1,
  name: 'My Server',
  hostname: '10.0.0.1',
  port: 22,
  username: 'root',
  auth_type: 'password',
  connection_type: 'ssh',
  key_filename: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  ...overrides,
});

const defaultProps = {
  devices: [makeDevice()],
  activeDeviceId: null,
  loading: false,
  collapsed: false,
  onToggleCollapse: vi.fn(),
  onConnect: vi.fn(),
  onAdd: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onRefresh: vi.fn(),
};

function setup(overrides = {}) {
  const props = { ...defaultProps, ...overrides };
  render(
    <ToastProvider>
      <DeviceList {...props} />
    </ToastProvider>,
  );
  return props;
}

beforeEach(() => { vi.clearAllMocks(); });

describe('DeviceList — empty state', () => {
  it('shows the empty state message when devices is empty', () => {
    setup({ devices: [] });
    expect(screen.getByText(/No devices yet/i)).toBeInTheDocument();
  });

  it('does not show the empty state when devices are present', () => {
    setup();
    expect(screen.queryByText(/No devices yet/i)).not.toBeInTheDocument();
  });
});

describe('DeviceList — device rows', () => {
  it('renders the device name', () => {
    setup();
    expect(screen.getByText('My Server')).toBeInTheDocument();
  });

  it('renders user@host:port', () => {
    setup();
    expect(screen.getByText('root@10.0.0.1:22')).toBeInTheDocument();
  });

  it('renders the device count badge', () => {
    setup({ devices: [makeDevice({ id: 1 }), makeDevice({ id: 2, name: 'B' })] });
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('calls onConnect when a device row is clicked', async () => {
    const { onConnect } = setup();
    await userEvent.click(screen.getByText('My Server'));
    expect(onConnect).toHaveBeenCalledWith(makeDevice());
  });

  it('shows the SFTP badge for sftp connection type', () => {
    setup({ devices: [makeDevice({ connection_type: 'sftp' })] });
    expect(screen.getByText('SFTP')).toBeInTheDocument();
  });

  it('shows SSH key icon for key auth type', () => {
    setup({ devices: [makeDevice({ auth_type: 'key' })] });
    expect(screen.getByLabelText('SSH key')).toBeInTheDocument();
  });

  it('shows password icon for password auth type', () => {
    setup();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });
});

describe('DeviceList — actions', () => {
  it('calls onAdd when the + button is clicked', async () => {
    const { onAdd } = setup();
    await userEvent.click(screen.getByTitle('Add device'));
    expect(onAdd).toHaveBeenCalledOnce();
  });

  it('calls onEdit when the edit button is clicked', async () => {
    const { onEdit } = setup();
    await userEvent.click(screen.getByLabelText('Edit'));
    expect(onEdit).toHaveBeenCalledWith(makeDevice());
  });
});

describe('DeviceList — delete flow', () => {
  it('shows the confirm prompt when delete is clicked', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Delete'));
    expect(screen.getByText(/Delete "My Server"\?/)).toBeInTheDocument();
  });

  it('hides the confirm prompt when Cancel is clicked', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Delete'));
    await userEvent.click(screen.getByText('Cancel'));
    expect(screen.queryByText(/Delete "My Server"\?/)).not.toBeInTheDocument();
  });

  it('calls onDelete after the user confirms deletion', async () => {
    const { onDelete } = setup();
    await userEvent.click(screen.getByLabelText('Delete'));
    await userEvent.click(screen.getByText('Delete'));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(1));
  });
});

describe('DeviceList — collapsed mode', () => {
  it('renders the expand toggle button when collapsed', () => {
    setup({ collapsed: true });
    expect(screen.getByTitle('Expand sidebar')).toBeInTheDocument();
  });

  it('calls onToggleCollapse when the expand button is clicked', async () => {
    const { onToggleCollapse } = setup({ collapsed: true });
    await userEvent.click(screen.getByTitle('Expand sidebar'));
    expect(onToggleCollapse).toHaveBeenCalledOnce();
  });

  it('renders device icon buttons (not full rows) when collapsed', () => {
    setup({ collapsed: true });
    // The device name should not be visible as text in collapsed mode
    expect(screen.queryByText('My Server')).not.toBeInTheDocument();
    // But a button with the device title should exist
    expect(screen.getByTitle('My Server')).toBeInTheDocument();
  });

  it('calls onConnect when an icon button is clicked in collapsed mode', async () => {
    const { onConnect } = setup({ collapsed: true });
    await userEvent.click(screen.getByTitle('My Server'));
    expect(onConnect).toHaveBeenCalledWith(makeDevice());
  });

  it('renders the collapse button in expanded mode', () => {
    setup({ collapsed: false });
    expect(screen.getByTitle('Collapse sidebar')).toBeInTheDocument();
  });
});

describe('DeviceList — device name truncation and action button layout', () => {
  it('device name element does not have the truncate class at rest', () => {
    setup();
    const nameEl = screen.getByText('My Server');
    // classList.contains checks for the exact token 'truncate', not the substring 'group-hover:truncate'
    expect(nameEl.classList.contains('truncate')).toBe(false);
  });

  it('action buttons container is absolutely positioned so it does not consume layout space at rest', () => {
    setup();
    const editBtn = screen.getByLabelText('Edit');
    const container = editBtn.parentElement!;
    expect(container.className).toContain('absolute');
  });
});
