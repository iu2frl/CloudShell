/**
 * Unit tests for the terminal-fit / ResizeObserver logic extracted from
 * Terminal.tsx.
 *
 * Terminal.tsx cannot be mounted in jsdom (xterm.js requires a real browser
 * canvas), so we test the fit/resize behaviour by replicating the relevant
 * logic with plain DOM nodes and mocked fit/ws objects.
 *
 * Covers:
 * - "terminal-fit" event triggers fit.fit() after a requestAnimationFrame
 * - "terminal-fit" event sends a resize message when the WebSocket is open
 * - "terminal-fit" event does NOT send when the WebSocket is closed
 * - ResizeObserver fires fit.fit() and sends resize when connected
 * - ResizeObserver debounces rapid callbacks into a single fit call
 * - fit is NOT called again after the listener is torn down (cleanup)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ─── rAF / cAF stubs ──────────────────────────────────────────────────────────
// jsdom does not implement requestAnimationFrame; replace with synchronous
// versions so tests run without needing fake timers for every case.
let rafCallbacks: Map<number, FrameRequestCallback>;
let rafCounter: number;

// jsdom also does not implement ResizeObserver; provide a minimal stub.
// We capture the latest callback so individual tests can trigger it manually.
let latestRoCallback: ResizeObserverCallback | null = null;

class StubResizeObserver {
  constructor(cb: ResizeObserverCallback) { latestRoCallback = cb; }
  observe()     { latestRoCallback!([], this); }
  unobserve()   {}
  disconnect()  { latestRoCallback = null; }
}

beforeEach(() => {
  rafCallbacks     = new Map();
  rafCounter       = 0;
  latestRoCallback = null;
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    const id = ++rafCounter;
    rafCallbacks.set(id, cb);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    rafCallbacks.delete(id);
  });
  vi.stubGlobal('ResizeObserver', StubResizeObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Flush all pending rAF callbacks (simulates a browser layout pass). */
function flushRaf(): void {
  const pending = [...rafCallbacks.values()];
  rafCallbacks.clear();
  for (const cb of pending) cb(performance.now());
}

// ─── helpers ──────────────────────────────────────────────────────────────────

interface MockFit  { fit: () => void }
interface MockTerm { rows: number; cols: number }
interface MockWs   { readyState: number; send: (data: Uint8Array) => void }

/**
 * Minimal re-implementation of the persistent resize/fit useEffect from
 * Terminal.tsx.  Returns a teardown function (mirrors the useEffect cleanup).
 */
function attachFitHandler(
  container: HTMLElement,
  fitRef:    { current: MockFit | null },
  wsRef:     { current: MockWs  | null },
  xtermRef:  { current: MockTerm | null },
): () => void {
  let rafId    = 0;

  const doFit = () => {
    try { fitRef.current?.fit(); } catch { /* ignore */ }
    const ws   = wsRef.current;
    const term = xtermRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && term) {
      const { rows, cols } = term;
      ws.send(new TextEncoder().encode(JSON.stringify({ type: 'resize', cols, rows })));
    }
  };

  let resizing = false;
  const ro = new ResizeObserver(() => {
    if (resizing) return;
    resizing = true;
    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => { doFit(); resizing = false; });
  });
  ro.observe(container);

  const onFitEvent = () => {
    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(doFit);
  };
  container.addEventListener('terminal-fit', onFitEvent);

  return () => {
    ro.disconnect();
    container.removeEventListener('terminal-fit', onFitEvent);
    cancelAnimationFrame(rafId);
  };
}

// ─── tests ────────────────────────────────────────────────────────────────────

