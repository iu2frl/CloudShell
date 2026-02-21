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
 * - assigned cell renders children content instead of the picker
 * - assigned cell shows the unassign (X) button
 * - clicking the unassign button calls onAssign(index, null)
 * - clicking the cell calls onFocus with the cell index
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
  const onAssign = vi.fn();
  const onFocus  = vi.fn();
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
    >
      {(item) => <div data-testid="content">{item.name}</div>}
    </GridCell>,
  );
  return { onAssign, onFocus };
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
  it('renders the children content when a key is assigned', () => {
    setup(1); // item with id=1 is "Server Alpha"
    expect(screen.getByTestId('content')).toHaveTextContent('Server Alpha');
  });

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
});

describe('GridCell — focus', () => {
  it('calls onFocus when the cell is clicked', async () => {
    const { onFocus } = setup(null);
    // Click somewhere on the cell wrapper (not the button)
    await userEvent.click(screen.getByText('Assign connection').closest('div.relative')!.parentElement!);
    expect(onFocus).toHaveBeenCalledWith(0);
  });

  it('applies focused ring classes when isFocused is true', () => {
    const onAssign = vi.fn();
    const onFocus  = vi.fn();
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
      >
        {(item) => <span>{item.name}</span>}
      </GridCell>,
    );
    const cell = container.firstChild as HTMLElement;
    expect(cell.className).toContain('ring-blue-500');
  });
});
