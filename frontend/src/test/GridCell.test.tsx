/**
 * tests for GridCell.tsx
 *
 * Covers:
 * - empty cell shows "Assign connection" button when items are available
 * - empty cell shows a hint message when no items are available
 * - clicking "Assign connection" opens the dropdown
 * - dropdown lists all available items by label
 * - selecting an item from the dropdown calls onAssign with the correct key
 * - selecting an item closes the dropdown
 * - clicking the backdrop closes the dropdown without calling onAssign
 * - assigned cell shows the unassign (X) button (content is DOM-moved externally)
 * - assigned cell does NOT show the assign picker
 * - clicking the unassign button calls onAssign(index, null)
 * - clicking the cell calls onFocus with the cell index
 * - onContentRef is called with the mount-point div on mount
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GridCell } from '../components/splitview/GridCell';

interface Item { id: number; name: string }
const items: Item[] = [
  { id: 1, name: 'Server Alpha' },
  { id: 2, name: 'Server Beta' },
];

function setup(assignedKey: number | null = null, itemList = items) {
  const onAssign     = vi.fn();
  const onFocus      = vi.fn();
  const onContentRef = vi.fn();
  render(
    <GridCell<number, Item>
      index={0}
      isFocused={false}
      assignedKey={assignedKey}
      items={itemList}
      getKey={(item) => item.id}
      getLabel={(item) => item.name}
      onAssign={onAssign}
      onFocus={onFocus}
      onContentRef={onContentRef}
    />,
  );
  return { onAssign, onFocus, onContentRef };
}

describe('GridCell — empty state', () => {
  it('shows the Assign connection button when items are available', () => {
    setup(null);
    expect(screen.getByText('Assign connection')).toBeInTheDocument();
  });

  it('shows a hint when no items are available', () => {
    setup(null, []);
    expect(screen.getByText('Connect to a device first')).toBeInTheDocument();
    expect(screen.queryByText('Assign connection')).not.toBeInTheDocument();
  });

  it('opens the dropdown when Assign connection is clicked', async () => {
    setup(null);
    await userEvent.click(screen.getByText('Assign connection'));
    expect(screen.getByText('Server Alpha')).toBeInTheDocument();
    expect(screen.getByText('Server Beta')).toBeInTheDocument();
  });

  it('calls onAssign with the item key when an item is selected', async () => {
    const { onAssign } = setup(null);
    await userEvent.click(screen.getByText('Assign connection'));
    await userEvent.click(screen.getByText('Server Alpha'));
    expect(onAssign).toHaveBeenCalledWith(0, 1);
  });

  it('calls onFocus when an item is selected', async () => {
    const { onFocus } = setup(null);
    await userEvent.click(screen.getByText('Assign connection'));
    await userEvent.click(screen.getByText('Server Beta'));
    expect(onFocus).toHaveBeenCalledWith(0);
  });

  it('closes the dropdown after an item is selected', async () => {
    setup(null);
    await userEvent.click(screen.getByText('Assign connection'));
    await userEvent.click(screen.getByText('Server Alpha'));
    expect(screen.queryByText('Server Alpha')).not.toBeInTheDocument();
  });

  it('closes the dropdown when clicking the backdrop without calling onAssign', async () => {
    const { onAssign } = setup(null);
    await userEvent.click(screen.getByText('Assign connection'));
    const backdrop = document.querySelector('.fixed.inset-0') as HTMLElement;
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop);
    expect(screen.queryByText('Server Alpha')).not.toBeInTheDocument();
    expect(onAssign).not.toHaveBeenCalled();
  });
});

describe('GridCell — assigned state', () => {
  it('does not show the Assign connection button when assigned', () => {
    setup(1);
    expect(screen.queryByText('Assign connection')).not.toBeInTheDocument();
  });

  it('shows the unassign (X) button', () => {
    setup(1);
    expect(screen.getByTitle('Remove from this pane')).toBeInTheDocument();
  });

  it('calls onAssign(index, null) when the unassign button is clicked', async () => {
    const { onAssign } = setup(1);
    await userEvent.click(screen.getByTitle('Remove from this pane'));
    expect(onAssign).toHaveBeenCalledWith(0, null);
  });

  it('pointerdown on the unassign button also focuses the cell (capture fires before bubble stopPropagation)', () => {
    // The capture-phase listener on the wrapper fires before any child's
    // bubble-phase stopPropagation can silence it — so clicking the unassign
    // button correctly marks this cell as focused.
    const { onFocus } = setup(1);
    fireEvent.pointerDown(screen.getByTitle('Remove from this pane'));
    expect(onFocus).toHaveBeenCalledWith(0);
  });

  it('calls onContentRef with the mount-point div on mount', () => {
    // Content is no longer rendered by GridCell itself; it exposes an empty
    // mount-point div via onContentRef so the parent can DOM-move the live
    // panel in without unmounting it.
    const { onContentRef } = setup(1);
    expect(onContentRef).toHaveBeenCalledTimes(1);
    expect(onContentRef.mock.calls[0][0]).toBeInstanceOf(HTMLDivElement);
  });
});

describe('GridCell — focus', () => {
  it('calls onFocus on pointerdown on the cell wrapper', () => {
    const { onFocus } = setup(null);
    const cell = screen.getByText('Assign connection').closest('div.relative')!.parentElement!;
    fireEvent.pointerDown(cell);
    expect(onFocus).toHaveBeenCalledWith(0);
  });

  it('calls onFocus when pointerdown is fired on a child that calls stopPropagation (xterm scenario)', () => {
    // xterm.js registers its own pointerdown listener on the canvas and calls
    // stopPropagation(), which would silence a bubble-phase onPointerDown on
    // the cell wrapper.  The fix is a capture-phase listener on the wrapper,
    // which fires BEFORE any child bubble handler can stop propagation.
    const { onFocus, onContentRef } = setup(1);
    // The content div is the mount-point that xterm would be placed inside
    const contentDiv = onContentRef.mock.calls[0][0] as HTMLDivElement;

    // Add a bubble-phase stopPropagation listener on the child, exactly as
    // xterm does — this would break an onPointerDown on the parent wrapper
    contentDiv.addEventListener('pointerdown', (e) => e.stopPropagation());
    // Fire pointerdown on the child
    fireEvent.pointerDown(contentDiv);

    // Capture-phase listener on the wrapper MUST have fired despite stopPropagation
    expect(onFocus).toHaveBeenCalledWith(0);
  });

  it('does not call onFocus when click fires without pointerdown (regression guard)', () => {
    // Confirms that click alone no longer triggers focus — the old onClick
    // handler was replaced with a capture-phase pointerdown listener
    const { onFocus } = setup(null);
    const cell = screen.getByText('Assign connection').closest('div.relative')!.parentElement!;
    fireEvent.click(cell);
    // click on the wrapper div itself (no onFocus there anymore) — but the
    // "Assign connection" button's onClick calls stopPropagation, so reaching
    // the wrapper means we clicked outside the button; onFocus should NOT fire
    expect(onFocus).not.toHaveBeenCalled();
  });

  it('applies focused ring classes when isFocused is true', () => {
    const onAssign     = vi.fn();
    const onFocus      = vi.fn();
    const onContentRef = vi.fn();
    const { container } = render(
      <GridCell<number, Item>
        index={2}
        isFocused={true}
        assignedKey={null}
        items={[]}
        getKey={(item) => item.id}
        getLabel={(item) => item.name}
        onAssign={onAssign}
        onFocus={onFocus}
        onContentRef={onContentRef}
      />,
    );
    const cell = container.firstChild as HTMLElement;
    expect(cell.className).toContain('ring-blue-500');
  });
});
