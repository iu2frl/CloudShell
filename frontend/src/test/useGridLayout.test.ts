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

  it('does not overflow into a non-existent cell when all are full', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 1 }));
    act(() => result.current.autoPlace(1));
    act(() => result.current.autoPlace(2)); // all full, should not throw or corrupt
    expect(result.current.assignments.get(0)).toBe(1);
    expect(result.current.assignments.size).toBe(1);
  });
});

describe('useGridLayout — setFocusedCell', () => {
  it('updates the focused cell index', () => {
    const { result } = renderHook(() => useGridLayout<number>({ rows: 1, cols: 3 }));
    act(() => result.current.setFocusedCell(2));
    expect(result.current.focusedCell).toBe(2);
  });
});
