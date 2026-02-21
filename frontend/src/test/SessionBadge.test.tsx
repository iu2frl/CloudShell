/**
 * Tests for components/SessionBadge.tsx
 *
 * Covers:
 * - renders a button with a clock icon
 * - displays the formatted countdown from the stored token
 * - shows "expired" when no token is stored
 * - popover is hidden initially
 * - clicking the button opens the popover
 * - popover contains the expected explanation headings / key terms
 * - popover shows the expiry time when a valid token is present
 * - clicking the X button inside the popover closes it
 * - pressing Escape closes the popover
 * - clicking outside the popover closes it
 * - colour class is green when > 30 min remaining
 * - colour class is yellow when 10–30 min remaining
 * - colour class is red + animate-pulse when < 10 min remaining
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { SessionBadge } from '../components/SessionBadge';

// ── Helpers ───────────────────────────────────────────────────────────────────

const FROZEN_NOW = new Date('2026-01-01T12:00:00.000Z').getTime();

/** Build a minimal JWT whose exp claim is `offsetMs` ms from FROZEN_NOW. */
function makeToken(offsetMs: number): string {
  const exp = Math.floor((FROZEN_NOW + offsetMs) / 1000);
  const header  = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(JSON.stringify({ sub: 'admin', exp }));
  return `${header}.${payload}.fakesig`;
}

function setToken(offsetMs: number) {
  localStorage.setItem('token', makeToken(offsetMs));
}

/** Returns the session trigger button by its title attribute. */
const getTrigger = () => screen.getByTitle('Session info');

/**
 * userEvent instance configured to advance fake timers so async pointer
 * events don't stall waiting for real time.
 * Created lazily inside beforeEach after vi.useFakeTimers() is active.
 */

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FROZEN_NOW);
  localStorage.clear();
});

// Convenience: open the popover synchronously via fireEvent (safe with fake timers)
function openPopover() {
  fireEvent.click(getTrigger());
}

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

// ── Rendering ─────────────────────────────────────────────────────────────────

describe('SessionBadge — rendering', () => {
  it('renders a button element', () => {
    render(<SessionBadge />);
    expect(getTrigger()).toBeInTheDocument();
  });

  it('shows "expired" when no token is stored', () => {
    render(<SessionBadge />);
    expect(getTrigger()).toHaveTextContent('expired');
  });

  it('shows the formatted remaining time from the stored token', () => {
    setToken(2 * 60 * 60 * 1000); // exactly 2 h from frozen now
    render(<SessionBadge />);
    // At the frozen moment, 2h remain (displayed as "2h 0m")
    expect(getTrigger()).toHaveTextContent('2h 0m');
  });

  it('shows minutes and seconds when less than an hour remains', () => {
    setToken(25 * 60 * 1000); // exactly 25 min from frozen now
    render(<SessionBadge />);
    expect(getTrigger()).toHaveTextContent('25m 0s');
  });
});

// ── Colour coding ─────────────────────────────────────────────────────────────

describe('SessionBadge — colour classes', () => {
  it('applies green colour when > 30 min remain', () => {
    setToken(60 * 60 * 1000); // 1 h
    render(<SessionBadge />);
    expect(getTrigger().className).toContain('text-green-400');
  });

  it('applies yellow colour when between 10 and 30 min remain', () => {
    setToken(20 * 60 * 1000); // 20 min
    render(<SessionBadge />);
    expect(getTrigger().className).toContain('text-yellow-400');
  });

  it('applies red colour and animate-pulse when < 10 min remain', () => {
    setToken(5 * 60 * 1000); // 5 min
    render(<SessionBadge />);
    const btn = getTrigger();
    expect(btn.className).toContain('text-red-400');
    expect(btn.className).toContain('animate-pulse');
  });
});

// ── Popover visibility ────────────────────────────────────────────────────────

describe('SessionBadge — popover', () => {
  it('popover is not rendered initially', () => {
    render(<SessionBadge />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens the popover when the button is clicked', () => {
    render(<SessionBadge />);
    openPopover();
    expect(screen.getByRole('dialog', { name: /session information/i })).toBeInTheDocument();
  });

  it('toggles the popover closed on a second click', () => {
    render(<SessionBadge />);
    openPopover();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(getTrigger());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes the popover when the X button is clicked', () => {
    render(<SessionBadge />);
    openPopover();
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes the popover when Escape is pressed', () => {
    render(<SessionBadge />);
    openPopover();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes the popover when clicking outside', () => {
    render(
      <div>
        <SessionBadge />
        <span data-testid="outside">outside</span>
      </div>,
    );
    openPopover();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId('outside'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

// ── Popover content ───────────────────────────────────────────────────────────

describe('SessionBadge — popover content', () => {
  beforeEach(() => {
    setToken(60 * 60 * 1000); // 1 h so we are in a predictable state
    render(<SessionBadge />);
    openPopover();
  });

  it('shows the "Session timeout" heading', () => {
    expect(screen.getByText('Session timeout')).toBeInTheDocument();
  });

  it('shows the large countdown inside the popover', () => {
    // The dialog contains a text node with the formatted remaining time
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('1h 0m');
  });

  it('displays the expiry clock time', () => {
    // The "expires at HH:MM" string should be present somewhere in the dialog
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toMatch(/expires at \d{1,2}:\d{2}/i);
  });

  it('mentions JWT in the explanation', () => {
    expect(screen.getByText(/JSON Web Token/i)).toBeInTheDocument();
  });

  it('mentions TOKEN_TTL_HOURS in the explanation', () => {
    expect(screen.getByText('TOKEN_TTL_HOURS')).toBeInTheDocument();
  });

  it('mentions the automatic refresh behaviour', () => {
    expect(screen.getByText(/automatically refreshes/i)).toBeInTheDocument();
  });

  it('mentions the 10-minute refresh window', () => {
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toMatch(/10 minutes/i);
  });

  it('warns about session expiry and login redirect', () => {
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toMatch(/login page/i);
  });
});

// ── Live countdown update ─────────────────────────────────────────────────────

describe('SessionBadge — live countdown', () => {
  it('updates the displayed time as the clock advances', () => {
    setToken(2 * 60 * 1000); // exactly 2 min from frozen now
    render(<SessionBadge />);
    const btn = getTrigger();
    expect(btn).toHaveTextContent('2m 0s');

    // Advance 61 s: 2m 0s → 59s (formatRemaining shows seconds only when m === 0)
    act(() => { vi.advanceTimersByTime(61_000); });
    expect(btn).toHaveTextContent('59s');
  });
});
