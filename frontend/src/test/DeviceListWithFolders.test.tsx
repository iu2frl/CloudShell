import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DeviceListWithFolders } from '../components/DeviceListWithFolders';
import { ToastProvider } from '../components/Toast';
import type { Device, FolderWithChildren } from '../api/client';
import * as apiClient from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    deleteDevice: vi.fn().mockResolvedValue(undefined),
    listFolders: vi.fn(),
    updateDevice: vi.fn().mockResolvedValue(undefined),
  };
});

const makeDevice = (id: number): Device => ({
  id,
  name: `Server-${id}`,
  hostname: 'host.example.com',
  port: 2200,
  username: 'root',
  auth_type: 'password',
  connection_type: 'ssh',
  key_filename: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
});

const folders: FolderWithChildren[] = [
  {
    id: 1,
    name: 'Root Folder',
    description: null,
    parent_folder_id: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    device_count: 42,
    children: [
      {
        id: 2,
        name: 'Child Folder',
        description: null,
        parent_folder_id: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        device_count: 0,
        children: [],
      },
    ],
  },
];

const defaultProps = {
  devices: Array.from({ length: 42 }, (_, index) => makeDevice(index + 1)),
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listFolders).mockResolvedValue(folders);
});

describe('DeviceListWithFolders', () => {
  it('starts with folders collapsed and does not render counters', async () => {
    render(
      <ToastProvider>
        <DeviceListWithFolders {...defaultProps} />
      </ToastProvider>,
    );

    expect(await screen.findByText('Root Folder')).toBeInTheDocument();
    expect(screen.queryByText('Child Folder')).not.toBeInTheDocument();
    expect(screen.queryByText('42')).not.toBeInTheDocument();
  });
});
