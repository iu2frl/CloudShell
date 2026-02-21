/**
 * Regression tests for the DOM-move panel management logic in Dashboard.tsx.
 *
 * The full Dashboard component requires mocked API routes and WebSocket
 * infrastructure.  Instead we test the DOM-move algorithm in isolation by
 * replicating its core logic with real DOM nodes.
 *
 * Covers:
 * - moving a panel into a cell mount-point shows it correctly
 * - closing a tab whose panel is live in a cell does NOT throw "removeChild"
 * - stale (detached) panel refs are cleaned up from panelRefsMap silently
 * - panels for remaining tabs keep working after a sibling tab is closed
 * - "terminal-fit" custom event is dispatched every time a panel is shown
 */

import { describe, it, expect } from 'vitest';

type PanelRefsMap = Map<number, HTMLDivElement>;

/**
 * Minimal re-implementation of the DOM-move effect from Dashboard.tsx so we
 * can unit-test it without mounting the full component tree.
 */
function runDomMoveEffect(
  panelRefsMap: PanelRefsMap,
  cellRefsMap: Map<number, HTMLDivElement | null>,
  assignments: Map<number, number | null>,
  pool: HTMLDivElement,
): void {
  // Step 1 — hide all panels and return them to the pool (skip detached nodes)
  for (const [key, panelEl] of panelRefsMap) {
    if (!document.contains(panelEl)) {
      panelRefsMap.delete(key);
      continue;
    }
    panelEl.style.display = 'none';
    if (panelEl.parentElement !== pool) pool.appendChild(panelEl);
  }
  // Step 2 — move assigned panels into their cell mount-points
  for (const [cellIdx, key] of assignments) {
    if (key === null) continue;
    const panelEl = panelRefsMap.get(key);
    const cellEl  = cellRefsMap.get(cellIdx);
    if (!panelEl || !cellEl) continue;
    if (!document.contains(panelEl)) {
      panelRefsMap.delete(key);
      continue;
    }
    if (panelEl.parentElement !== cellEl) cellEl.appendChild(panelEl);
    panelEl.style.display = '';
    // Mirrors Dashboard: notify the terminal inside to re-fit after show
    panelEl.dispatchEvent(new CustomEvent('terminal-fit', { bubbles: true }));
  }
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function makePool(): HTMLDivElement {
  const pool = document.createElement('div');
  document.body.appendChild(pool);
  return pool;
}

function makePanel(pool: HTMLDivElement): HTMLDivElement {
  const panel = document.createElement('div');
  pool.appendChild(panel);
  return panel;
}

function makeCell(): HTMLDivElement {
  const cell = document.createElement('div');
  document.body.appendChild(cell);
  return cell;
}

// ─── tests ────────────────────────────────────────────────────────────────────

describe('DOM-move effect — panel lifecycle', () => {
  it('moves an assigned panel from the pool into its cell mount-point', () => {
    const pool   = makePool();
    const cell   = makeCell();
    const panel  = makePanel(pool);

    const panelRefs: PanelRefsMap      = new Map([[1, panel]]);
    const cellRefs                     = new Map([[0, cell]]);
    const assignments: Map<number, number | null> = new Map([[0, 1]]);

    runDomMoveEffect(panelRefs, cellRefs, assignments, pool);

    expect(panel.parentElement).toBe(cell);
    expect(panel.style.display).toBe('');
  });

  it('returns a panel to the pool when its cell assignment is cleared', () => {
    const pool  = makePool();
    const cell  = makeCell();
    const panel = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);
    const cellRefs                = new Map([[0, cell]]);

    // First run — assign panel to cell
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    expect(panel.parentElement).toBe(cell);

    // Second run — clear assignment
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, null]]), pool);
    expect(panel.parentElement).toBe(pool);
    expect(panel.style.display).toBe('none');
  });

  it('does NOT throw when a tab is closed and its panel is still assigned to a cell', () => {
    // This is the exact crash scenario:
    //   1. Panel is in a cell (not the pool).
    //   2. User closes the tab → React removes the panel div from the DOM.
    //   3. DOM-move effect runs with a now-detached panelEl still in panelRefsMap.
    //   4. Without the guard, pool.appendChild(detachedNode) causes React's
    //      internal removeChild to fail with "The node to be removed is not a
    //      child of this node."
    const pool  = makePool();
    const cell  = makeCell();
    const panel = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);
    const cellRefs                = new Map([[0, cell]]);

    // Simulate the tab being open and assigned
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    expect(panel.parentElement).toBe(cell);

    // Simulate React removing the panel node (tab closed)
    panel.parentElement!.removeChild(panel);
    // panel is now detached — document.contains(panel) === false

    // This must NOT throw
    expect(() => {
      runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    }).not.toThrow();
  });

  it('cleans up the stale ref from panelRefsMap after the panel is detached', () => {
    const pool  = makePool();
    const cell  = makeCell();
    const panel = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);
    const cellRefs                = new Map([[0, cell]]);

    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);

    // Remove panel from DOM (simulates tab close)
    panel.parentElement!.removeChild(panel);

    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);

    // Stale ref must have been pruned
    expect(panelRefs.has(1)).toBe(false);
  });

  it('keeps remaining panels working after a sibling tab is closed', () => {
    const pool   = makePool();
    const cell0  = makeCell();
    const cell1  = makeCell();
    const panel1 = makePanel(pool);
    const panel2 = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel1], [2, panel2]]);
    const cellRefs                = new Map([[0, cell0], [1, cell1]]);

    // Both tabs assigned to cells
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1], [1, 2]]), pool);
    expect(panel1.parentElement).toBe(cell0);
    expect(panel2.parentElement).toBe(cell1);

    // Close tab 1 — remove panel1 from DOM
    panel1.parentElement!.removeChild(panel1);

    // Run effect with only tab 2 remaining
    expect(() => {
      runDomMoveEffect(panelRefs, cellRefs, new Map([[0, null], [1, 2]]), pool);
    }).not.toThrow();

    // panel2 should still be alive in cell1
    expect(panel2.parentElement).toBe(cell1);
    expect(panel2.style.display).toBe('');
    // stale ref cleaned up
    expect(panelRefs.has(1)).toBe(false);
    expect(panelRefs.has(2)).toBe(true);
  });
});

