/**
 * GridCell — a single cell in the split-view grid.
 *
 * Generic over TKey and TItem so it is reusable beyond SSH terminals.
 *
 * Content is NOT rendered here. The cell only provides:
 *   - the focus ring / border chrome
 *   - an empty content slot (div) whose ref is passed up via onContentRef so
 *     the parent can portal the live panel into it without unmounting it
 *   - the unassign overlay button when a key is assigned
 *   - the "assign" dropdown when the cell is empty
 *
 * Props
 * ──────
 *  index          Cell index (row * cols + col)
 *  isFocused      Whether this cell has the "active" highlight
 *  assignedKey    The key currently assigned to this cell (null = empty)
 *  items          All available items the user can assign
 *  getKey         (item) => TKey
 *  getLabel       (item) => string shown in the dropdown
 *  onAssign       (cellIndex, key | null) => void
 *  onFocus        (cellIndex) => void
 *  onContentRef   (cellIndex, el | null) => void — called with the content div ref
 */

import { useEffect, useRef, useState } from "react";
import { Plus, X } from "lucide-react";

interface GridCellProps<TKey, TItem> {
  index: number;
  isFocused: boolean;
  assignedKey: TKey | null;
  items: TItem[];
  getKey: (item: TItem) => TKey;
  getLabel: (item: TItem) => string;
  onAssign: (cellIndex: number, key: TKey | null) => void;
  onFocus: (cellIndex: number) => void;
  /** Called with the content mount-point div when it mounts/unmounts. */
  onContentRef: (el: HTMLDivElement | null) => void;
}

export function GridCell<TKey, TItem>({
  index,
  isFocused,
  assignedKey,
  items,
  getKey,
  getLabel,
  onAssign,
  onFocus,
  onContentRef,
}: GridCellProps<TKey, TItem>) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  // Notify parent whenever the content div mounts or unmounts
  useEffect(() => {
    onContentRef(contentRef.current);
    return () => { onContentRef(null); };
  // onContentRef is stable (useCallback in SplitView) so this only fires once
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  const isAssigned = assignedKey !== null;
  const hasItems   = items.length > 0;

  const handleFocus = () => onFocus(index);

  return (
    <div
      onClick={handleFocus}
      className={`relative flex flex-col overflow-hidden rounded-lg transition-shadow duration-150
        ${isFocused
          ? "ring-2 ring-blue-500/60 ring-offset-1 ring-offset-surface"
          : "ring-1 ring-slate-700/50"
        }`}
    >
      {isAssigned ? (
        <>
          {/* ── Assigned: empty slot — content is portalled in from outside ── */}
          <div ref={contentRef} className="flex-1 overflow-hidden" />

          {/* ── Unassign button (top-right corner overlay) ────────────────── */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onAssign(index, null);
            }}
            title="Remove from this pane"
            className="absolute top-1 right-1 z-10 p-0.5 rounded bg-slate-900/70 text-slate-400
                       hover:text-red-400 hover:bg-slate-900 transition-colors opacity-0
                       group-hover:opacity-100 focus:opacity-100"
            style={{ opacity: undefined }} // let CSS handle via parent :hover
          >
            <X size={11} />
          </button>
        </>
      ) : (
        /* ── Empty: content slot hidden + assign picker ─────────────────── */
        <>
          <div ref={contentRef} className="hidden" />
          <div className="flex-1 flex items-center justify-center bg-surface-50 relative">
            {!hasItems ? (
              <p className="text-xs text-slate-600 text-center px-4">
                Connect to a device first
              </p>
            ) : (
              <div className="relative">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleFocus();
                    setPickerOpen((v) => !v);
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-dashed
                             border-slate-600 text-slate-500 hover:text-slate-300 hover:border-blue-500
                             text-xs transition-colors"
                >
                  <Plus size={13} />
                  Assign connection
                </button>

                {/* Dropdown */}
                {pickerOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-10"
                      onClick={(e) => { e.stopPropagation(); setPickerOpen(false); }}
                    />
                    <ul className="absolute left-1/2 -translate-x-1/2 top-full mt-1.5 z-20
                                   bg-slate-800 border border-slate-600 rounded-lg shadow-xl
                                   min-w-[160px] max-h-56 overflow-y-auto py-1">
                      {items.map((item) => (
                        <li key={String(getKey(item))}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onAssign(index, getKey(item));
                              setPickerOpen(false);
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs text-slate-300
                                       hover:bg-slate-700 hover:text-white transition-colors truncate"
                          >
                            {getLabel(item)}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
