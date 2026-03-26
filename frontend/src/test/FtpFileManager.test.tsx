/**
 * tests for components/FtpFileManager.tsx
 *
 * Covers:
 * - shows loading spinner while connecting
 * - shows error state with Retry button when connection fails
 * - clicking Retry re-attempts to connect
 * - renders directory listing entries after successful connection
 * - shows protocol badge "FTP" for ftp device
 * - shows protocol badge "FTPS" for ftps device
 * - shows "Empty directory" message when listing is empty
 * - shows item count in status bar
 * - clicking a folder navigates into it
 * - download button calls ftpDownload
 * - delete button opens confirm modal; confirm calls ftpDelete
 * - cancel in delete modal closes without deleting
 * - rename button opens rename modal; confirm calls ftpRename
 * - mkdir button opens new folder modal; confirm calls ftpMkdir
 * - breadcrumb / button navigates to "/"
 * - closes ftp session on unmount
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FtpFileManager } from '../components/FtpFileManager';
import { ToastProvider } from '../components/Toast';
import type { Device } from '../api/client';

// -- API mocks -----------------------------------------------------------------

const mockOpenFtpSession  = vi.fn().mockResolvedValue('sess-ftp-1');
const mockCloseFtpSession = vi.fn().mockResolvedValue(undefined);
const mockFtpList         = vi.fn();
const mockFtpDownload     = vi.fn().mockResolvedValue(undefined);
const mockFtpUpload       = vi.fn().mockResolvedValue(undefined);
const mockFtpDelete       = vi.fn().mockResolvedValue(undefined);
const mockFtpRename       = vi.fn().mockResolvedValue(undefined);
const mockFtpMkdir        = vi.fn().mockResolvedValue(undefined);

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    openFtpSession:  (...args: unknown[]) => mockOpenFtpSession(...args),
    closeFtpSession: (...args: unknown[]) => mockCloseFtpSession(...args),
    ftpList:         (...args: unknown[]) => mockFtpList(...args),
    ftpDownload:     (...args: unknown[]) => mockFtpDownload(...args),
    ftpUpload:       (...args: unknown[]) => mockFtpUpload(...args),
    ftpDelete:       (...args: unknown[]) => mockFtpDelete(...args),
    ftpRename:       (...args: unknown[]) => mockFtpRename(...args),
    ftpMkdir:        (...args: unknown[]) => mockFtpMkdir(...args),
  };
});

// -- Helpers -------------------------------------------------------------------

const makeFtpDevice = (overrides: Partial<Device> = {}): Device => ({
  id: 5,
  name: 'FTP Server',
  hostname: 'ftp.example.com',
  port: 21,
  username: 'ftpuser',
  auth_type: 'password',
  connection_type: 'ftp',
  key_filename: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  ...overrides,
});

const FILE_ENTRY = {
  name: 'readme.txt',
  path: '/readme.txt',
  is_dir: false,
  size: 1024,
  modified: 1700000000,
  permissions: '-rw-r--r--',
};

const DIR_ENTRY = {
  name: 'uploads',
  path: '/uploads',
  is_dir: true,
  size: 0,
  modified: 1700000000,
  permissions: 'drwxr-xr-x',
};

function defaultListResponse() {
  return { path: '/', entries: [FILE_ENTRY, DIR_ENTRY] };
}

function setup(deviceOverrides: Partial<Device> = {}) {
  const device = makeFtpDevice(deviceOverrides);
  const { unmount } = render(
    <ToastProvider>
      <FtpFileManager device={device} />
    </ToastProvider>,
  );
  return { device, unmount };
}

beforeEach(() => {
  vi.clearAllMocks();
  // Always reset to a fresh session ID
  mockOpenFtpSession.mockResolvedValue('sess-ftp-1');
  mockFtpList.mockResolvedValue(defaultListResponse());
});

// -- Connecting state ----------------------------------------------------------

describe('FtpFileManager — connecting state', () => {
  it('shows connecting spinner initially', () => {
    // openFtpSession never resolves in this test
    mockOpenFtpSession.mockReturnValue(new Promise(() => {}));
    setup();
    expect(screen.getByText(/Connecting FTP/i)).toBeInTheDocument();
  });

  it('shows FTPS in connecting message for ftps device', () => {
    mockOpenFtpSession.mockReturnValue(new Promise(() => {}));
    setup({ connection_type: 'ftps' });
    expect(screen.getByText(/Connecting FTPS/i)).toBeInTheDocument();
  });

  it('prompts on FTPS untrusted certificate and retries with trust', async () => {
    const api = await import('../api/client');
    const challenge = new api.FtpsCertificateChallengeError({
      code: 'FTPS_CERT_UNTRUSTED',
      thumbprint: 'AA:BB:CC',
    });
    mockOpenFtpSession.mockRejectedValueOnce(challenge).mockResolvedValueOnce('sess-ftp-2');

    setup({ connection_type: 'ftps' });

    await waitFor(() => expect(mockOpenFtpSession).toHaveBeenNthCalledWith(1, 5));
    expect(screen.getByText('Trust FTPS Certificate')).toBeInTheDocument();
    expect(screen.getByText('AA:BB:CC')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Trust certificate' }));
    await waitFor(() => expect(mockOpenFtpSession).toHaveBeenNthCalledWith(2, 5, { trustCert: true }));
  });
});

// -- Error state ---------------------------------------------------------------

describe('FtpFileManager — error state', () => {
  it('shows error message and Retry button when connection fails', async () => {
    mockOpenFtpSession.mockRejectedValueOnce(new Error('Connection refused'));
    setup();
    await waitFor(() => {
      expect(screen.getByText(/Connection refused/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('clicking Retry calls openFtpSession again', async () => {
    mockOpenFtpSession
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValue('sess-2');
    mockFtpList.mockResolvedValue({ path: '/', entries: [] });
    setup();
    await waitFor(() => screen.getByRole('button', { name: /retry/i }));
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    await waitFor(() => expect(mockOpenFtpSession).toHaveBeenCalledTimes(2));
  });
});

// -- Directory listing ---------------------------------------------------------

describe('FtpFileManager — directory listing', () => {
  it('renders file entries after successful connection', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText('readme.txt')).toBeInTheDocument();
    });
  });

  it('renders folder entries', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText('uploads')).toBeInTheDocument();
    });
  });

  it('shows "Empty directory" when listing is empty', async () => {
    mockFtpList.mockResolvedValue({ path: '/', entries: [] });
    setup();
    await waitFor(() => {
      expect(screen.getByText(/Empty directory/i)).toBeInTheDocument();
    });
  });

  it('shows item count in the status bar', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText(/2 items/i)).toBeInTheDocument();
    });
  });

  it('shows "1 item" (singular) when there is one entry', async () => {
    mockFtpList.mockResolvedValue({ path: '/', entries: [FILE_ENTRY] });
    setup();
    await waitFor(() => {
      expect(screen.getByText('1 item')).toBeInTheDocument();
    });
  });
});

// -- Protocol badge ------------------------------------------------------------

describe('FtpFileManager — protocol badge', () => {
  it('shows "FTP" badge for ftp device', async () => {
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    expect(screen.getByText('FTP')).toBeInTheDocument();
  });

  it('shows "FTPS" badge for ftps device', async () => {
    setup({ connection_type: 'ftps' });
    await waitFor(() => screen.getByText('readme.txt'));
    expect(screen.getByText('FTPS')).toBeInTheDocument();
  });
});

// -- Navigation ----------------------------------------------------------------

describe('FtpFileManager — navigation', () => {
  it('clicking a folder navigates into it', async () => {
    mockFtpList
      .mockResolvedValueOnce(defaultListResponse())
      .mockResolvedValueOnce({ path: '/uploads', entries: [] });
    setup();
    await waitFor(() => screen.getByText('uploads'));
    await userEvent.click(screen.getByText('uploads'));
    await waitFor(() => expect(mockFtpList).toHaveBeenCalledWith('sess-ftp-1', '/uploads'));
  });

  it('clicking the root breadcrumb navigates to "/"', async () => {
    // Start in a subdirectory so we can see the root crumb
    mockFtpList
      .mockResolvedValueOnce({ path: '/', entries: [DIR_ENTRY] })
      .mockResolvedValueOnce({ path: '/uploads', entries: [] })
      .mockResolvedValueOnce({ path: '/', entries: [DIR_ENTRY] });
    setup();
    await waitFor(() => screen.getByText('uploads'));
    await userEvent.click(screen.getByText('uploads'));
    // Now in /uploads — breadcrumb shows "/" and "uploads"
    await waitFor(() => screen.getByText('uploads', { selector: 'button' }));
    // Click the "/" root breadcrumb button (exact text match)
    const rootCrumb = screen.getByRole('button', { name: '/' });
    await userEvent.click(rootCrumb);
    await waitFor(() => expect(mockFtpList).toHaveBeenLastCalledWith('sess-ftp-1', '/'));
  });
});

// -- Download ------------------------------------------------------------------

describe('FtpFileManager — download', () => {
  it('calls ftpDownload when download button is clicked', async () => {
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    // Only files have download buttons; there's exactly one Download button
    const downloadBtn = screen.getByTitle('Download');
    await userEvent.click(downloadBtn);
    expect(mockFtpDownload).toHaveBeenCalledWith('sess-ftp-1', '/readme.txt');
  });
});

// -- Delete --------------------------------------------------------------------

describe('FtpFileManager — delete flow', () => {
  it('opens delete confirm modal when delete button is clicked', async () => {
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    // Click the first Delete button (for readme.txt)
    const deleteBtns = screen.getAllByTitle('Delete');
    await userEvent.click(deleteBtns[0]);
    expect(screen.getByText('Confirm delete')).toBeInTheDocument();
  });

  it('calls ftpDelete and refreshes when Delete is confirmed', async () => {
    // Use single-file listing so there's only one Delete row button
    mockFtpList.mockResolvedValue({ path: '/', entries: [FILE_ENTRY] });
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    await userEvent.click(screen.getByTitle('Delete'));
    // Modal is open; find the modal's confirm button by its parent context (modal has fixed positioning)
    const confirmDeleteBtns = screen.getAllByRole('button', { name: /^delete$/i });
    // Last one is the modal confirm button
    await userEvent.click(confirmDeleteBtns[confirmDeleteBtns.length - 1]);
    await waitFor(() => expect(mockFtpDelete).toHaveBeenCalledWith('sess-ftp-1', '/readme.txt', false));
  });

  it('Cancel in delete modal closes without calling ftpDelete', async () => {
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    const deleteBtns = screen.getAllByTitle('Delete');
    await userEvent.click(deleteBtns[0]);
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(mockFtpDelete).not.toHaveBeenCalled();
    expect(screen.queryByText('Confirm delete')).not.toBeInTheDocument();
  });
});

// -- Rename --------------------------------------------------------------------

describe('FtpFileManager — rename flow', () => {
  it('opens rename modal when rename button is clicked', async () => {
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    // Click the first Rename button (for readme.txt)
    const renameBtns = screen.getAllByTitle('Rename');
    await userEvent.click(renameBtns[0]);
    expect(screen.getByText(/Rename "readme.txt"/i)).toBeInTheDocument();
  });

  it('calls ftpRename when rename is confirmed', async () => {
    // Use single-file listing so there's only one Rename row button
    mockFtpList.mockResolvedValue({ path: '/', entries: [FILE_ENTRY] });
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    await userEvent.click(screen.getByTitle('Rename'));
    const input = screen.getByDisplayValue('readme.txt');
    await userEvent.clear(input);
    await userEvent.type(input, 'new.txt');
    // Get all "Rename" buttons; last one is the modal confirm button
    const renameBtns = screen.getAllByRole('button', { name: /^rename$/i });
    await userEvent.click(renameBtns[renameBtns.length - 1]);
    await waitFor(() =>
      expect(mockFtpRename).toHaveBeenCalledWith('sess-ftp-1', '/readme.txt', '/new.txt'),
    );
  });
});

// -- Mkdir ---------------------------------------------------------------------

describe('FtpFileManager — mkdir flow', () => {
  it('opens new folder modal when "New folder" toolbar button is clicked', async () => {
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    await userEvent.click(screen.getByTitle('New folder'));
    expect(screen.getByPlaceholderText('folder-name')).toBeInTheDocument();
  });

  it('calls ftpMkdir when create folder is confirmed', async () => {
    mockFtpList.mockResolvedValue(defaultListResponse());
    setup();
    await waitFor(() => screen.getByText('readme.txt'));
    await userEvent.click(screen.getByTitle('New folder'));
    await userEvent.type(screen.getByPlaceholderText('folder-name'), 'archive');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));
    await waitFor(() =>
      expect(mockFtpMkdir).toHaveBeenCalledWith('sess-ftp-1', '/archive'),
    );
  });
});

// -- Unmount cleanup -----------------------------------------------------------

describe('FtpFileManager — cleanup', () => {
  it('calls closeFtpSession when the component unmounts', async () => {
    const { unmount } = setup();
    await waitFor(() => screen.getByText('readme.txt'));
    unmount();
    await waitFor(() => expect(mockCloseFtpSession).toHaveBeenCalledWith('sess-ftp-1'));
  });
});
