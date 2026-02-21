/**
 * useGridLayout — reusable hook for managing a split-view grid layout.
 *
 * Generic over TKey so it works with any kind of content key
 * (tab numbers, device ids, strings, …).
 *
 * Responsibilities:
 *  - Hold the current GridLayout (rows x cols).
 *  - Hold the CellAssignmentMap (cell index → TKey | null).
 *  - Resize the assignment map when the layout changes, preserving as many
 *    existing assignments as possible.
 *  - Expose helpers to assign / clear individual cells.
 *  - Expose a helper to remove a key from all cells (e.g. on tab close).
 */

import { useCallback, useState } from "react";
import {
  CellAssignmentMap,
  GridLayout,
  cellCount,
} from "./GridLayoutTypes";

export interface UseGridLayoutReturn<TKey> {
  layout: GridLayout;
  assignments: CellAssignmentMap<TKey>;
  /** Replace the layout, keeping as many existing assignments as possible. */
  setLayout: (next: GridLayout) => void;
  /** Assign a key to a cell (passing null clears it). */
  assignCell: (cellIndex: number, key: TKey | null) => void;
  /** Remove a key from every cell it currently occupies. */
  evictKey: (key: TKey) => void;
  /** Place a key into the first empty cell, or do nothing if all are filled. */
  autoPlace: (key: TKey) => void;
  /** Focused cell index (last cell the user interacted with). */
  focusedCell: number;
  setFocusedCell: (index: number) => void;
}

function buildEmptyMap<TKey>(count: number): CellAssignmentMap<TKey> {
  const m = new Map<number, TKey | null>();
  for (let i = 0; i < count; i++) m.set(i, null);
  return m;
}

export function useGridLayout<TKey>(
  initialLayout: GridLayout = { rows: 1, cols: 1 },
): UseGridLayoutReturn<TKey> {
  const [layout, setLayoutState] = useState<GridLayout>(initialLayout);
  const [assignments, setAssignments] = useState<CellAssignmentMap<TKey>>(
    () => buildEmptyMap<TKey>(cellCount(initialLayout)),
  );
  const [focusedCell, setFocusedCell] = useState<number>(0);

  const setLayout = useCallback((next: GridLayout) => {
    const count = cellCount(next);
    setAssignments((prev) => {
      const next_map = new Map<number, TKey | null>();
      for (let i = 0; i < count; i++) {
        next_map.set(i, prev.get(i) ?? null);
      }
      return next_map;
    });
    setLayoutState(next);
    // Keep focused cell in bounds
    setFocusedCell((prev) => (prev < count ? prev : 0));
  }, []);

  const assignCell = useCallback((cellIndex: number, key: TKey | null) => {
    setAssignments((prev) => {
      const next = new Map(prev);
      // If the same key was in another cell, evict it first
      if (key !== null) {
        for (const [idx, v] of next) {
          if (v === key && idx !== cellIndex) next.set(idx, null);
        }
      }
      next.set(cellIndex, key);
      return next;
    });
  }, []);

  const evictKey = useCallback((key: TKey) => {
    setAssignments((prev) => {
      const next = new Map(prev);
      for (const [idx, v] of next) {
        if (v === key) next.set(idx, null);
      }
      return next;
    });
  }, []);

  const autoPlace = useCallback((key: TKey) => {
    setAssignments((prev) => {
      // Already placed — no-op
      for (const v of prev.values()) {
        if (v === key) return prev;
      }
      // Find first empty cell
      for (const [idx, v] of prev) {
        if (v === null) {
          const next = new Map(prev);
          next.set(idx, key);
          return next;
        }
      }
      // All cells full — place in focused cell (evicting the current occupant)
      const next = new Map(prev);
      next.set(focusedCell, key);
      return next;
    });
  }, [focusedCell]);

  return {
    layout,
    assignments,
    setLayout,
    assignCell,
    evictKey,
    autoPlace,
    focusedCell,
    setFocusedCell,
  };
}
