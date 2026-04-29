import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeviceRow } from '../components/DeviceRow';
import type { Device } from '../api/client';

const makeDevice = (overrides: Partial<Device> = {}): Device => ({
  id: 1,
  name: 'Server-1',
  hostname: 'host.example.com',
  port: 22,
  username: 'root',
  auth_type: 'password',
  connection_type: 'ssh',
  key_filename: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const defaultProps = {
  device: makeDevice(),
  isActive: false,
  isDeleting: false,
  isConfirm: false,
  onConnect: vi.fn(),
  onEdit: vi.fn(),
  onMove: vi.fn(),
  onDeleteClick: vi.fn(),
  onDeleteConfirm: vi.fn(),
  onDeleteCancel: vi.fn(),
};

describe('DeviceRow', () => {
  it('renders device name and connection info', () => {
    render(<DeviceRow {...defaultProps} />);
    expect(screen.getByText('Server-1')).toBeInTheDocument();
    expect(screen.getByText('root@host.example.com:22')).toBeInTheDocument();
  });

  it('shows SSH badge for ssh connection type', () => {
    render(<DeviceRow {...defaultProps} device={makeDevice({ connection_type: 'ssh' })} />);
    expect(screen.getByText('SSH')).toBeInTheDocument();
  });

  it('shows SFTP badge for sftp connection type', () => {
    render(<DeviceRow {...defaultProps} device={makeDevice({ connection_type: 'sftp' })} />);
    expect(screen.getByText('SFTP')).toBeInTheDocument();
  });

  it('shows FTP badge for ftp connection type', () => {
    render(<DeviceRow {...defaultProps} device={makeDevice({ connection_type: 'ftp' })} />);
    expect(screen.getByText('FTP')).toBeInTheDocument();
  });

  it('shows FTPS badge for ftps connection type', () => {
    render(<DeviceRow {...defaultProps} device={makeDevice({ connection_type: 'ftps' })} />);
    expect(screen.getByText('FTPS')).toBeInTheDocument();
  });

  it('shows SSH key icon for key auth type', () => {
    render(<DeviceRow {...defaultProps} device={makeDevice({ auth_type: 'key' })} />);
    expect(screen.getByLabelText('SSH key')).toBeInTheDocument();
  });

  it('shows Password icon for password auth type', () => {
    render(<DeviceRow {...defaultProps} device={makeDevice({ auth_type: 'password' })} />);
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('calls onConnect when row is clicked', async () => {
    const onConnect = vi.fn();
    render(<DeviceRow {...defaultProps} onConnect={onConnect} />);
    await userEvent.click(screen.getByText('Server-1'));
    expect(onConnect).toHaveBeenCalledWith(defaultProps.device);
  });

  it('does not block onConnect when confirm modal is shown', async () => {
    const onConnect = vi.fn();
    render(<DeviceRow {...defaultProps} onConnect={onConnect} isConfirm={true} />);
    await userEvent.click(screen.getByText('Server-1'));
    expect(onConnect).toHaveBeenCalledWith(defaultProps.device);
  });

  it('shows green status dot when active', () => {
    const { container } = render(<DeviceRow {...defaultProps} isActive={true} />);
    const dot = container.querySelector('.bg-green-400');
    expect(dot).toBeInTheDocument();
  });

  it('does not show status dot when inactive', () => {
    const { container } = render(<DeviceRow {...defaultProps} isActive={false} />);
    const dot = container.querySelector('.bg-green-400');
    expect(dot).not.toBeInTheDocument();
  });

  it('shows action buttons (edit, move, delete)', () => {
    render(<DeviceRow {...defaultProps} />);
    expect(screen.getByLabelText('Edit')).toBeInTheDocument();
    expect(screen.getByLabelText('Move to folder')).toBeInTheDocument();
    expect(screen.getByLabelText('Delete')).toBeInTheDocument();
  });

  it('hides action buttons when deleting', () => {
    render(<DeviceRow {...defaultProps} isDeleting={true} />);
    expect(screen.queryByLabelText('Edit')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Delete')).not.toBeInTheDocument();
  });

  it('calls onEdit when edit button is clicked', async () => {
    const onEdit = vi.fn();
    render(<DeviceRow {...defaultProps} onEdit={onEdit} />);
    await userEvent.click(screen.getByLabelText('Edit'));
    expect(onEdit).toHaveBeenCalledWith(defaultProps.device);
  });

  it('calls onMove when move button is clicked', async () => {
    const onMove = vi.fn();
    render(<DeviceRow {...defaultProps} onMove={onMove} />);
    await userEvent.click(screen.getByLabelText('Move to folder'));
    expect(onMove).toHaveBeenCalledWith(defaultProps.device);
  });

  it('calls onDeleteClick when delete button is clicked', async () => {
    const onDeleteClick = vi.fn();
    render(<DeviceRow {...defaultProps} onDeleteClick={onDeleteClick} />);
    await userEvent.click(screen.getByLabelText('Delete'));
    expect(onDeleteClick).toHaveBeenCalled();
  });

  it('shows delete confirmation modal when isConfirm is true', () => {
    render(<DeviceRow {...defaultProps} isConfirm={true} />);
    const dialog = screen.getByRole('dialog', { name: 'Delete device?' });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/Are you sure you want to delete Server-1/)).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(screen.getByText('Delete device')).toBeInTheDocument();
  });

  it('calls onDeleteCancel when cancel button is clicked in delete modal', async () => {
    const onDeleteCancel = vi.fn();
    render(<DeviceRow {...defaultProps} isConfirm={true} onDeleteCancel={onDeleteCancel} />);
    await userEvent.click(screen.getByText('Cancel'));
    expect(onDeleteCancel).toHaveBeenCalled();
  });

  it('calls onDeleteConfirm when delete button is clicked in delete modal', async () => {
    const onDeleteConfirm = vi.fn();
    render(<DeviceRow {...defaultProps} isConfirm={true} onDeleteConfirm={onDeleteConfirm} />);
    await userEvent.click(screen.getByText('Delete device'));
    expect(onDeleteConfirm).toHaveBeenCalledWith(1);
  });

  it('calls onDeleteCancel when clicking the backdrop', async () => {
    const onDeleteCancel = vi.fn();
    const { container } = render(<DeviceRow {...defaultProps} isConfirm={true} onDeleteCancel={onDeleteCancel} />);
    const backdrop = container.querySelector('.fixed.inset-0') as HTMLElement;
    await userEvent.click(backdrop);
    expect(onDeleteCancel).toHaveBeenCalled();
  });

  it('does not dismiss modal when clicking inside the dialog', async () => {
    const onDeleteCancel = vi.fn();
    render(<DeviceRow {...defaultProps} isConfirm={true} onDeleteCancel={onDeleteCancel} />);
    const dialog = screen.getByRole('dialog', { name: 'Delete device?' });
    await userEvent.click(dialog);
    expect(onDeleteCancel).not.toHaveBeenCalled();
  });

  it('indents based on level', () => {
    const { container } = render(<DeviceRow {...defaultProps} level={2} />);
    const row = container.querySelector('[style]') as HTMLElement;
    expect(row?.style.paddingLeft).toBe('40px'); // 16 + 2*12
  });

  it('has no extra indent at level 0', () => {
    const { container } = render(<DeviceRow {...defaultProps} level={0} />);
    const row = container.querySelector('[style]') as HTMLElement;
    expect(row?.style.paddingLeft).toBe('16px'); // 16 + 0*12
  });

  it('shows spinner when deleting', () => {
    const { container } = render(<DeviceRow {...defaultProps} isDeleting={true} />);
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).toBeInTheDocument();
  });
});
