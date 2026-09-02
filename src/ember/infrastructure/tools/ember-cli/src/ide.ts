// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ide.ts — /ide slash command for IDE integration.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const IDE_CONNECTION_TIMEOUT_MS = 35_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IdeDescriptor {
  name: string;
  type: string;
  url: string;
}

type McpStatus = 'connected' | 'failed' | 'pending';

interface IdeCommandDeps {
  getValidIdes?: () => IdeDescriptor[];
  getWorktreePath?: () => string | null;
  runCodeCommand?: (path: string) => Promise<{ exitCode: number }>;
  onChangeDynamicMcpConfig?: (config: null | unknown) => void;
  watchIdeMcpStatus?: (cb: (status: McpStatus) => void) => () => void;
  getTimeoutMs?: () => number;
  clearIdeServerCache?: () => void;
  removeIdeFromAppState?: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Module-level mutable deps
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: Required<IdeCommandDeps> = {
  getValidIdes: () => [],
  getWorktreePath: () => null,
  runCodeCommand: async () => ({ exitCode: 0 }),
  onChangeDynamicMcpConfig: () => {},
  watchIdeMcpStatus: () => () => {},
  getTimeoutMs: () => IDE_CONNECTION_TIMEOUT_MS,
  clearIdeServerCache: () => {},
  removeIdeFromAppState: async () => {},
};

let deps: IdeCommandDeps = { ...DEFAULT_DEPS };

export function setIdeCommandDeps(overrides: IdeCommandDeps): void {
  deps = { ...DEFAULT_DEPS, ...overrides };
}

export function resetIdeCommandDeps(): void {
  deps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

export function formatWorkspaceFolders(folders: string[], cwd: string): string {
  const stripped = folders.map((f) => f.startsWith(cwd + '/') ? f.slice(cwd.length + 1) : f);
  const limited = stripped.slice(0, 2);
  const hasMore = stripped.length > 2;
  return hasMore ? limited.join(', ') + ', …' : limited.join(', ');
}

// ---------------------------------------------------------------------------
// connectToIde
// ---------------------------------------------------------------------------

export async function connectToIde(
  ide: IdeDescriptor,
  onMessage: (msg: string | null) => void,
): Promise<void> {
  const d = deps;
  const timeoutMs = (d.getTimeoutMs ?? DEFAULT_DEPS.getTimeoutMs)();

  (d.onChangeDynamicMcpConfig ?? DEFAULT_DEPS.onChangeDynamicMcpConfig)(ide);

  await new Promise<void>((resolve) => {
    let done = false;
    const timer = setTimeout(() => {
      if (!done) {
        done = true;
        unsubscribe();
        onMessage(`Connection to ${ide.name} timed out.`);
        resolve();
      }
    }, timeoutMs);

    const unsubscribe = (d.watchIdeMcpStatus ?? DEFAULT_DEPS.watchIdeMcpStatus)((status) => {
      if (done) return;
      if (status === 'connected' || status === 'failed') {
        done = true;
        clearTimeout(timer);
        unsubscribe();
        if (status === 'connected') {
          onMessage(`Connected to ${ide.name}.`);
        } else {
          onMessage(`Failed to connect to ${ide.name}.`);
        }
        resolve();
      }
    });
  });
}

// ---------------------------------------------------------------------------
// disconnectFromIde
// ---------------------------------------------------------------------------

export async function disconnectFromIde(
  ideName: string | undefined,
  onDone: () => Promise<void>,
  onMessage: (msg: string | null) => void,
): Promise<void> {
  if (!ideName) {
    onMessage('No IDE selected.');
    return;
  }
  const d = deps;
  (d.clearIdeServerCache ?? DEFAULT_DEPS.clearIdeServerCache)();
  await (d.removeIdeFromAppState ?? DEFAULT_DEPS.removeIdeFromAppState)();
  (d.onChangeDynamicMcpConfig ?? DEFAULT_DEPS.onChangeDynamicMcpConfig)(null);
  onMessage(`Disconnected from ${ideName}.`);
  await onDone();
}

// ---------------------------------------------------------------------------
// ideCommand
// ---------------------------------------------------------------------------

type IdeResult = { type: 'message'; message: string };

export const ideCommand = {
  name: 'ide',
  type: 'local-jsx',
  description: 'Connect to or open your IDE',

  isEnabled(): boolean {
    return true;
  },

  async execute(args: string, ctx: CommandContext): Promise<IdeResult> {
    const subcommand = args.trim();

    if (subcommand === 'open' || subcommand === '') {
      const ides = (deps.getValidIdes ?? DEFAULT_DEPS.getValidIdes)();
      if (ides.length === 0) {
        return { type: 'message', message: 'No IDEs with Ember CLI extension detected.' };
      }
      const ide = ides[0]!;
      const worktreePath = (deps.getWorktreePath ?? DEFAULT_DEPS.getWorktreePath)();
      const openPath = worktreePath ?? ctx.cwd;

      if (ide.type === 'vscode' || ide.type === 'cursor') {
        const result = await (deps.runCodeCommand ?? DEFAULT_DEPS.runCodeCommand)(openPath);
        if (result.exitCode === 0) {
          return { type: 'message', message: `Opened ${ide.name} at ${openPath}.` };
        }
        return { type: 'message', message: `Failed to open ${ide.name}.` };
      }

      // JetBrains or other: manual instruction
      return {
        type: 'message',
        message: `Please open ${ide.name} manually and navigate to: ${openPath}`,
      };
    }

    return { type: 'message', message: `Unknown subcommand: ${subcommand}` };
  },
};
