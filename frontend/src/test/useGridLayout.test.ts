/**
 * tests for useGridLayout.ts
 *
 * Covers every exported behaviour of the hook:
 * - initial state (layout, assignments, focusedCell)
 * - setLayout: resizes map, preserves existing assignments, clamps focusedCell
 * - assignCell: places a key, evicts it from its old cell first
 * - assignCell with null clears the cell
 * - evictKey: removes a key from all cells
 * - autoPlace: fills the first empty cell; no-op if already placed; no-op if all full
 * - setFocusedCell: updates focused index
 */

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useGridLayout } from '../components/splitview/useGridLayout';

// Helper: extract snapshot of assignments as a plain object for easy assertion
function assignSnapshot(map: Map<number, number | null>): Record<number, number | null> {
  return Object.fromEntries(map.entries());
}

describe('useGridLayout — initial state', () => {
  it('defaults to a 1x1 layout', () => {
    const { result } = renderHook(() => useGridLayout<number>());
    expect(result.current.layout).toEqual({ rows: 1, cols: 1 });
  });

  it('creates one null assignment for 1x1', () => {
    const { result } = renderHook(() => useGridLayout<number>());
    expect(assignSnapshot(result.current.assignments)).toEqual({ 0: null });
  });

  it('accepts a custom initial layout', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 2, cols: 3 }));
    expect(result.current.layout).toEqual({ rows: 2, cols: 3 });
    expect(result.current.assignments.size).toBe(6);
  });

  it('starts with focusedCell = 0', () => {
    const { result } = renderHook(() => useGridLayout<number>());
    expect(result.current.focusedCell).toBe(0);
  });
});

describe('useGridLayout — setLayout', () => {
  it('updates layout dimensions', () => {
    const { result } = renderHook(() => useGridLayout<number>());
    act(() => result.current.setLayout({ rows: 1, cols: 2 }));
    expect(result.current.layout).toEqual({ rows: 1, cols: 2 });
  });

  it('creates the correct number of cells', () => {
    const { result } = renderHook(() => useGridLayout<number>());
    act(() => result.current.setLayout({ rows: 2, cols: 2 }));
    expect(result.current.assignments.size).toBe(4);
  });

  it('preserves existing assignments that fit in the new layout', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 2, cols: 2 }));
    act(() => result.current.assignCell(0, 10));
    act(() => result.current.assignCell(1, 20));
    // Shrink to 1x2 (2 cells) — cells 0 and 1 must survive
    act(() => result.current.setLayout({ rows: 1, cols: 2 }));
    expect(result.current.assignments.get(0)).toBe(10);
    expect(result.current.assignments.get(1)).toBe(20);
  });

  it('drops assignments for cells that no longer exist after shrink', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 2, cols: 2 }));
    act(() => result.current.assignCell(3, 99));
    act(() => result.current.setLayout({ rows: 1, cols: 2 })); // cell 3 gone
    expect(result.current.assignments.has(3)).toBe(false);
  });

  it('all new cells are null after an expansion', () => {
    const { result } = renderHook(() => useGridLayout<number>());
    act(() => result.current.setLayout({ rows: 2, cols: 2 }));
    for (const v of result.current.assignments.values()) {
      expect(v).toBeNull();
    }
  });

  it('clamps focusedCell to 0 when it falls outside the new layout', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 2, cols: 2 }));
    act(() => result.current.setFocusedCell(3));
    act(() => result.current.setLayout({ rows: 1, cols: 1 })); // only cell 0 left
    expect(result.current.focusedCell).toBe(0);
  });

  it('keeps focusedCell unchanged when it is still valid after shrink', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 4 }));
    act(() => result.current.setFocusedCell(1));
    act(() => result.current.setLayout({ rows: 1, cols: 2 })); // cell 1 still valid
    expect(result.current.focusedCell).toBe(1);
  });
});

describe('useGridLayout — assignCell', () => {
  it('assigns a key to a cell', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 42));
    expect(result.current.assignments.get(0)).toBe(42);
  });

  it('clears a cell when null is passed', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 42));
    act(() => result.current.assignCell(0, null));
    expect(result.current.assignments.get(0)).toBeNull();
  });

  it('evicts the key from its previous cell when reassigned', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 7));
    act(() => result.current.assignCell(1, 7)); // move key 7 from cell 0 to cell 1
    expect(result.current.assignments.get(0)).toBeNull();
    expect(result.current.assignments.get(1)).toBe(7);
  });

  it('allows different keys in different cells', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 1));
    act(() => result.current.assignCell(1, 2));
    expect(result.current.assignments.get(0)).toBe(1);
    expect(result.current.assignments.get(1)).toBe(2);
  });
});

