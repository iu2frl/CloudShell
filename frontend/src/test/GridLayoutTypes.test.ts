/**
 * tests for GridLayoutTypes.ts
 *
 * Covers:
 * - cellCount returns rows * cols for every preset and edge cases
 * - LAYOUT_PRESETS contains exactly the four documented presets
 * - every preset has a valid icon string and matching layout
 */

import { describe, it, expect } from 'vitest';
import { cellCount, LAYOUT_PRESETS } from '../components/splitview/GridLayoutTypes';

describe('cellCount', () => {
  it('returns 1 for a 1x1 layout', () => {
    expect(cellCount({ rows: 1, cols: 1 })).toBe(1);
  });

  it('returns 2 for a 1x2 (vertical split) layout', () => {
    expect(cellCount({ rows: 1, cols: 2 })).toBe(2);
  });

  it('returns 2 for a 2x1 (horizontal split) layout', () => {
    expect(cellCount({ rows: 2, cols: 1 })).toBe(2);
  });

  it('returns 4 for a 2x2 grid', () => {
    expect(cellCount({ rows: 2, cols: 2 })).toBe(4);
  });

  it('returns 12 for a 3x4 grid', () => {
    expect(cellCount({ rows: 3, cols: 4 })).toBe(12);
  });

  it('returns 16 for the maximum 4x4 grid', () => {
    expect(cellCount({ rows: 4, cols: 4 })).toBe(16);
  });
});

describe('LAYOUT_PRESETS', () => {
  it('contains exactly four presets', () => {
    expect(LAYOUT_PRESETS).toHaveLength(4);
  });

  it('first preset is single pane (1x1)', () => {
    expect(LAYOUT_PRESETS[0].layout).toEqual({ rows: 1, cols: 1 });
  });

  it('second preset is vertical split (1x2)', () => {
    expect(LAYOUT_PRESETS[1].layout).toEqual({ rows: 1, cols: 2 });
  });

  it('third preset is horizontal split (2x1)', () => {
    expect(LAYOUT_PRESETS[2].layout).toEqual({ rows: 2, cols: 1 });
  });

  it('fourth preset is 2x2 grid', () => {
    expect(LAYOUT_PRESETS[3].layout).toEqual({ rows: 2, cols: 2 });
  });

  it('every preset has a non-empty label, description, and icon', () => {
    for (const preset of LAYOUT_PRESETS) {
      expect(preset.label.length).toBeGreaterThan(0);
      expect(preset.description.length).toBeGreaterThan(0);
      expect(preset.icon.length).toBeGreaterThan(0);
    }
  });
});
