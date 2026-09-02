// desktop.ts — /desktop and /app slash commands for desktop app handoff.

import type { CommandContext } from './types/command-types.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DesktopCommandDeps {
  isCloudSurface?: () => boolean;
  getPlatform?: () => string;
  getArch?: () => string;
  renderDesktopHandoff?: (onDone: (result?: string) => void) => void;
}

// ---------------------------------------------------------------------------
// Module-level mutable deps
// ---------------------------------------------------------------------------

const DEFAULT_DEPS: Required<DesktopCommandDeps> = {
  isCloudSurface: () => false,
  getPlatform: () => process.platform,
  getArch: () => process.arch,
  renderDesktopHandoff: () => {},
};

let deps: DesktopCommandDeps = { ...DEFAULT_DEPS };

export function setDesktopCommandDeps(overrides: DesktopCommandDeps): void {
  deps = { ...DEFAULT_DEPS, ...overrides };
}

export function resetDesktopCommandDeps(): void {
  deps = { ...DEFAULT_DEPS };
}

// ---------------------------------------------------------------------------
// isSupportedPlatform
// ---------------------------------------------------------------------------

export function isSupportedPlatform(platform: string, arch: string): boolean {
  if (platform === 'darwin') return true;
  if (platform === 'win32' && arch === 'x64') return true;
  return false;
}

// ---------------------------------------------------------------------------
// desktopCommand
// ---------------------------------------------------------------------------

type ExtendedCtx = CommandContext & { onDone?: (result?: string) => void };

export const desktopCommand = {
  name: 'desktop',
  type: 'local-jsx',
  description: 'Download and open the Ember desktop app',
  aliases: ['app'],
  availability: ['cloud'],

  isEnabled(): boolean {
    const isCloud = (deps.isCloudSurface ?? DEFAULT_DEPS.isCloudSurface)();
    const platform = (deps.getPlatform ?? DEFAULT_DEPS.getPlatform)();
    const arch = (deps.getArch ?? DEFAULT_DEPS.getArch)();
    return isCloud && isSupportedPlatform(platform, arch);
  },

  async execute(_args: string, ctx: CommandContext): Promise<void> {
    const extCtx = ctx as ExtendedCtx;
    (deps.renderDesktopHandoff ?? DEFAULT_DEPS.renderDesktopHandoff)((result) => {
      extCtx.onDone?.(result);
    });
  },
};
