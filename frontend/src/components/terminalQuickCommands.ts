export interface QuickCommand {
  id: string;
  label: string;
  command: string;
}

export const MAX_QUICK_COMMANDS = 8;
const MAX_LABEL_LENGTH = 24;
const MAX_COMMAND_LENGTH = 160;

export function buildQuickCommandsStorageKey(terminalKey: number): string {
  return `cloudshell:terminal-quick-commands:${terminalKey}`;
}

function trimToLength(value: string, maxLength: number): string {
  return value.trim().slice(0, maxLength);
}

function toQuickCommand(value: unknown): QuickCommand | null {
  if (!value || typeof value !== "object") return null;
  const obj = value as Record<string, unknown>;
  if (typeof obj.id !== "string") return null;
  if (typeof obj.label !== "string") return null;
  if (typeof obj.command !== "string") return null;

  const label = trimToLength(obj.label, MAX_LABEL_LENGTH);
  const command = trimToLength(obj.command, MAX_COMMAND_LENGTH);
  if (!label || !command) return null;

  return {
    id: obj.id,
    label,
    command,
  };
}

export function normalizeQuickCommands(value: unknown): QuickCommand[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const normalized: QuickCommand[] = [];

  for (const item of value) {
    const parsed = toQuickCommand(item);
    if (!parsed) continue;
    if (seen.has(parsed.id)) continue;
    seen.add(parsed.id);
    normalized.push(parsed);
    if (normalized.length >= MAX_QUICK_COMMANDS) break;
  }

  return normalized;
}

export function parseQuickCommands(raw: string | null): QuickCommand[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    return normalizeQuickCommands(parsed);
  } catch {
    return [];
  }
}