/**
 * SplitView — assembles GridCells into a CSS grid.
 *
 * Fully generic: knows nothing about SSH, terminals, or devices.
 *
 * Content panels are NOT rendered inside the cells. Instead each cell exposes
 * an empty mount-point div via onContentRef so the parent can portal live
 * panels into them without ever unmounting the panel components.
 *
 * Props
 * ──────
 *  layout         Current GridLayout (rows x cols)
 *  assignments    CellAssignmentMap<TKey> from useGridLayout
 *  items          All available items (e.g. open tabs)
 *  getKey         (item) => TKey
 *  getLabel       (item) => string
 *  focusedCell    Index of the focused cell
 *  onAssign       (cellIndex, key | null) => void
 *  onFocus        (cellIndex) => void
 *  onContentRef   (cellIndex, el | null) => void — stable callback
 *  emptyState     ReactNode shown when items array is empty and layout is 1x1
 */

import { useCallback, useRef } from "react";
import { CellAssignmentMap, GridLayout } from "./GridLayoutTypes";
import { GridCell } from "./GridCell";

interface SplitViewProps<TKey, TItem> {
  layout: GridLayout;
  assignments: CellAssignmentMap<TKey>;
  items: TItem[];
  getKey: (item: TItem) => TKey;
  getLabel: (item: TItem) => string;
  focusedCell: number;
  onAssign: (cellIndex: number, key: TKey | null) => void;
  onFocus: (cellIndex: number) => void;
  onContentRef: (cellIndex: number, el: HTMLDivElement | null) => void;
  emptyState?: React.ReactNode;
}

export function SplitView<TKey, TItem>({
  layout,
  assignments,
  items,
  getKey,
  getLabel,
  focusedCell,
  onAssign,
  onFocus,
  onContentRef,
  emptyState,
}: SplitViewProps<TKey, TItem>) {
  const { rows, cols } = layout;
  const totalCells = rows * cols;
  const isSingleEmpty = totalCells === 1 && items.length === 0;

  // Stable per-cell callbacks so GridCell effects don't re-fire needlessly
  const stableRefCbs = useRef<Map<number, (el: HTMLDivElement | null) => void>>(new Map());
  const getRefCb = useCallback((i: number) => {
    if (!stableRefCbs.current.has(i)) {
      stableRefCbs.current.set(i, (el) => onContentRef(i, el));
    }
    return stableRefCbs.current.get(i)!;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onContentRef]);

  if (isSingleEmpty && emptyState) {
    return <div className="h-full">{emptyState}</div>;
  }

  return (
    <div
      className="h-full w-full"
      style={{
        display: "grid",
        gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
        gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        gap: "6px",
      }}
    >
      {Array.from({ length: totalCells }, (_, i) => (
        <GridCell<TKey, TItem>
          key={i}
          index={i}
          isFocused={focusedCell === i}
          assignedKey={assignments.get(i) ?? null}
          items={items}
          getKey={getKey}
          getLabel={getLabel}
          onAssign={onAssign}
          onFocus={onFocus}
          onContentRef={getRefCb(i)}
        />
      ))}
    </div>
  );
}
