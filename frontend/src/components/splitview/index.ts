/**
 * Barrel export for the split-view / grid-layout system.
 *
 * Import everything you need from this single entry point:
 *
 *   import { SplitView, LayoutPicker, useGridLayout } from "../components/splitview";
 */

export { SplitView } from "./SplitView";
export { LayoutPicker } from "./LayoutPicker";
export { GridCell } from "./GridCell";
export { useGridLayout } from "./useGridLayout";
export type { UseGridLayoutReturn } from "./useGridLayout";
export {
  LAYOUT_PRESETS,
  cellCount,
} from "./GridLayoutTypes";
export type {
  GridLayout,
  CellAssignmentMap,
  LayoutPreset,
} from "./GridLayoutTypes";