// ─── ref-cleanup helper ───────────────────────────────────────────────────────
// Models the ref callback in Dashboard.tsx that fires when React unmounts a
// pool div.  Before deleting the entry from panelRefsMap it moves the node
// back to the pool so React finds it where it expects it.

function simulateRefCleanup(
  key: number,
  panelRefs: PanelRefsMap,
  pool: HTMLDivElement,
): void {
  const panelEl = panelRefs.get(key);
  if (panelEl && pool && panelEl.parentElement !== pool) {
    pool.appendChild(panelEl);
  }
  panelRefs.delete(key);
}

describe('DOM-move effect — last tab close regression', () => {
  it('does NOT throw when the only open tab is closed while its panel is in a cell', () => {
    // Scenario:
    //   1. Single tab assigned to cell 0 — DOM-move effect moves panel into cell.
    //   2. User closes the last tab.
    //   3. React fires the pool-div ref callback with null.
    //   4. The ref cleanup must move the panel back to the pool BEFORE React
    //      calls pool.removeChild(panel) — otherwise it throws because the
    //      panel is sitting in the cell, not the pool.
    const pool  = makePool();
    const cell  = makeCell();
    const panel = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);
    const cellRefs                = new Map([[0, cell]]);

    // Panel is moved into the cell
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    expect(panel.parentElement).toBe(cell);

    // Simulate ref cleanup (fires before React removes the node)
    simulateRefCleanup(1, panelRefs, pool);

    // Panel must now be back in the pool so React can remove it cleanly
    expect(panel.parentElement).toBe(pool);

    // Simulating React's removeChild must not throw
    expect(() => pool.removeChild(panel)).not.toThrow();

    // Ref map is cleared
    expect(panelRefs.has(1)).toBe(false);
  });

  it('ref cleanup is a no-op when the panel is already in the pool', () => {
    // If the panel was never moved out (e.g. tab was never focused), the
    // cleanup path must still work without errors.
    const pool  = makePool();
    const panel = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);

    expect(() => simulateRefCleanup(1, panelRefs, pool)).not.toThrow();
    expect(panel.parentElement).toBe(pool); // still in pool, not moved
    expect(panelRefs.has(1)).toBe(false);
  });

  it('closing the last of three tabs does NOT throw', () => {
    // Open 3 tabs in a 1x1 grid (only the most recently auto-placed tab is
    // visible).  Close them one at a time.  The final close is the regression.
    const pool   = makePool();
    const cell   = makeCell();
    const panel1 = makePanel(pool);
    const panel2 = makePanel(pool);
    const panel3 = makePanel(pool);

    const panelRefs: PanelRefsMap = new Map([[1, panel1], [2, panel2], [3, panel3]]);
    const cellRefs                = new Map([[0, cell]]);

    // In a 1x1 grid only the last-placed tab occupies cell 0
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 3]]), pool);
    expect(panel3.parentElement).toBe(cell);
    expect(panel1.parentElement).toBe(pool);
    expect(panel2.parentElement).toBe(pool);

    // Close tab 1 (not in cell — easy case)
    simulateRefCleanup(1, panelRefs, pool);
    pool.removeChild(panel1); // React removes it

    // Close tab 2 (also in pool — easy case)
    simulateRefCleanup(2, panelRefs, pool);
    pool.removeChild(panel2);

    // Close tab 3 — it is in the cell, not the pool: this is the regression
    simulateRefCleanup(3, panelRefs, pool);
    expect(panel3.parentElement).toBe(pool); // moved back before React acts
    expect(() => pool.removeChild(panel3)).not.toThrow();

    expect(panelRefs.size).toBe(0);
  });
});

