import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

vi.mock('../components/FolderTreeItem', () => ({
  FolderTreeItem: ({ onDelete }: { onDelete: (folderId: number) => void }) => (
    <button onClick={() => onDelete(2)}>Mock delete folder</button>
  ),
}));

vi.mock('../components/FolderModal', () => ({
  FolderModal: ({ isOpen, onSave }: { isOpen: boolean; onSave: (folder: FolderWithChildren) => void }) =>
    isOpen ? (
      <button
        onClick={() =>
          onSave({
            id: 99,
            name: 'new-folder',
            description: null,
            parent_folder_id: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            device_count: 0,
            children: [],
          })
        }
      >
        Mock save folder
      </button>
    ) : null,
}));

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
    name: 'cloud',
    description: null,
    parent_folder_id: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    device_count: 0,
    children: [],
  },
];

const defaultProps = {
  devices: [makeDevice(1)],
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

describe('DeviceListWithFolders refresh handling', () => {
  it('refreshes devices after a folder delete completes', async () => {
    const onRefresh = vi.fn();

    render(
      <ToastProvider>
        <DeviceListWithFolders {...defaultProps} onRefresh={onRefresh} />
      </ToastProvider>,
    );

    const deleteButton = await screen.findByRole('button', { name: 'Mock delete folder' });
    await userEvent.click(deleteButton);

    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('notifies the dashboard after a new folder is saved', async () => {
    const onFoldersChanged = vi.fn();

    render(
      <ToastProvider>
        <DeviceListWithFolders {...defaultProps} onFoldersChanged={onFoldersChanged} />
      </ToastProvider>,
    );

    await userEvent.click(screen.getByTitle('Create folder'));
    await userEvent.click(await screen.findByRole('button', { name: 'Mock save folder' }));

    expect(onFoldersChanged).toHaveBeenCalledOnce();
  });
});
