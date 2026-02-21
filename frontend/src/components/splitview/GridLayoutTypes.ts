/**
 * Shared types for the split-view / grid-layout system.
 *
 * A GridLayout describes *how many rows and columns* the workspace is divided
 * into.  A CellAssignment maps each cell index (row * cols + col) to whatever
 * content key the consumer wants to show there (e.g. a tab key, a device id…).
 *
 * Keeping these types generic (`TKey`) makes the system reusable for any kind
 * of tabbable/paneable content — terminals, file managers, log viewers, etc.
 */

/** Describes the grid dimensions. */
export interface GridLayout {
  rows: number;
  cols: number;
}

/** Maps cell index → content key (or null = empty cell). */
export type CellAssignmentMap<TKey> = Map<number, TKey | null>;

/** A named preset shown in the layout picker. */
export interface LayoutPreset {
  label: string;
  /** Accessible description used for aria-label / tooltip. */
  description: string;
  layout: GridLayout;
  /** SVG icon rendered inside the picker button. */
  icon: string; // inline SVG path data (viewBox 0 0 20 20)
}

/** Presets exposed to the layout picker. */
export const LAYOUT_PRESETS: LayoutPreset[] = [
  {
    label: "1",
    description: "Single pane",
    layout: { rows: 1, cols: 1 },
    icon: "M2 2h16v16H2z",
  },
  {
    label: "1|1",
    description: "Vertical split",
    layout: { rows: 1, cols: 2 },
    icon: "M2 2h7v16H2zm9 0h7v16h-7z",
  },
  {
    label: "1/1",
    description: "Horizontal split",
    layout: { rows: 2, cols: 1 },
    icon: "M2 2h16v7H2zm0 9h16v7H2z",
  },
  {
    label: "2x2",
    description: "2x2 grid",
    layout: { rows: 2, cols: 2 },
    icon: "M2 2h7v7H2zm9 0h7v7h-7zM2 11h7v7H2zm9 0h7v7h-7z",
  },
];

/** Returns the flat cell count for a layout. */
export function cellCount(layout: GridLayout): number {
  return layout.rows * layout.cols;
}
