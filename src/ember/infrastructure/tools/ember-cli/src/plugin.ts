// plugin.ts
// /plugin slash command: argument parsing, routing (ant vs standard), and
// the pagination helper used by plugin/MCP list views.
// Contract: src/plugin.test.ts (AC1-AC5).

import type { RegistryCommand, CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// ParsedPluginCommand — discriminated union
// ---------------------------------------------------------------------------

export type ParsedPluginCommand =
  | { type: 'menu' }
  | { type: 'install'; target?: string; isUrlOrPath: boolean }
  | { type: 'marketplace'; action?: string; target?: string };

// ---------------------------------------------------------------------------
// isUrlOrPath — determines whether an install target is a URL or filesystem path
// ---------------------------------------------------------------------------

function isUrlOrPathTarget(target: string): boolean {
  if (!target) return false;
  if (
    target.startsWith('https://') ||
    target.startsWith('http://') ||
    target.startsWith('file://')
  ) {
    return true;
  }
  if (
    target.startsWith('./') ||
    target.startsWith('../') ||
    target.startsWith('@')
  ) {
    return true;
  }
  if (target.includes('/') || target.includes('\\')) return true;
  return false;
}

// ---------------------------------------------------------------------------
// parsePluginArgs — AC1, AC2, AC5
// ---------------------------------------------------------------------------

const MARKETPLACE_ALIASES = new Set(['marketplace', 'market']);
const ACTION_ALIASES: Record<string, string> = { rm: 'remove' };

export function parsePluginArgs(args: string): ParsedPluginCommand {
  const trimmed = args.trim();
  if (!trimmed) return { type: 'menu' };

  const tokens = trimmed.split(/\s+/);
  const first = tokens[0]!;

  if (first === 'install') {
    const target = tokens[1];
    return {
      type: 'install',
      target,
      isUrlOrPath: target !== undefined ? isUrlOrPathTarget(target) : false,
    };
  }

  if (MARKETPLACE_ALIASES.has(first)) {
    const rawAction = tokens[1];
    const action = rawAction !== undefined
      ? (ACTION_ALIASES[rawAction] ?? rawAction)
      : undefined;
    const target = tokens[2];
    return { type: 'marketplace', action, target };
  }

  // Unknown first token → menu
  return { type: 'menu' };
}

// ---------------------------------------------------------------------------
// PluginCommand deps (injected via setPluginCommandDeps) — AC3
// ---------------------------------------------------------------------------

interface PluginCommandDeps {
  isAntUser(): boolean;
  renderPluginSettings(parsed?: ParsedPluginCommand, ctx?: CommandContext): void;
  renderMcpSettings(parsed?: ParsedPluginCommand, ctx?: CommandContext): void;
}

const noop = () => {};

const DEFAULT_DEPS: PluginCommandDeps = {
  isAntUser: () => false,
  renderPluginSettings: noop,
  renderMcpSettings: noop,
};

let _deps: PluginCommandDeps = { ...DEFAULT_DEPS };

export function setPluginCommandDeps(deps: PluginCommandDeps): void {
  _deps = deps;
}

export function resetPluginCommandDeps(): void {
  _deps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// pluginCommand — the /plugin slash command
// ---------------------------------------------------------------------------

export const pluginCommand: RegistryCommand & { type: 'local-jsx' } = {
  name: 'plugin',
  description: 'Manage plugins and MCP servers',
  type: 'local-jsx',
  isEnabled: () => true,
  async execute(args: string, ctx: CommandContext): Promise<void> {
    const parsed = parsePluginArgs(args);
    if (_deps.isAntUser()) {
      _deps.renderPluginSettings(parsed, ctx);
    } else {
      _deps.renderMcpSettings(parsed, ctx);
    }
  },
};

// ---------------------------------------------------------------------------
// PaginationState — AC4
// ---------------------------------------------------------------------------

export interface PaginationState {
  selectedIndex: number;
  scrollOffset: number;
  maxVisible: number;
  canScrollUp: boolean;
  canScrollDown: boolean;
  total: number;
}

export function createPaginationState(total: number, maxVisible = 5): PaginationState {
  return {
    selectedIndex: 0,
    scrollOffset: 0,
    maxVisible,
    total,
    canScrollUp: false,
    canScrollDown: maxVisible < total,
  };
}

export function adjustScrollToKeepInView(
  state: PaginationState,
  newIndex: number,
): PaginationState {
  let { scrollOffset } = state;
  const { maxVisible, total } = state;

  if (newIndex >= scrollOffset + maxVisible) {
    scrollOffset = newIndex - maxVisible + 1;
  } else if (newIndex < scrollOffset) {
    scrollOffset = newIndex;
  }

  // Clamp scrollOffset to valid range
  const maxScrollOffset = Math.max(0, total - maxVisible);
  scrollOffset = Math.min(scrollOffset, maxScrollOffset);
  scrollOffset = Math.max(0, scrollOffset);

  return {
    ...state,
    selectedIndex: newIndex,
    scrollOffset,
    canScrollUp: scrollOffset > 0,
    canScrollDown: scrollOffset + maxVisible < total,
  };
}

/** No-op: page-level navigation is not implemented at this layer. */
export function goToPage(state: PaginationState, _page: number): PaginationState {
  return state;
}

/** No-op: page-level navigation is not implemented at this layer. */
export function nextPage(state: PaginationState): PaginationState {
  return state;
}

/** No-op: page-level navigation is not implemented at this layer. */
export function prevPage(state: PaginationState): PaginationState {
  return state;
}
