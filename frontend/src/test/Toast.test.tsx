/**
 * tests for components/Toast.tsx
 *
 * Covers:
 * - useToast throws when used outside ToastProvider
 * - toast.success renders a message with the success icon border class
 * - toast.error renders a message with the error icon border class
 * - toast.info renders a message with the info icon border class
 * - multiple toasts are all visible
 * - clicking the dismiss (X) button removes the toast
 * - at most 5 toasts are visible at once (slice(-4) keeps last 4 + new = 5)
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastProvider, useToast } from '../components/Toast';

// Helper: a small component that fires toast calls via buttons
function ToastTrigger() {
  const toast = useToast();
  return (
    <>
      <button onClick={() => toast.success('Saved!')}>success</button>
      <button onClick={() => toast.error('Boom!')}>error</button>
      <button onClick={() => toast.info('Connecting...')}>info</button>
    </>
  );
}

function setup() {
  render(
    <ToastProvider>
      <ToastTrigger />
    </ToastProvider>,
  );
}

describe('useToast — outside provider', () => {
  it('throws when called outside ToastProvider', () => {
    // Render a component that calls useToast without a provider
    function Bad() { useToast(); return null; }
    expect(() => render(<Bad />)).toThrow('useToast must be used inside <ToastProvider>');
  });
});

describe('ToastProvider', () => {
  it('shows a success toast message', async () => {
    setup();
    await userEvent.click(screen.getByText('success'));
    expect(screen.getByText('Saved!')).toBeInTheDocument();
  });

  it('shows an error toast message', async () => {
    setup();
    await userEvent.click(screen.getByText('error'));
    expect(screen.getByText('Boom!')).toBeInTheDocument();
  });

  it('shows an info toast message', async () => {
    setup();
    await userEvent.click(screen.getByText('info'));
    expect(screen.getByText('Connecting...')).toBeInTheDocument();
  });

  it('applies the error border class for error toasts', async () => {
    const { container } = render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByText('error'));
    // The toast wrapper uses border-red-700/60 for errors
    expect(container.querySelector('.border-red-700\\/60')).toBeInTheDocument();
  });

  it('applies the success border class for success toasts', async () => {
    const { container } = render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByText('success'));
    expect(container.querySelector('.border-green-700\\/60')).toBeInTheDocument();
  });

  it('applies the info border class for info toasts', async () => {
    const { container } = render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByText('info'));
    expect(container.querySelector('.border-blue-700\\/60')).toBeInTheDocument();
  });

  it('removes the toast when the dismiss button is clicked', async () => {
    setup();
    await userEvent.click(screen.getByText('success'));
    expect(screen.getByText('Saved!')).toBeInTheDocument();
    // The dismiss button is the X icon button inside the toast
    const dismissBtns = screen.getAllByRole('button').filter(
      (b) => !['success', 'error', 'info'].includes(b.textContent ?? ''),
    );
    await userEvent.click(dismissBtns[0]);
    expect(screen.queryByText('Saved!')).not.toBeInTheDocument();
  });

  it('shows multiple toasts simultaneously', async () => {
    setup();
    await userEvent.click(screen.getByText('success'));
    await userEvent.click(screen.getByText('error'));
    await userEvent.click(screen.getByText('info'));
    expect(screen.getByText('Saved!')).toBeInTheDocument();
    expect(screen.getByText('Boom!')).toBeInTheDocument();
    expect(screen.getByText('Connecting...')).toBeInTheDocument();
  });

  it('caps visible toasts at 5 (slice -4 + new)', async () => {
    // ToastProvider keeps the last 4 toasts + the new one = 5 max
    function ManyTrigger() {
      const toast = useToast();
      return (
        <button onClick={() => {
          for (let i = 1; i <= 7; i++) toast.info(`msg-${i}`);
        }}>
          spam
        </button>
      );
    }
    render(<ToastProvider><ManyTrigger /></ToastProvider>);
    await userEvent.click(screen.getByText('spam'));
    // Only the last 5 messages should be visible
    expect(screen.queryByText('msg-1')).not.toBeInTheDocument();
    expect(screen.queryByText('msg-2')).not.toBeInTheDocument();
    expect(screen.getByText('msg-3')).toBeInTheDocument();
    expect(screen.getByText('msg-7')).toBeInTheDocument();
  });

  it('auto-dismisses toasts after timeout', async () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastTrigger /></ToastProvider>);
    act(() => { fireEvent.click(screen.getByText('info')); });
    expect(screen.getByText('Connecting...')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.queryByText('Connecting...')).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it('auto-dismisses error toasts after 6 seconds', async () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastTrigger /></ToastProvider>);
    act(() => { fireEvent.click(screen.getByText('error')); });
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getByText('Boom!')).toBeInTheDocument(); // still visible at 5s
    act(() => { vi.advanceTimersByTime(2000); });
    expect(screen.queryByText('Boom!')).not.toBeInTheDocument(); // gone at 7s
    vi.useRealTimers();
  });
});