describe('Terminal fit handler — terminal-fit event', () => {
  it('calls fit.fit() after rAF when "terminal-fit" is dispatched', () => {
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsRef     = { current: null };
    const xtermRef  = { current: null };

    attachFitHandler(container, fitRef, wsRef, xtermRef);
    container.dispatchEvent(new CustomEvent('terminal-fit', { bubbles: true }));

    // fit not called yet — rAF not flushed
    expect(fitRef.current.fit).not.toHaveBeenCalled();

    flushRaf();
    expect(fitRef.current.fit).toHaveBeenCalledTimes(1);
  });

  it('sends a resize message when the WebSocket is open', () => {
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsSend    = vi.fn();
    const wsRef     = { current: { readyState: WebSocket.OPEN, send: wsSend } };
    const xtermRef  = { current: { rows: 24, cols: 80 } };

    attachFitHandler(container, fitRef, wsRef, xtermRef);
    container.dispatchEvent(new CustomEvent('terminal-fit', { bubbles: true }));
    flushRaf();

    expect(wsSend).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(new TextDecoder().decode(wsSend.mock.calls[0][0]));
    expect(sent).toEqual({ type: 'resize', cols: 80, rows: 24 });
  });

  it('does NOT send a resize message when the WebSocket is closed', () => {
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsSend    = vi.fn();
    const wsRef     = { current: { readyState: WebSocket.CLOSED, send: wsSend } };
    const xtermRef  = { current: { rows: 24, cols: 80 } };

    attachFitHandler(container, fitRef, wsRef, xtermRef);
    container.dispatchEvent(new CustomEvent('terminal-fit', { bubbles: true }));
    flushRaf();

    expect(fitRef.current.fit).toHaveBeenCalledTimes(1); // fit still called
    expect(wsSend).not.toHaveBeenCalled();               // but no WS message
  });

  it('does NOT send when wsRef is null (not yet connected)', () => {
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsRef     = { current: null };
    const xtermRef  = { current: { rows: 24, cols: 80 } };

    attachFitHandler(container, fitRef, wsRef, xtermRef);
    container.dispatchEvent(new CustomEvent('terminal-fit', { bubbles: true }));
    flushRaf();

    expect(fitRef.current.fit).toHaveBeenCalledTimes(1);
    // no crash and no send attempted
  });

  it('does not call fit.fit() after cleanup (listener removed)', () => {
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsRef     = { current: null };
    const xtermRef  = { current: null };

    const cleanup = attachFitHandler(container, fitRef, wsRef, xtermRef);
    cleanup(); // simulate useEffect teardown

    container.dispatchEvent(new CustomEvent('terminal-fit', { bubbles: true }));
    flushRaf();

    expect(fitRef.current.fit).not.toHaveBeenCalled();
  });
});

describe('Terminal fit handler — ResizeObserver', () => {
  it('calls fit.fit() and sends resize when the container is resized', () => {
    // The StubResizeObserver fires the callback immediately on observe() —
    // simulating the initial "current size" notification that real browsers send.
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsSend    = vi.fn();
    const wsRef     = { current: { readyState: WebSocket.OPEN, send: wsSend } };
    const xtermRef  = { current: { rows: 30, cols: 120 } };

    attachFitHandler(container, fitRef, wsRef, xtermRef);

    // observe() was called by attachFitHandler, which triggered the stub
    // callback → scheduled a rAF.  Flush it.
    flushRaf();

    expect(fitRef.current.fit).toHaveBeenCalledTimes(1);
    expect(wsSend).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(new TextDecoder().decode(wsSend.mock.calls[0][0]));
    expect(sent).toEqual({ type: 'resize', cols: 120, rows: 30 });
  });

  it('debounces rapid ResizeObserver callbacks into a single fit call', () => {
    const container = document.createElement('div');
    const fitRef    = { current: { fit: vi.fn() } };
    const wsRef     = { current: null };
    const xtermRef  = { current: null };

    attachFitHandler(container, fitRef, wsRef, xtermRef);
    // observe() already fired once; flush that initial rAF and reset the mock
    flushRaf();
    fitRef.current.fit.mockClear();

    // Fire the observer two more times without flushing rAF in between
    latestRoCallback!([], {} as ResizeObserver);
    latestRoCallback!([], {} as ResizeObserver);

    // Both callbacks schedule rAF; each cancels the previous one → only 1 flush
    flushRaf();
    expect(fitRef.current.fit).toHaveBeenCalledTimes(1);
  });
});
