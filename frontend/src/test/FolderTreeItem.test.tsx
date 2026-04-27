import { describe, it, expect, vi } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FolderTreeItem } from '../components/FolderTreeItem';
import { ToastProvider } from '../components/Toast';
import type { FolderWithChildren } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, deleteFolder: vi.fn().mockResolvedValue(undefined) };
});

const folder: FolderWithChildren = {
  id: 1,
  name: 'Servers',
  description: null,
  parent_folder_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  children: [],
  device_count: 0,
};

describe('FolderTreeItem', () => {
  it('anchors hover action buttons to the folder row', () => {
    const { container } = render(
      <ToastProvider>
        <FolderTreeItem
          folder={folder}
          level={0}
          activeDeviceId={null}
          selectedFolderId={null}
          expandedFolders={new Set<number>()}
          onToggleExpand={vi.fn()}
          onSelectFolder={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          renderDevices={() => null}
        />
      </ToastProvider>,
    );

    const row = container.querySelector('div[data-test-folder="Servers-level-0-haschildren-0"] > div');
    expect(row?.className).toContain('relative');

    const editButton = screen.getByTitle('Edit folder');
    const actionsContainer = editButton.parentElement;
    expect(actionsContainer?.className).toContain('absolute');
    expect(actionsContainer?.className).toContain('top-1/2');
    expect(actionsContainer?.className).toContain('-translate-y-1/2');
  });

  it('shows a delete confirmation popup that explains devices are preserved', async () => {
    const onDelete = vi.fn();

    render(
      <ToastProvider>
        <FolderTreeItem
          folder={folder}
          level={0}
          activeDeviceId={null}
          selectedFolderId={null}
          expandedFolders={new Set<number>()}
          onToggleExpand={vi.fn()}
          onSelectFolder={vi.fn()}
          onEdit={vi.fn()}
          onDelete={onDelete}
          renderDevices={() => null}
        />
      </ToastProvider>,
    );

    await userEvent.click(screen.getByTitle('Delete folder'));

    const dialog = screen.getByRole('dialog', { name: 'Delete folder?' });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/Devices in this folder will not be deleted/i)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete folder' }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(folder.id));
  });

  it('closes the delete popup when clicking the backdrop or pressing Escape', async () => {
    render(
      <ToastProvider>
        <FolderTreeItem
          folder={folder}
          level={0}
          activeDeviceId={null}
          selectedFolderId={null}
          expandedFolders={new Set<number>()}
          onToggleExpand={vi.fn()}
          onSelectFolder={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
          renderDevices={() => null}
        />
      </ToastProvider>,
    );

    await userEvent.click(screen.getByTitle('Delete folder'));

    const dialog = screen.getByRole('dialog', { name: 'Delete folder?' });
    await userEvent.click(dialog.parentElement as HTMLElement);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete folder?' })).not.toBeInTheDocument());

    await userEvent.click(screen.getByTitle('Delete folder'));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete folder?' })).not.toBeInTheDocument());
  });
});
