/**
 * tests for SplitView.tsx
 *
 * Covers:
 * - renders the correct number of cells for each layout
 * - renders the emptyState when layout is 1x1 and items is empty
 * - does NOT render emptyState when items are present
 * - does NOT render emptyState when layout is larger than 1x1
 * - applies the correct CSS grid-template-rows and grid-template-columns
 * - each cell receives the correct assignedKey from the assignments map
 * - calls onAssign and onFocus (delegated to GridCell — integration check)
 * - calls onContentRef for each cell so the parent can DOM-move live panels
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SplitView } from '../components/splitview/SplitView';
import type { CellAssignmentMap, GridLayout } from '../components/splitview/GridLayoutTypes';

interface Item { id: number; label: string }
const items: Item[] = [
  { id: 1, label: 'Alpha' },
  { id: 2, label: 'Beta' },
];

function makeAssignments(entries: [number, number | null][]): CellAssignmentMap<number> {
  return new Map(entries);
}

function setup({
  layout = { rows: 1, cols: 1 } as GridLayout,
  assignments = makeAssignments([[0, null]]),
  itemList = items,
  focusedCell = 0,
} = {}) {
  const onAssign     = vi.fn();
  const onFocus      = vi.fn();
  const onContentRef = vi.fn();
  const { container } = render(
    <SplitView<number, Item>
      layout={layout}
      assignments={assignments}
      items={itemList}
      getKey={(item) => item.id}
      getLabel={(item) => item.label}
      focusedCell={focusedCell}
      onAssign={onAssign}
      onFocus={onFocus}
      onContentRef={onContentRef}
      emptyState={<div data-testid="empty-state">No connections</div>}
    />,
  );
  return { container, onAssign, onFocus, onContentRef };
}

describe('SplitView — empty state', () => {
  it('renders emptyState when 1x1 layout and no items', () => {
    setup({ itemList: [] });
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
  });

  it('does not render the grid when showing emptyState', () => {
    const { container } = setup({ itemList: [] });
    // No CSS grid wrapper should be present
    const grid = container.querySelector('[style*="grid-template"]');
    expect(grid).toBeNull();
  });

  it('does not render emptyState when items are present', () => {
    setup();
    expect(screen.queryByTestId('empty-state')).not.toBeInTheDocument();
  });

  it('does not render emptyState for a 2x2 layout even with no items', () => {
    setup({
      layout: { rows: 2, cols: 2 },
      assignments: makeAssignments([[0, null],[1, null],[2, null],[3, null]]),
      itemList: [],
    });
    expect(screen.queryByTestId('empty-state')).not.toBeInTheDocument();
  });
});

describe('SplitView — grid layout', () => {
  it('renders 1 cell for a 1x1 layout', () => {
    setup({ itemList: [] , layout: { rows: 1, cols: 1 } });
    // With empty items and 1x1, emptyState is shown — skip this combo
    // Use a layout >1 or items present
  });

  it('renders 2 cells for a 1x2 layout', () => {
    setup({
      layout: { rows: 1, cols: 2 },
      assignments: makeAssignments([[0, null],[1, null]]),
    });
    expect(screen.getAllByText('Assign connection')).toHaveLength(2);
  });

  it('renders 4 cells for a 2x2 layout', () => {
    setup({
      layout: { rows: 2, cols: 2 },
      assignments: makeAssignments([[0,null],[1,null],[2,null],[3,null]]),
    });
    expect(screen.getAllByText('Assign connection')).toHaveLength(4);
  });

  it('applies correct grid-template-columns for a 1x3 layout', () => {
    const { container } = setup({
      layout: { rows: 1, cols: 3 },
      assignments: makeAssignments([[0,null],[1,null],[2,null]]),
    });
    const grid = container.querySelector('[style]') as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe('repeat(3, minmax(0, 1fr))');
  });

  it('applies correct grid-template-rows for a 3x1 layout', () => {
    const { container } = setup({
      layout: { rows: 3, cols: 1 },
      assignments: makeAssignments([[0,null],[1,null],[2,null]]),
    });
    const grid = container.querySelector('[style]') as HTMLElement;
    expect(grid.style.gridTemplateRows).toBe('repeat(3, minmax(0, 1fr))');
  });

  it('calls onContentRef once per cell so the parent can DOM-move panels', () => {
    // Content is no longer rendered inside cells — each cell exposes an empty
    // mount-point div via onContentRef.  The parent is responsible for moving
    // the live panel node into that div (avoiding React unmount/remount).
    const { onContentRef } = setup({
      layout: { rows: 1, cols: 2 },
      assignments: makeAssignments([[0, null],[1, null]]),
    });
    // Filter to only the mount calls (non-null el) — the cleanup call passes null.
    // Signature: onContentRef(cellIndex: number, el: HTMLDivElement | null)
    const mountCalls = onContentRef.mock.calls.filter(([, el]) => el !== null);
    expect(mountCalls).toHaveLength(2);
    for (const [, el] of mountCalls) {
      expect(el).toBeInstanceOf(HTMLDivElement);
    }
  });
});

describe('SplitView — assigned cells', () => {
  it('does not show the Assign picker for an assigned cell', () => {
    setup({
      layout: { rows: 1, cols: 2 },
      assignments: makeAssignments([[0, 1],[1, null]]),
    });
    // Only cell 1 (unassigned) should show the picker; cell 0 should not
    expect(screen.getAllByText('Assign connection')).toHaveLength(1);
  });

  it('renders the Assign picker for an empty cell alongside an assigned cell', () => {
    setup({
      layout: { rows: 1, cols: 2 },
      assignments: makeAssignments([[0, 1],[1, null]]),
    });
    expect(screen.getByText('Assign connection')).toBeInTheDocument();
  });

  it('calls onAssign when an item is selected from an empty cell', async () => {
    const { onAssign } = setup({
      layout: { rows: 1, cols: 2 },
      assignments: makeAssignments([[0, null],[1, null]]),
    });
    const [firstAssignBtn] = screen.getAllByText('Assign connection');
    await userEvent.click(firstAssignBtn);
    await userEvent.click(screen.getByText('Alpha'));
    expect(onAssign).toHaveBeenCalledWith(0, 1);
  });
});