describe('DOM-move effect — terminal-fit dispatch', () => {
  it('dispatches "terminal-fit" on the panel when it is moved into a cell', () => {
    const pool  = makePool();
    const cell  = makeCell();
    const panel = makePanel(pool);

    let fitCount = 0;
    panel.addEventListener('terminal-fit', () => { fitCount++; });

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);
    const cellRefs                = new Map([[0, cell]]);

    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);

    expect(fitCount).toBe(1);
  });

  it('dispatches "terminal-fit" on every subsequent show (tab switch back)', () => {
    // When the user switches away and back, the panel goes pool → cell → pool
    // → cell.  Each time it becomes visible it must get a fit event.
    const pool  = makePool();
    const cell  = makeCell();
    const panel = makePanel(pool);

    let fitCount = 0;
    panel.addEventListener('terminal-fit', () => { fitCount++; });

    const panelRefs: PanelRefsMap = new Map([[1, panel]]);
    const cellRefs                = new Map([[0, cell]]);

    // First show
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    expect(fitCount).toBe(1);

    // Hide (switch away)
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, null]]), pool);
    expect(fitCount).toBe(1); // no extra event while hidden

    // Second show (switch back)
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    expect(fitCount).toBe(2);
  });

  it('does NOT dispatch "terminal-fit" for panels that remain hidden', () => {
    // In a 1x1 grid with two tabs, only the assigned tab should get the event.
    const pool   = makePool();
    const cell   = makeCell();
    const panel1 = makePanel(pool);
    const panel2 = makePanel(pool);

    let fit1 = 0;
    let fit2 = 0;
    panel1.addEventListener('terminal-fit', () => { fit1++; });
    panel2.addEventListener('terminal-fit', () => { fit2++; });

    const panelRefs: PanelRefsMap = new Map([[1, panel1], [2, panel2]]);
    const cellRefs                = new Map([[0, cell]]);

    // Only tab 1 assigned
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);

    expect(fit1).toBe(1); // assigned tab got the event
    expect(fit2).toBe(0); // hidden tab did not
  });

  it('dispatches "terminal-fit" when switching from one tab to another in single-tile mode', () => {
    // The half-terminal regression: opening a second connection in 1x1 mode
    // caused the terminal to stay sized at the pool dimensions (zero / wrong).
    // After the fix, the newly-shown terminal must always receive a fit event.
    const pool   = makePool();
    const cell   = makeCell();
    const panel1 = makePanel(pool);
    const panel2 = makePanel(pool);

    let fit1 = 0;
    let fit2 = 0;
    panel1.addEventListener('terminal-fit', () => { fit1++; });
    panel2.addEventListener('terminal-fit', () => { fit2++; });

    const panelRefs: PanelRefsMap = new Map([[1, panel1], [2, panel2]]);
    const cellRefs                = new Map([[0, cell]]);

    // Tab 1 opens first
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 1]]), pool);
    expect(fit1).toBe(1);
    expect(fit2).toBe(0);

    // Tab 2 replaces tab 1 in the single cell (autoPlace eviction)
    runDomMoveEffect(panelRefs, cellRefs, new Map([[0, 2]]), pool);
    expect(fit1).toBe(1); // tab 1 now hidden — no new event
    expect(fit2).toBe(1); // tab 2 just became visible — must get the event
  });
});
