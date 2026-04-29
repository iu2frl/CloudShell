import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FolderModal } from '../components/FolderModal';
import type { FolderWithChildren } from '../api/client';
import * as apiClient from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    createFolder: vi.fn(),
    updateFolder: vi.fn(),
  };
});

const makeFolderWithChildren = (overrides: Partial<FolderWithChildren> = {}): FolderWithChildren => ({
  id: 1,
  name: 'Existing Folder',
  description: 'A folder',
  parent_folder_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  children: [],
  device_count: 0,
  ...overrides,
});

const defaultProps = {
  isOpen: true,
  editingFolder: null as FolderWithChildren | null,
  availableFolders: [] as Array<{ folder: FolderWithChildren; path: string }>,
  onClose: vi.fn(),
  onSave: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FolderModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<FolderModal {...defaultProps} isOpen={false} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows "New Folder" title when creating', () => {
    render(<FolderModal {...defaultProps} />);
    expect(screen.getByText('New Folder')).toBeInTheDocument();
  });

  it('shows "Edit Folder" title when editing', () => {
    const folder = makeFolderWithChildren();
    render(<FolderModal {...defaultProps} editingFolder={folder} />);
    expect(screen.getByText('Edit Folder')).toBeInTheDocument();
  });

  it('populates form fields when editing', () => {
    const folder = makeFolderWithChildren({ name: 'Prod', description: 'Production' });
    render(<FolderModal {...defaultProps} editingFolder={folder} />);
    expect(screen.getByDisplayValue('Prod')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Production')).toBeInTheDocument();
  });

  it('populates parent folder when editing a nested folder', () => {
    const parent = makeFolderWithChildren({ id: 10, name: 'Parent' });
    const child = makeFolderWithChildren({ id: 20, name: 'Child', parent_folder_id: 10 });
    const availableFolders = [{ folder: parent, path: 'Parent' }];

    render(
      <FolderModal {...defaultProps} editingFolder={child} availableFolders={availableFolders} />,
    );

    const select = screen.getByRole('combobox');
    expect(select).toHaveValue('10');
  });

  it('shows error when saving with empty name', async () => {
    render(<FolderModal {...defaultProps} />);
    await userEvent.click(screen.getByText('Save'));
    expect(screen.getByText('Folder name is required')).toBeInTheDocument();
    expect(apiClient.createFolder).not.toHaveBeenCalled();
  });

  it('calls createFolder and onSave when creating a new folder', async () => {
    const savedFolder = { id: 5, name: 'NewFolder', created_at: '', updated_at: '' };
    vi.mocked(apiClient.createFolder).mockResolvedValue(savedFolder as any);

    render(<FolderModal {...defaultProps} />);

    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'NewFolder');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(apiClient.createFolder).toHaveBeenCalledWith({
        name: 'NewFolder',
        description: undefined,
        parent_folder_id: null,
      });
    });
    expect(defaultProps.onSave).toHaveBeenCalledWith(savedFolder);
  });

  it('calls updateFolder and onSave when editing an existing folder', async () => {
    const folder = makeFolderWithChildren({ id: 7, name: 'Old Name', description: null });
    const updatedFolder = { ...folder, name: 'New Name' };
    vi.mocked(apiClient.updateFolder).mockResolvedValue(updatedFolder as any);

    render(<FolderModal {...defaultProps} editingFolder={folder} />);

    const input = screen.getByDisplayValue('Old Name');
    await userEvent.clear(input);
    await userEvent.type(input, 'New Name');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(apiClient.updateFolder).toHaveBeenCalledWith(7, {
        name: 'New Name',
        description: undefined,
        parent_folder_id: null,
      });
    });
    expect(defaultProps.onSave).toHaveBeenCalledWith(updatedFolder);
  });

  it('shows error message when save fails with Error', async () => {
    vi.mocked(apiClient.createFolder).mockRejectedValue(new Error('Network error'));

    render(<FolderModal {...defaultProps} />);
    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'Test');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('shows generic error message when save fails with non-Error', async () => {
    vi.mocked(apiClient.createFolder).mockRejectedValue('something broke');

    render(<FolderModal {...defaultProps} />);
    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'Test');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(screen.getByText('Failed to save folder')).toBeInTheDocument();
    });
  });

  it('calls onClose when Cancel is clicked', async () => {
    render(<FolderModal {...defaultProps} />);
    await userEvent.click(screen.getByText('Cancel'));
    expect(defaultProps.onClose).toHaveBeenCalled();
  });

  it('selects a parent folder from dropdown', async () => {
    const parent = makeFolderWithChildren({ id: 3, name: 'Servers' });
    const availableFolders = [{ folder: parent, path: 'Servers' }];
    vi.mocked(apiClient.createFolder).mockResolvedValue({ id: 9, name: 'Sub' } as any);

    render(<FolderModal {...defaultProps} availableFolders={availableFolders} />);

    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'Sub');
    await userEvent.selectOptions(screen.getByRole('combobox'), '3');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(apiClient.createFolder).toHaveBeenCalledWith({
        name: 'Sub',
        description: undefined,
        parent_folder_id: 3,
      });
    });
  });

  it('clears parent folder selection back to root', async () => {
    const parent = makeFolderWithChildren({ id: 3, name: 'Servers' });
    const availableFolders = [{ folder: parent, path: 'Servers' }];
    vi.mocked(apiClient.createFolder).mockResolvedValue({ id: 10, name: 'Root' } as any);

    render(<FolderModal {...defaultProps} availableFolders={availableFolders} />);

    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'Root');
    await userEvent.selectOptions(screen.getByRole('combobox'), '3');
    await userEvent.selectOptions(screen.getByRole('combobox'), '');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(apiClient.createFolder).toHaveBeenCalledWith({
        name: 'Root',
        description: undefined,
        parent_folder_id: null,
      });
    });
  });

  it('saves description when provided', async () => {
    vi.mocked(apiClient.createFolder).mockResolvedValue({ id: 11, name: 'F' } as any);

    render(<FolderModal {...defaultProps} />);

    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'F');
    await userEvent.type(screen.getByPlaceholderText('Organize your servers...'), 'desc');
    await userEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(apiClient.createFolder).toHaveBeenCalledWith({
        name: 'F',
        description: 'desc',
        parent_folder_id: null,
      });
    });
  });

  it('resets form when opened for create after editing', async () => {
    const folder = makeFolderWithChildren({ name: 'Edit Me', description: 'desc' });

    const { rerender } = render(
      <FolderModal {...defaultProps} editingFolder={folder} />,
    );
    expect(screen.getByDisplayValue('Edit Me')).toBeInTheDocument();

    rerender(
      <FolderModal {...defaultProps} editingFolder={null} />,
    );

    expect(screen.getByPlaceholderText('My Servers')).toHaveValue('');
  });

  it('shows "Saving..." on the button while loading', async () => {
    // Make createFolder hang
    vi.mocked(apiClient.createFolder).mockReturnValue(new Promise(() => {}));

    render(<FolderModal {...defaultProps} />);
    await userEvent.type(screen.getByPlaceholderText('My Servers'), 'Test');
    await userEvent.click(screen.getByText('Save'));

    expect(screen.getByText('Saving...')).toBeInTheDocument();
  });
});
