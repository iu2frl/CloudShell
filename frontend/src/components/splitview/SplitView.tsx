/**
 * SplitView — assembles GridCells into a CSS grid.
 *
 * Fully generic: knows nothing about SSH, terminals, or devices.
 * Pass any items, a key extractor, a label and a render function.
 *
 * Props
 * ──────
 *  layout       Current GridLayout (rows x cols)
 *  assignments  CellAssignmentMap<TKey> from useGridLayout
 *  items        All available items (e.g. open tabs)
 *  getKey       (item) => TKey
 *  getLabel     (item) => string
 *  focusedCell  Index of the focused cell
 *  onAssign     (cellIndex, key | null) => void
 *  onFocus      (cellIndex) => void
 *  children     (item) => ReactNode — the actual panel content
 *  emptyState   ReactNode shown when items array is empty and layout is 1x1
 */

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
  children: (item: TItem) => React.ReactNode;
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
  children,
  emptyState,
}: SplitViewProps<TKey, TItem>) {
  const { rows, cols } = layout;
  const totalCells = rows * cols;
  const isSingleEmpty = totalCells === 1 && items.length === 0;

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
        >
          {children}
        </GridCell>
      ))}
    </div>
  );
}
