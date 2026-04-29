import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
    deleteFolder: vi.fn().mockResolvedValue(undefined),
    listFolders: vi.fn(),
    updateDevice: vi.fn().mockResolvedValue(undefined),
    createFolder: vi.fn(),
    updateFolder: vi.fn(),
  };
});

const makeDevice = (id: number, overrides: Partial<Device> = {}): Device => ({
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
  ...overrides,
});

const makeFolder = (overrides: Partial<FolderWithChildren> = {}): FolderWithChildren => ({
  id: 1,
  name: 'TestFolder',
  description: null,
  parent_folder_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  device_count: 0,
  children: [],
  ...overrides,
});

const defaultProps = {
  devices: [makeDevice(1), makeDevice(2)],
  activeDeviceId: null as number | null,
  loading: false,
  collapsed: false,
  onToggleCollapse: vi.fn(),
  onConnect: vi.fn(),
  onAdd: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onRefresh: vi.fn(),
  onFoldersChanged: vi.fn(),
};

const renderWithToast = (props = defaultProps) =>
  render(
    <ToastProvider>
      <DeviceListWithFolders {...props} />
    </ToastProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.listFolders).mockResolvedValue([]);
});

describe('DeviceListWithFolders', () => {
  // -- Expanded sidebar basics -----------------------------------------------

  it('renders devices in expanded mode', async () => {
    renderWithToast();
    expect(screen.getByText('Server-1')).toBeInTheDocument();
    expect(screen.getByText('Server-2')).toBeInTheDocument();
  });

  it('shows empty state when no devices and not loading', () => {
    renderWithToast({ ...defaultProps, devices: [] });
    expect(screen.getByText(/No devices yet/)).toBeInTheDocument();
  });

  it('does not show empty state when folders exist but no devices', async () => {
    const folder = makeFolder({ id: 1, name: 'MyFolder' });
    vi.mocked(apiClient.listFolders).mockResolvedValue([folder]);
    renderWithToast({ ...defaultProps, devices: [] });
    await screen.findByText('MyFolder');
    expect(screen.queryByText(/No devices yet/)).not.toBeInTheDocument();
  });

  it('does not show empty state when loading', () => {
    renderWithToast({ ...defaultProps, devices: [], loading: true });
    expect(screen.queryByText(/No devices yet/)).not.toBeInTheDocument();
  });

  it('shows header with Devices title', () => {
    renderWithToast();
    expect(screen.getByText('Devices')).toBeInTheDocument();
  });

  it('calls onAdd when + button is clicked', async () => {
    renderWithToast();
    await userEvent.click(screen.getByTitle('Add device'));
    expect(defaultProps.onAdd).toHaveBeenCalled();
  });

  it('calls onRefresh when refresh button is clicked', async () => {
    renderWithToast();
    await userEvent.click(screen.getByTitle('Refresh'));
    expect(defaultProps.onRefresh).toHaveBeenCalled();
  });

  it('calls onToggleCollapse when collapse button is clicked', async () => {
    renderWithToast();
    await userEvent.click(screen.getByTitle('Collapse sidebar'));
    expect(defaultProps.onToggleCollapse).toHaveBeenCalled();
  });

  // -- Collapsed sidebar -----------------------------------------------------

  it('renders collapsed sidebar with icon buttons', async () => {
    renderWithToast({ ...defaultProps, collapsed: true });
    expect(screen.getByTitle('Expand sidebar')).toBeInTheDocument();
    expect(screen.getByTitle('Add device')).toBeInTheDocument();
    expect(screen.getByTitle('Refresh')).toBeInTheDocument();
  });

  it('renders device icons in collapsed mode', () => {
    renderWithToast({ ...defaultProps, collapsed: true });
    expect(screen.getByTitle('Server-1')).toBeInTheDocument();
    expect(screen.getByTitle('Server-2')).toBeInTheDocument();
  });

  it('calls onConnect when device icon is clicked in collapsed mode', async () => {
    const onConnect = vi.fn();
    renderWithToast({ ...defaultProps, collapsed: true, onConnect });
    await userEvent.click(screen.getByTitle('Server-1'));
    expect(onConnect).toHaveBeenCalledWith(defaultProps.devices[0]);
  });

  it('highlights active device in collapsed mode', () => {
    renderWithToast({ ...defaultProps, collapsed: true, activeDeviceId: 1 });
    const btn = screen.getByTitle('Server-1');
    expect(btn.className).toContain('bg-blue-600/30');
  });

  it('shows folder icon for sftp devices in collapsed mode', () => {
    const sftpDevice = makeDevice(3, { name: 'SFTP-box', connection_type: 'sftp' });
    renderWithToast({ ...defaultProps, collapsed: true, devices: [sftpDevice] });
    expect(screen.getByTitle('SFTP-box')).toBeInTheDocument();
  });

  it('shows folder icon for ftp devices in collapsed mode', () => {
    const ftpDevice = makeDevice(4, { name: 'FTP-box', connection_type: 'ftp' });
    renderWithToast({ ...defaultProps, collapsed: true, devices: [ftpDevice] });
    expect(screen.getByTitle('FTP-box')).toBeInTheDocument();
  });

  it('shows folder icon for ftps devices in collapsed mode', () => {
    const ftpsDevice = makeDevice(5, { name: 'FTPS-box', connection_type: 'ftps' });
    renderWithToast({ ...defaultProps, collapsed: true, devices: [ftpsDevice] });
    expect(screen.getByTitle('FTPS-box')).toBeInTheDocument();
  });

  it('calls onToggleCollapse when expand button is clicked in collapsed mode', async () => {
    const onToggleCollapse = vi.fn();
    renderWithToast({ ...defaultProps, collapsed: true, onToggleCollapse });
    await userEvent.click(screen.getByTitle('Expand sidebar'));
    expect(onToggleCollapse).toHaveBeenCalled();
  });

  // -- Folder loading --------------------------------------------------------

  it('loads folders on mount', async () => {
    const folders = [makeFolder()];
    vi.mocked(apiClient.listFolders).mockResolvedValue(folders);

    renderWithToast();

    await waitFor(() => {
      expect(apiClient.listFolders).toHaveBeenCalled();
    });
    expect(await screen.findByText('TestFolder')).toBeInTheDocument();
  });

  it('handles folder load failure gracefully', async () => {
    vi.mocked(apiClient.listFolders).mockRejectedValue(new Error('fail'));
    renderWithToast();
    // Should not crash
    await waitFor(() => {
      expect(apiClient.listFolders).toHaveBeenCalled();
    });
  });

  // -- Device delete flow ----------------------------------------------------

  it('deletes a device after confirm', async () => {
    vi.mocked(apiClient.deleteDevice).mockResolvedValue(undefined);
    renderWithToast();

    // Click delete on Server-1
    const deleteButtons = screen.getAllByLabelText('Delete');
    await userEvent.click(deleteButtons[0]);

    // Confirm via modal dialog
    const dialog = screen.getByRole('dialog', { name: 'Delete device?' });
    expect(dialog).toBeInTheDocument();
    await userEvent.click(within(dialog).getByText('Delete device'));

    await waitFor(() => {
      expect(apiClient.deleteDevice).toHaveBeenCalledWith(1);
      expect(defaultProps.onDelete).toHaveBeenCalledWith(1);
    });
  });

  it('shows error toast when device delete fails', async () => {
    vi.mocked(apiClient.deleteDevice).mockRejectedValue(new Error('nope'));
    renderWithToast();

    const deleteButtons = screen.getAllByLabelText('Delete');
    await userEvent.click(deleteButtons[0]);

    const dialog = screen.getByRole('dialog', { name: 'Delete device?' });
    await userEvent.click(within(dialog).getByText('Delete device'));

    await waitFor(() => {
      expect(screen.getByText(/Delete failed/)).toBeInTheDocument();
    });
  });

  it('cancels device delete', async () => {
    renderWithToast();

    const deleteButtons = screen.getAllByLabelText('Delete');
    await userEvent.click(deleteButtons[0]);

    const dialog = screen.getByRole('dialog', { name: 'Delete device?' });
    expect(dialog).toBeInTheDocument();
    await userEvent.click(within(dialog).getByText('Cancel'));
    expect(screen.queryByRole('dialog', { name: 'Delete device?' })).not.toBeInTheDocument();
  });

  // -- Folder create/edit via modal ------------------------------------------

  it('opens folder modal when Create folder is clicked', async () => {
    renderWithToast();
    await userEvent.click(screen.getByTitle('Create folder'));
    expect(screen.getByText('New Folder')).toBeInTheDocument();
  });

  // -- Move device modal -----------------------------------------------------

  it('opens move modal when Move to folder is clicked', async () => {
    const folders = [makeFolder({ id: 10, name: 'Prod' })];
    vi.mocked(apiClient.listFolders).mockResolvedValue(folders);

    renderWithToast();
    await screen.findByText('Prod');

    const moveButtons = screen.getAllByLabelText('Move to folder');
    await userEvent.click(moveButtons[0]);

    const moveModal = screen.getByRole('dialog', { name: 'Move Device' });
    expect(moveModal).toBeInTheDocument();
    expect(screen.getByText(/Move "Server-1"/)).toBeInTheDocument();
    expect(within(moveModal).getByText('Root (no folder)')).toBeInTheDocument();
    expect(within(moveModal).getByText('Prod')).toBeInTheDocument();
  });

  it('moves device to a folder', async () => {
    const folders = [makeFolder({ id: 10, name: 'Prod' })];
    vi.mocked(apiClient.listFolders).mockResolvedValue(folders);
    vi.mocked(apiClient.updateDevice).mockResolvedValue(makeDevice(1, { folder_id: 10 }));

    renderWithToast();
    await screen.findByText('Prod');

    const moveButtons = screen.getAllByLabelText('Move to folder');
    await userEvent.click(moveButtons[0]);

    // Click the folder in the move modal
    const moveModal = screen.getByRole('dialog', { name: 'Move Device' });
    const folderBtn = within(moveModal).getByText('Prod');
    await userEvent.click(folderBtn);

    await waitFor(() => {
      expect(apiClient.updateDevice).toHaveBeenCalledWith(1, { folder_id: 10 });
      expect(defaultProps.onRefresh).toHaveBeenCalled();
    });
  });

  it('moves device to root', async () => {
    vi.mocked(apiClient.listFolders).mockResolvedValue([makeFolder({ id: 10, name: 'Prod' })]);
    vi.mocked(apiClient.updateDevice).mockResolvedValue(makeDevice(1, { folder_id: undefined }));

    renderWithToast();
    await screen.findByText('Prod');

    const moveButtons = screen.getAllByLabelText('Move to folder');
    await userEvent.click(moveButtons[0]);

    await userEvent.click(screen.getByText('Root (no folder)'));

    await waitFor(() => {
      expect(apiClient.updateDevice).toHaveBeenCalledWith(1, { folder_id: null });
    });
  });

  it('shows error toast when move fails', async () => {
    vi.mocked(apiClient.listFolders).mockResolvedValue([makeFolder({ id: 10, name: 'Prod' })]);
    vi.mocked(apiClient.updateDevice).mockRejectedValue(new Error('move failed'));

    renderWithToast();
    await screen.findByText('Prod');

    const moveButtons = screen.getAllByLabelText('Move to folder');
    await userEvent.click(moveButtons[0]);
    await userEvent.click(screen.getByText('Root (no folder)'));

    await waitFor(() => {
      expect(screen.getByText(/Failed to move device/)).toBeInTheDocument();
    });
  });

  it('closes move modal when Cancel is clicked', async () => {
    vi.mocked(apiClient.listFolders).mockResolvedValue([makeFolder({ id: 10, name: 'Prod' })]);

    renderWithToast();
    await screen.findByText('Prod');

    const moveButtons = screen.getAllByLabelText('Move to folder');
    await userEvent.click(moveButtons[0]);

    const moveModal = screen.getByRole('dialog', { name: 'Move Device' });
    expect(moveModal).toBeInTheDocument();

    // Click cancel inside the move modal
    await userEvent.click(within(moveModal).getByText('Cancel'));

    expect(screen.queryByRole('dialog', { name: 'Move Device' })).not.toBeInTheDocument();
  });

  // -- Folder with nested children in move modal -----------------------------

  it('shows nested folders in move modal', async () => {
    const childFolder = makeFolder({ id: 20, name: 'Child', parent_folder_id: 10, children: [] });
    const parentFolder = makeFolder({ id: 10, name: 'Parent', children: [childFolder] });
    vi.mocked(apiClient.listFolders).mockResolvedValue([parentFolder]);

    renderWithToast();
    await screen.findByText('Parent');

    const moveButtons = screen.getAllByLabelText('Move to folder');
    await userEvent.click(moveButtons[0]);

    const moveModal = screen.getByRole('dialog', { name: 'Move Device' });
    expect(within(moveModal).getByText('Parent')).toBeInTheDocument();
    expect(within(moveModal).getByText('Parent > Child')).toBeInTheDocument();
  });

  // -- Devices in folders vs root --------------------------------------------

  it('renders root devices only for devices without folder_id', async () => {
    const rootDevice = makeDevice(1, { name: 'RootDev', folder_id: undefined });
    const folderDevice = makeDevice(2, { name: 'FolderDev', folder_id: 5 });

    renderWithToast({ ...defaultProps, devices: [rootDevice, folderDevice] });

    // Root device visible directly
    expect(screen.getByText('RootDev')).toBeInTheDocument();
  });

  // -- Folder refresh on folder-saved error ----------------------------------

  it('shows error toast when folder refresh fails after save', async () => {
    vi.mocked(apiClient.listFolders)
      .mockResolvedValueOnce([makeFolder()]) // initial load
      .mockRejectedValueOnce(new Error('refresh fail')); // after save

    renderWithToast();
    await screen.findByText('TestFolder');

    // Open folder modal
    await userEvent.click(screen.getByTitle('Create folder'));

    // We have the real FolderModal now, fill in the name
    vi.mocked(apiClient.createFolder).mockResolvedValue({
      id: 99, name: 'NewFolder', created_at: '', updated_at: '',
    } as any);

    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'NewFolder');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(screen.getByText(/Failed to refresh folders/)).toBeInTheDocument();
    });
  });

  // -- Folder delete refresh error -------------------------------------------

  it('shows error toast when folder refresh fails after delete', async () => {
    // We need a real FolderTreeItem that calls onDelete
    const folder = makeFolder({ id: 1, name: 'ToDelete' });
    vi.mocked(apiClient.listFolders)
      .mockResolvedValueOnce([folder]) // initial load
      .mockRejectedValueOnce(new Error('oops')); // after delete

    vi.mocked(apiClient.deleteFolder).mockResolvedValue(undefined);

    renderWithToast();
    await screen.findByText('ToDelete');

    // Click delete on the folder
    await userEvent.click(screen.getByTitle('Delete folder'));
    // Confirm in dialog
    const dialog = screen.getByRole('dialog', { name: 'Delete folder?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete folder' }));

    await waitFor(() => {
      expect(screen.getByText(/Failed to refresh folders/)).toBeInTheDocument();
    });
  });

  // -- Loading spinner in collapsed mode -------------------------------------

  it('shows spinner when loading in collapsed mode', () => {
    const { container } = renderWithToast({ ...defaultProps, collapsed: true, loading: true });
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).toBeInTheDocument();
  });

  // -- Folder expand/collapse (handleToggleExpand) ----------------------------

  it('expands a folder to show devices inside it', async () => {
    const folder = makeFolder({ id: 1, name: 'Production' });
    const device = makeDevice(10, { name: 'WebServer', folder_id: 1 });
    vi.mocked(apiClient.listFolders).mockResolvedValue([folder]);

    renderWithToast({ ...defaultProps, devices: [device] });
    await screen.findByText('Production');

    // Folder starts collapsed, device not visible
    expect(screen.queryByText('WebServer')).not.toBeInTheDocument();

    // Click the expand chevron on the folder row
    const folderRow = screen.getByText('Production').closest('[data-test-folder]') as HTMLElement;
    const buttons = within(folderRow).getAllByRole('button');
    const expandBtn = buttons[0]; // first button is the expand chevron
    await userEvent.click(expandBtn);

    // Device should now be visible inside the folder
    await waitFor(() => {
      expect(screen.getByText('WebServer')).toBeInTheDocument();
    });
  });

  it('collapses an expanded folder', async () => {
    const folder = makeFolder({ id: 1, name: 'Production' });
    const device = makeDevice(10, { name: 'WebServer', folder_id: 1 });
    vi.mocked(apiClient.listFolders).mockResolvedValue([folder]);

    renderWithToast({ ...defaultProps, devices: [device] });
    await screen.findByText('Production');

    // Expand
    const folderRow = screen.getByText('Production').closest('[data-test-folder]') as HTMLElement;
    const buttons = within(folderRow).getAllByRole('button');
    const expandBtn = buttons[0];
    await userEvent.click(expandBtn);
    await waitFor(() => expect(screen.getByText('WebServer')).toBeInTheDocument());

    // Collapse
    await userEvent.click(expandBtn);
    await waitFor(() => expect(screen.queryByText('WebServer')).not.toBeInTheDocument());
  });

  // -- Edit folder (onEdit callback on FolderTreeItem) ------------------------

  it('opens edit modal when edit button is clicked on a folder', async () => {
    const folder = makeFolder({ id: 1, name: 'Production' });
    vi.mocked(apiClient.listFolders).mockResolvedValue([folder]);

    renderWithToast();
    await screen.findByText('Production');

    await userEvent.click(screen.getByTitle('Edit folder'));

    // The FolderModal should open with the folder name pre-filled
    await waitFor(() => {
      expect(screen.getByDisplayValue('Production')).toBeInTheDocument();
    });
  });
});
