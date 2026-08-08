import { describe, expect, it } from "vitest";
import {
  MAX_QUICK_COMMANDS,
  buildQuickCommandsStorageKey,
  normalizeQuickCommands,
  parseQuickCommands,
} from "../components/terminalQuickCommands";

describe("terminalQuickCommands", () => {
  it("builds a per-window storage key", () => {
    expect(buildQuickCommandsStorageKey(42)).toBe("cloudshell:terminal-quick-commands:42");
  });

  it("normalizes and trims valid commands", () => {
    const normalized = normalizeQuickCommands([
      { id: "a", label: "  Apt Update  ", command: "  apt update  " },
      { id: "b", label: "", command: "uptime" },
    ]);

    expect(normalized).toEqual([
      { id: "a", label: "Apt Update", command: "apt update" },
    ]);
  });

  it("drops duplicate ids and enforces max command count", () => {
    const many = Array.from({ length: MAX_QUICK_COMMANDS + 4 }, (_, idx) => ({
      id: `id-${idx}`,
      label: `label-${idx}`,
      command: `echo ${idx}`,
    }));
    many.push({ id: "id-1", label: "duplicate", command: "echo duplicate" });

    const normalized = normalizeQuickCommands(many);
    expect(normalized).toHaveLength(MAX_QUICK_COMMANDS);
    expect(normalized[1].id).toBe("id-1");
  });

  it("returns empty list for bad JSON payloads", () => {
    expect(parseQuickCommands(null)).toEqual([]);
    expect(parseQuickCommands("not-json")).toEqual([]);
    expect(parseQuickCommands("{}")).toEqual([]);
  });
});