describe('useGridLayout — evictKey', () => {
  it('removes a key from a single cell', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 5));
    act(() => result.current.evictKey(5));
    expect(result.current.assignments.get(0)).toBeNull();
  });

  it('is a no-op when the key is not in any cell', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 5));
    act(() => result.current.evictKey(99)); // 99 not placed anywhere
    expect(result.current.assignments.get(0)).toBe(5); // 5 untouched
  });

  it('does not affect other keys', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 5));
    act(() => result.current.assignCell(1, 6));
    act(() => result.current.evictKey(5));
    expect(result.current.assignments.get(1)).toBe(6);
  });
});

describe('useGridLayout — autoPlace', () => {
  it('places a key in the first empty cell', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.autoPlace(11));
    expect(result.current.assignments.get(0)).toBe(11);
  });

  it('fills the second cell when the first is already occupied', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.autoPlace(11));
    act(() => result.current.autoPlace(22));
    expect(result.current.assignments.get(1)).toBe(22);
  });

  it('is a no-op when the key is already placed', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.autoPlace(11));
    act(() => result.current.autoPlace(11)); // duplicate call
    // Still only in cell 0; cell 1 stays null
    expect(result.current.assignments.get(0)).toBe(11);
    expect(result.current.assignments.get(1)).toBeNull();
  });

  it('replaces the focused cell when all cells are full (single-tile regression)', () => {
    // Bug: in 1x1 mode autoPlace was a no-op when the only cell was occupied,
    // meaning a second connection was never shown on screen.
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));
    act(() => result.current.autoPlace(1)); // first connection fills the only cell
    act(() => result.current.autoPlace(2)); // second connection must take over cell 0
    expect(result.current.assignments.get(0)).toBe(2);
    expect(result.current.assignments.size).toBe(1);
  });

  it('replaces the focused cell (not cell 0) when all cells are full', () => {
    // In a 1x2 layout where both cells are occupied, a new key placed via
    // autoPlace should land in focusedCell, not always in cell 0.
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 2 }));
    act(() => result.current.assignCell(0, 10));
    act(() => result.current.assignCell(1, 20));
    act(() => result.current.setFocusedCell(1)); // user is looking at cell 1
    act(() => result.current.autoPlace(30));      // all full — should evict cell 1
    expect(result.current.assignments.get(1)).toBe(30);
    expect(result.current.assignments.get(0)).toBe(10); // cell 0 untouched
  });

  it('does not mutate the assignments map size when all cells are full', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));
    act(() => result.current.autoPlace(1));
    act(() => result.current.autoPlace(2));
    // Still exactly 1 cell in a 1x1 grid
    expect(result.current.assignments.size).toBe(1);
  });
});

// ── Regression tests for tab-navigation bug ──────────────────────────────────
//
// Scenario: single-tile mode (1x1 layout).
//   1. User opens device A  → autoPlace fills cell 0 with key 1.
//   2. User opens device B  → autoPlace must replace cell 0 with key 2
//      (previously it was a no-op so key 2 was never shown).
//   3. User clicks the tab for key 1 → if key 1 is not in any cell, autoPlace
//      must bring it back (previously the tab click was a no-op for orphaned tabs).

describe('useGridLayout — single-tile tab navigation regression', () => {
  it('second autoPlace replaces the first connection in 1x1 mode', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));

    act(() => result.current.autoPlace(1)); // connect device A
    expect(result.current.assignments.get(0)).toBe(1);

    act(() => result.current.autoPlace(2)); // connect device B while A is open
    // Device B must now be visible in the only cell
    expect(result.current.assignments.get(0)).toBe(2);
  });

  it('switching back to an orphaned tab via autoPlace restores it to the cell', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));

    act(() => result.current.autoPlace(1)); // open device A → cell 0 = 1
    act(() => result.current.autoPlace(2)); // open device B → cell 0 = 2 (key 1 orphaned)

    // Simulate clicking tab for key 1: it is no longer in any cell, so the
    // tab-click handler calls autoPlace(1) to bring it back.
    act(() => result.current.autoPlace(1));
    expect(result.current.assignments.get(0)).toBe(1);
  });

  it('autoPlace is a no-op for a key that is already the current cell occupant', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));

    act(() => result.current.autoPlace(1));
    act(() => result.current.autoPlace(1)); // calling again for the same key
    expect(result.current.assignments.get(0)).toBe(1);
    expect(result.current.assignments.size).toBe(1);
  });

  it('three successive connections in 1x1 mode each become the visible terminal', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));

    act(() => result.current.autoPlace(1));
    expect(result.current.assignments.get(0)).toBe(1);

    act(() => result.current.autoPlace(2));
    expect(result.current.assignments.get(0)).toBe(2);

    act(() => result.current.autoPlace(3));
    expect(result.current.assignments.get(0)).toBe(3);
  });
});

describe('useGridLayout — setFocusedCell', () => {
  it('updates the focused cell index', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 3 }));
    act(() => result.current.setFocusedCell(2));
    expect(result.current.focusedCell).toBe(2);
  });
});
