/**
 * LayoutPicker — toolbar widget for choosing the grid layout.
 *
 * Shows preset buttons (1, 1|1, 1/1, 2x2) and a custom rows×cols popover.
 * Purely presentational: calls onSelect with the chosen GridLayout.
 */

import { useRef, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { GridLayout, LAYOUT_PRESETS } from "./GridLayoutTypes";

interface Props {
  current: GridLayout;
  onSelect: (layout: GridLayout) => void;
}

const MAX_DIM = 4;

export function LayoutPicker({ current, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [customRows, setCustomRows] = useState(2);
  const [customCols, setCustomCols] = useState(3);
  const btnRef = useRef<HTMLButtonElement>(null);

  const isActive = (l: GridLayout) =>
    l.rows === current.rows && l.cols === current.cols;

  return (
    <div className="relative flex items-center gap-1">
      {/* ── Preset buttons ────────────────────────────────────────────────── */}
      {LAYOUT_PRESETS.map((preset) => (
        <button
          key={preset.label}
          title={preset.description}
          aria-label={preset.description}
          onClick={() => { onSelect(preset.layout); setOpen(false); }}
          className={`icon-btn px-2 py-1 text-xs font-mono transition-colors
            ${isActive(preset.layout)
              ? "bg-blue-600/30 text-blue-300 border border-blue-600/50"
              : "text-slate-400 border border-transparent hover:text-white"
            }`}
        >
          <svg
            viewBox="0 0 20 20"
            width={16}
            height={16}
            fill="currentColor"
            aria-hidden
          >
            <path d={preset.icon} />
          </svg>
        </button>
      ))}

      {/* ── Custom grid button ────────────────────────────────────────────── */}
      <button
        ref={btnRef}
        title="Custom grid"
        aria-label="Custom grid"
        onClick={() => setOpen((v) => !v)}
        className={`icon-btn px-2 py-1 text-xs transition-colors
          ${open
            ? "bg-blue-600/30 text-blue-300 border border-blue-600/50"
            : "text-slate-400 border border-transparent hover:text-white"
          }`}
      >
        <LayoutGrid size={15} />
      </button>

      {/* ── Custom grid popover ───────────────────────────────────────────── */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
          />
          <div className="absolute top-full right-0 mt-2 z-20 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-4 w-48">
            <p className="text-xs font-medium text-slate-300 mb-3">Custom grid</p>

            <div className="flex flex-col gap-3">
              <DimControl
                label="Rows"
                value={customRows}
                onChange={setCustomRows}
              />
              <DimControl
                label="Cols"
                value={customCols}
                onChange={setCustomCols}
              />
            </div>

            <button
              className="btn-primary w-full mt-4 py-1.5 text-xs"
              onClick={() => {
                onSelect({ rows: customRows, cols: customCols });
                setOpen(false);
              }}
            >
              Apply {customRows}x{customCols}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Small +/- spinner ──────────────────────────────────────────────────────── */
interface DimControlProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
}

function DimControl({ label, value, onChange }: DimControlProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-slate-400 w-8">{label}</span>
      <div className="flex items-center gap-1">
        <button
          className="icon-btn w-6 h-6 flex items-center justify-center text-base leading-none"
          onClick={() => onChange(Math.max(1, value - 1))}
          disabled={value <= 1}
        >
          -
        </button>
        <span className="text-sm text-slate-200 w-4 text-center select-none">
          {value}
        </span>
        <button
          className="icon-btn w-6 h-6 flex items-center justify-center text-base leading-none"
          onClick={() => onChange(Math.min(MAX_DIM, value + 1))}
          disabled={value >= MAX_DIM}
        >
          +
        </button>
      </div>
    </div>
  );
}
