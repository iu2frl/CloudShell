/**
 * tests for components/ErrorBoundary.tsx
 *
 * Covers:
 * - renders children normally when no error occurs
 * - renders the fallback UI when a child throws during render
 * - shows the error message in the fallback
 * - shows the "Something went wrong" heading
 * - shows the "Reload page" button
 * - clicking "Reload page" calls window.location.reload
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBoundary } from '../components/ErrorBoundary';

// Component that throws unconditionally — used to trigger the boundary
function Bomb(): React.ReactNode {
  throw new Error('Test render error');
}

// Suppress the expected console.error noise from React's error boundary
const originalConsoleError = console.error;
afterEach(() => { console.error = originalConsoleError; });

describe('ErrorBoundary', () => {
  it('renders children when there is no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">hello</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('renders the fallback UI when a child throws', () => {
    console.error = vi.fn(); // suppress React's error output
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('displays the thrown error message in the fallback', () => {
    console.error = vi.fn();
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Test render error')).toBeInTheDocument();
  });

  it('shows the Reload page button', () => {
    console.error = vi.fn();
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('button', { name: /reload page/i })).toBeInTheDocument();
  });

  it('calls window.location.reload when Reload page is clicked', async () => {
    console.error = vi.fn();
    const reload = vi.fn();
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { reload },
    });

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    await userEvent.click(screen.getByRole('button', { name: /reload page/i }));
    expect(reload).toHaveBeenCalledOnce();
  });
});
