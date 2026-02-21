/**
 * tests for LayoutPicker.tsx
 *
 * Covers:
 * - renders all four preset buttons
 * - clicking a preset calls onSelect with the correct layout
 * - the active preset button has the active CSS class
 * - the custom grid button opens the popover
 * - the popover renders row and column controls
 * - the +/- controls increment and decrement correctly
 * - the +/- controls are clamped at 1 (min) and 4 (max)
 * - clicking Apply calls onSelect with the custom layout
 * - clicking the backdrop closes the popover without calling onSelect
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LayoutPicker } from '../components/splitview/LayoutPicker';
import type { GridLayout } from '../components/splitview/GridLayoutTypes';

function setup(current: GridLayout = { rows: 1, cols: 1 }) {
  const onSelect = vi.fn();
  render(<LayoutPicker current={current} onSelect={onSelect} />);
  return { onSelect };
}

describe('LayoutPicker — preset buttons', () => {
  it('renders four preset buttons', () => {
    setup();
    // Each preset has an aria-label set to its description
    expect(screen.getByLabelText('Single pane')).toBeInTheDocument();
    expect(screen.getByLabelText('Vertical split')).toBeInTheDocument();
    expect(screen.getByLabelText('Horizontal split')).toBeInTheDocument();
    expect(screen.getByLabelText('2x2 grid')).toBeInTheDocument();
  });

  it('calls onSelect with { rows:1, cols:1 } when Single pane is clicked', async () => {
    const { onSelect } = setup({ rows: 2, cols: 2 });
    await userEvent.click(screen.getByLabelText('Single pane'));
    expect(onSelect).toHaveBeenCalledWith({ rows: 1, cols: 1 });
  });

  it('calls onSelect with { rows:1, cols:2 } when Vertical split is clicked', async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByLabelText('Vertical split'));
    expect(onSelect).toHaveBeenCalledWith({ rows: 1, cols: 2 });
  });

  it('calls onSelect with { rows:2, cols:1 } when Horizontal split is clicked', async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByLabelText('Horizontal split'));
    expect(onSelect).toHaveBeenCalledWith({ rows: 2, cols: 1 });
  });

  it('calls onSelect with { rows:2, cols:2 } when 2x2 grid is clicked', async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByLabelText('2x2 grid'));
    expect(onSelect).toHaveBeenCalledWith({ rows: 2, cols: 2 });
  });

  it('applies active styling to the button matching the current layout', () => {
    setup({ rows: 2, cols: 2 });
    const activeBtn = screen.getByLabelText('2x2 grid');
    expect(activeBtn.className).toContain('bg-blue-600/30');
  });

  it('does not apply active styling to non-current presets', () => {
    setup({ rows: 1, cols: 1 });
    const inactiveBtn = screen.getByLabelText('Vertical split');
    expect(inactiveBtn.className).not.toContain('bg-blue-600/30');
  });
});

describe('LayoutPicker — custom grid popover', () => {
  it('popover is hidden initially', () => {
    setup();
    expect(screen.queryByText('Custom grid')).not.toBeInTheDocument();
  });

  it('opens the popover when Custom grid button is clicked', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    expect(screen.getByText('Custom grid')).toBeInTheDocument();
  });

  it('shows Rows and Cols labels in the popover', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    expect(screen.getByText('Rows')).toBeInTheDocument();
    expect(screen.getByText('Cols')).toBeInTheDocument();
  });

  it('increments rows when the Rows + button is clicked', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    // Rows control: the + button follows the "Rows" label
    const [rowPlus] = screen.getAllByText('+');
    await userEvent.click(rowPlus);
    // Default starts at 2; after one click both rows=3, so Apply shows "Apply 3x..."
    expect(screen.getByText(/^Apply 3x/)).toBeInTheDocument();
  });

  it('decrements rows when the Rows - button is clicked', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    const [rowMinus] = screen.getAllByText('-');
    // Default rows = 2; after one click should be 1
    await userEvent.click(rowMinus);
    // The value "1" appears; confirm the Apply button label updated
    expect(screen.getByText(/Apply 1x/)).toBeInTheDocument();
  });

  it('does not decrement rows below 1', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    const [rowMinus] = screen.getAllByText('-');
    // Default is 2; click twice — second click should be blocked
    await userEvent.click(rowMinus);
    await userEvent.click(rowMinus);
    expect(screen.getByText(/Apply 1x/)).toBeInTheDocument();
  });

  it('does not increment rows above 4', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    const [rowPlus] = screen.getAllByText('+');
    // Click 5 times from default 2 — should cap at 4
    for (let i = 0; i < 5; i++) await userEvent.click(rowPlus);
    expect(screen.getByText(/Apply 4x/)).toBeInTheDocument();
  });

  it('calls onSelect with the custom layout when Apply is clicked', async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    // Increment cols once (default 3 → 4) using the second + button
    const plusBtns = screen.getAllByText('+');
    await userEvent.click(plusBtns[1]); // cols +
    await userEvent.click(screen.getByText(/^Apply/));
    expect(onSelect).toHaveBeenCalledWith({ rows: 2, cols: 4 });
  });

  it('closes the popover after Apply is clicked', async () => {
    setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    await userEvent.click(screen.getByText(/^Apply/));
    expect(screen.queryByText('Custom grid')).not.toBeInTheDocument();
  });

  it('closes the popover when clicking the backdrop', async () => {
    const { onSelect } = setup();
    await userEvent.click(screen.getByLabelText('Custom grid'));
    // The backdrop is a fixed inset-0 div — click it
    const backdrop = document.querySelector('.fixed.inset-0') as HTMLElement;
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop);
    expect(screen.queryByText('Custom grid')).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
