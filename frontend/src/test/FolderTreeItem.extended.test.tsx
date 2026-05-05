import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FolderTreeItem } from '../components/FolderTreeItem';
import { ToastProvider } from '../components/Toast';
import type { FolderWithChildren } from '../api/client';
import * as apiClient from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, deleteFolder: vi.fn().mockResolvedValue(undefined) };
});

const makeFolder = (overrides: Partial<FolderWithChildren> = {}): FolderWithChildren => ({
  id: 1,
  name: 'Servers',
  description: null,
  parent_folder_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  children: [],
  device_count: 0,
  ...overrides,
});

const defaultProps = {
  folder: makeFolder(),
  level: 0,
  activeDeviceId: null as number | null,
  folderIdsWithDevices: new Set<number>(),
  selectedFolderId: null as number | null,
  expandedFolders: new Set<number>(),
  onToggleExpand: vi.fn(),
  onSelectFolder: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  renderDevices: vi.fn((_folderId: number, _level: number): React.ReactNode => null),
};

const renderItem = (props = defaultProps) =>
  render(
    <ToastProvider>
      <FolderTreeItem {...props} />
    </ToastProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FolderTreeItem extended', () => {
  it('calls onSelectFolder when folder row is clicked', async () => {
    const onSelectFolder = vi.fn();
    renderItem({ ...defaultProps, onSelectFolder });
    await userEvent.click(screen.getByText('Servers'));
    expect(onSelectFolder).toHaveBeenCalledWith(1);
  });

  it('highlights selected folder', () => {
    const { container } = renderItem({ ...defaultProps, selectedFolderId: 1 });
    const row = container.querySelector('[data-test-folder]')?.firstElementChild;
    expect(row?.className).toContain('bg-blue-600/20');
  });

  it('calls onToggleExpand when expand button is clicked', async () => {
    const onToggleExpand = vi.fn();
    const folder = makeFolder({ children: [makeFolder({ id: 2, name: 'Child' })] });
    renderItem({ ...defaultProps, folder, onToggleExpand });
    // Folder has children so expand button should exist
    const expandBtn = screen.getByRole('button', { name: '' });
    await userEvent.click(expandBtn);
    expect(onToggleExpand).toHaveBeenCalledWith(1);
  });

  it('renders devices and child folders when expanded', () => {
    const child = makeFolder({ id: 2, name: 'Child', parent_folder_id: 1 });
    const folder = makeFolder({ children: [child] });
    const renderDevices = vi.fn(() => <div data-testid="devices-in-folder" />);

    renderItem({
      ...defaultProps,
      folder,
      expandedFolders: new Set([1]),
      renderDevices,
    });

    expect(renderDevices).toHaveBeenCalledWith(1, 0);
    expect(screen.getByTestId('devices-in-folder')).toBeInTheDocument();
    expect(screen.getByText('Child')).toBeInTheDocument();
  });

  it('does not render expanded content when collapsed', () => {
    const child = makeFolder({ id: 2, name: 'Child', parent_folder_id: 1 });
    const folder = makeFolder({ children: [child] });
    const renderDevices = vi.fn(() => null);

    renderItem({
      ...defaultProps,
      folder,
      expandedFolders: new Set(), // not expanded
      renderDevices,
    });

    expect(renderDevices).not.toHaveBeenCalled();
    expect(screen.queryByText('Child')).not.toBeInTheDocument();
  });

  it('shows error toast when delete fails', async () => {
    vi.mocked(apiClient.deleteFolder).mockRejectedValue(new Error('network'));

    renderItem();

    await userEvent.click(screen.getByTitle('Delete folder'));
    const dialog = screen.getByRole('dialog', { name: 'Delete folder?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete folder' }));

    await waitFor(() => {
      expect(screen.getByText(/Delete failed/)).toBeInTheDocument();
    });
  });

  it('calls onEdit when edit button is clicked', async () => {
    const onEdit = vi.fn();
    renderItem({ ...defaultProps, onEdit });
    await userEvent.click(screen.getByTitle('Edit folder'));
    expect(onEdit).toHaveBeenCalledWith(defaultProps.folder);
  });

  it('renders data attribute for nested level', () => {
    const { container } = renderItem({ ...defaultProps, level: 1 });
    const item = container.querySelector('[data-test-folder]');
    expect(item?.getAttribute('data-test-folder')).toContain('level-1');
  });

  it('shows spacer div when folder has no children', () => {
    const { container } = renderItem();
    // No expand button, but a spacer div
    const spacer = container.querySelector('.w-4');
    expect(spacer).toBeInTheDocument();
  });

  it('hides action buttons while deleting', async () => {
    vi.mocked(apiClient.deleteFolder).mockReturnValue(new Promise(() => {})); // hang

    renderItem();

    await userEvent.click(screen.getByTitle('Delete folder'));
    const dialog = screen.getByRole('dialog', { name: 'Delete folder?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete folder' }));

    // While deleting, the action buttons should be hidden
    await waitFor(() => {
      expect(screen.queryByTitle('Edit folder')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Delete folder')).not.toBeInTheDocument();
    });
  });

  it('clicking inside the delete dialog does not dismiss it (stopPropagation)', async () => {
    renderItem();

    await userEvent.click(screen.getByTitle('Delete folder'));
    const dialog = screen.getByRole('dialog', { name: 'Delete folder?' });

    // Click on the dialog body itself (not the backdrop)
    await userEvent.click(dialog);

    // Dialog should still be visible
    expect(screen.getByRole('dialog', { name: 'Delete folder?' })).toBeInTheDocument();
  });
});
