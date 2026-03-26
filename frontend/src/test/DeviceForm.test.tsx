/**
 * tests for components/DeviceForm.tsx
 *
 * Covers:
 * - renders "Add Device" heading when no device prop is passed
 * - renders "Edit Device" heading when a device prop is passed
 * - port auto-updates to 21 when connection type is changed to ftp
 * - port auto-updates to 21 when connection type is changed to ftps
 * - port auto-updates to 22 when connection type is changed to sftp
 * - auth type select is disabled for ftp connection type
 * - auth type select is disabled for ftps connection type
 * - SSH Key option is absent from auth type select for ftp
 * - SSH Key option is absent from auth type select for ftps
 * - auth type forced to password when switching to ftp
 * - password field is visible for ftp connection type
 * - calls onCancel when X button is clicked
 * - shows error when save fails
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeviceForm } from '../components/DeviceForm';
import { ToastProvider } from '../components/Toast';
import type { Device } from '../api/client';

// Mock API calls so tests stay offline
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    createDevice: vi.fn().mockResolvedValue({
      id: 99,
      name: 'Test',
      hostname: '1.2.3.4',
      port: 22,
      username: 'user',
      auth_type: 'password',
      connection_type: 'ssh',
      key_filename: null,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    }),
    updateDevice: vi.fn().mockResolvedValue({
      id: 1,
      name: 'Test',
      hostname: '1.2.3.4',
      port: 22,
      username: 'user',
      auth_type: 'password',
      connection_type: 'ssh',
      key_filename: null,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    }),
  };
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
  onSave: vi.fn(),
  onCancel: vi.fn(),
};

function setup(overrides: Partial<Parameters<typeof DeviceForm>[0]> = {}) {
  const props = { ...defaultProps, ...overrides };
  render(
    <ToastProvider>
      <DeviceForm {...props} />
    </ToastProvider>,
  );
  return props;
}

beforeEach(() => vi.clearAllMocks());

describe('DeviceForm — heading', () => {
  it('shows "Add Device" when no device prop is provided', () => {
    setup();
    expect(screen.getByText('Add Device')).toBeInTheDocument();
  });

  it('shows "Edit Device" when a device prop is provided', () => {
    setup({ device: makeDevice() });
    expect(screen.getByText('Edit Device')).toBeInTheDocument();
  });
});

describe('DeviceForm — cancel button', () => {
  it('calls onCancel when the X button is clicked', async () => {
    const { onCancel } = setup();
    // The X close button is the only button in the header area (not inside the form)
    const header = document.querySelector('.border-b');
    const xBtn = header?.querySelector('button');
    await userEvent.click(xBtn!);
    expect(onCancel).toHaveBeenCalled();
  });
});

describe('DeviceForm — FTP/FTPS connection type', () => {
  it('auto-updates port to 21 when ftp is selected', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftp');
    const portInput = screen.getByDisplayValue('21');
    expect(portInput).toBeInTheDocument();
  });

  it('auto-updates port to 21 when ftps is selected', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftps');
    expect(screen.getByDisplayValue('21')).toBeInTheDocument();
  });

  it('auto-updates port to 22 when sftp is selected', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'sftp');
    expect(screen.getByDisplayValue('22')).toBeInTheDocument();
  });

  it('auth type select is disabled for ftp', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftp');
    const authSelect = screen.getAllByRole('combobox')[1] as HTMLSelectElement;
    expect(authSelect).toBeDisabled();
  });

  it('auth type select is disabled for ftps', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftps');
    const authSelect = screen.getAllByRole('combobox')[1] as HTMLSelectElement;
    expect(authSelect).toBeDisabled();
  });

  it('SSH Key option is NOT in auth select for ftp', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftp');
    const authSelect = screen.getAllByRole('combobox')[1] as HTMLSelectElement;
    const options = Array.from(authSelect.options).map((o) => o.text);
    expect(options).not.toContain('SSH Key');
  });

  it('SSH Key option is NOT in auth select for ftps', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftps');
    const authSelect = screen.getAllByRole('combobox')[1] as HTMLSelectElement;
    const options = Array.from(authSelect.options).map((o) => o.text);
    expect(options).not.toContain('SSH Key');
  });

  it('password field is visible after selecting ftp', async () => {
    setup();
    const typeSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    await userEvent.selectOptions(typeSelect, 'ftp');
    expect(screen.getByPlaceholderText('••••••••')).toBeInTheDocument();
  });
});

describe('DeviceForm — FTP connection type dropdown options', () => {
  it('has FTP option in connection type dropdown', () => {
    setup();
    const select = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain('ftp');
  });

  it('has FTPS option in connection type dropdown', () => {
    setup();
    const select = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain('ftps');
  });
});

describe('DeviceForm — error display', () => {
  it('shows error message when save fails', async () => {
    const { createDevice } = await import('../api/client');
    (createDevice as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('Server error'));
    setup();
    // Fill required fields
    await userEvent.type(screen.getByPlaceholderText('My Server'), 'Test');
    await userEvent.type(screen.getByPlaceholderText('192.168.1.1'), '1.2.3.4');
    await userEvent.type(screen.getByPlaceholderText('root'), 'user');
    // Submit
    const submitBtn = screen.getByRole('button', { name: /save/i });
    await userEvent.click(submitBtn);
    await waitFor(() => {
      expect(screen.getByText(/Server error/i)).toBeInTheDocument();
    });
  });
});

describe('DeviceForm — trusted fingerprint management', () => {
  it('deletes fingerprints immediately when trash icons are clicked', async () => {
    const { updateDevice } = await import('../api/client');
    setup({
      device: makeDevice({
        ssh_host_fingerprint: 'SHA256:abc123',
        ftps_cert_thumbprint: 'AA:BB:CC:DD',
      }),
    });

    expect(screen.getByText('Trusted Fingerprints')).toBeInTheDocument();
    expect(screen.getByText('SHA256:abc123')).toBeInTheDocument();
    expect(screen.getByText('AA:BB:CC:DD')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Delete SSH fingerprint' }));

    await waitFor(() => {
      expect(updateDevice).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ ssh_host_fingerprint: null }),
      );
    });

    await userEvent.click(screen.getByRole('button', { name: 'Delete FTPS fingerprint' }));

    await waitFor(() => {
      expect(updateDevice).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ ftps_cert_thumbprint: null }),
      );
    });

    expect(screen.queryByText('SHA256:abc123')).not.toBeInTheDocument();
    expect(screen.queryByText('AA:BB:CC:DD')).not.toBeInTheDocument();
  });
});
