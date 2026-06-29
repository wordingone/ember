// think-back.ts — /think-back and thinkback-play slash commands.

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';
import * as nodePath from 'node:path';

// ---------------------------------------------------------------------------
// Deps
// ---------------------------------------------------------------------------

interface ThinkbackFlowOpts {
  onStatus: (status: string) => void;
  onDone: (result: { display: string; shouldQuery: boolean; prompt: string }) => void;
}

interface ThinkbackDeps {
  isThinkbackEnabled: () => boolean;
  isMarketplaceSourceInstalled: () => boolean;
  addMarketplaceSource: () => Promise<void>;
  refreshMarketplace: () => Promise<void>;
  clearPluginCaches: () => void;
  loadAllPlugins: () => Promise<Array<{ name: string; enabled: boolean }>>;
  installSelectedPlugins: (names: string[]) => Promise<void>;
  getThinkbackSkillDir: () => Promise<string | null>;
  pathExists: (path: string) => Promise<boolean>;
  readFile: (path: string) => Promise<string>;
  runAnimationPlayer: (scriptContent: string) => Promise<{ success: boolean; message: string }>;
  enterAlternateScreen: () => void;
  exitAlternateScreen: () => void;
  openInBrowser: (path: string) => void;
  renderThinkbackFlow: ((opts: ThinkbackFlowOpts) => Promise<{ type: 'none' }>) | null;
  getUserType: () => string;
  getPluginIdForSource: (source: string) => Promise<string | null>;
  getPluginInstallPath: (pluginId: string) => Promise<string | null>;
}

const noopDeps: ThinkbackDeps = {
  isThinkbackEnabled: () => false,
  isMarketplaceSourceInstalled: () => true,
  addMarketplaceSource: async () => {},
  refreshMarketplace: async () => {},
  clearPluginCaches: () => {},
  loadAllPlugins: async () => [],
  installSelectedPlugins: async () => {},
  getThinkbackSkillDir: async () => null,
  pathExists: async () => false,
  readFile: async () => '',
  runAnimationPlayer: async () => ({ success: false, message: '' }),
  enterAlternateScreen: () => {},
  exitAlternateScreen: () => {},
  openInBrowser: () => {},
  renderThinkbackFlow: null,
  getUserType: () => 'external',
  getPluginIdForSource: async () => null,
  getPluginInstallPath: async () => null,
};

let deps: ThinkbackDeps = { ...noopDeps };

export function setThinkbackDeps(overrides: Partial<ThinkbackDeps>): void {
  deps = { ...deps, ...overrides };
}

export function resetThinkbackDeps(): void {
  deps = { ...noopDeps };
}

// ---------------------------------------------------------------------------
// playAnimation
// ---------------------------------------------------------------------------

export interface PlayAnimationResult {
  success: boolean;
  message: string;
}

export async function playAnimation(skillDir: string): Promise<PlayAnimationResult> {
  const jsPath = nodePath.join(skillDir, 'year_in_review.js').replace(/\\/g, '/');
  let scriptContent: string;
  try {
    scriptContent = await deps.readFile(jsPath);
  } catch {
    return { success: false, message: 'Animation file not accessible or not found.' };
  }

  deps.enterAlternateScreen();
  try {
    const result = await deps.runAnimationPlayer(scriptContent);
    // check for HTML companion
    const htmlPath = nodePath.join(skillDir, 'year_in_review.html').replace(/\\/g, '/');
    if (await deps.pathExists(htmlPath)) {
      deps.openInBrowser(htmlPath);
    }
    return result;
  } finally {
    deps.exitAlternateScreen();
  }
}

// ---------------------------------------------------------------------------
// Headless flow
// ---------------------------------------------------------------------------

async function runThinkbackFlow(_ctx: CommandContext): Promise<CommandResult> {
  // Ensure marketplace source is installed
  if (!deps.isMarketplaceSourceInstalled()) {
    try {
      await deps.addMarketplaceSource();
      await deps.refreshMarketplace();
      deps.clearPluginCaches();
    } catch {
      return {
        type: 'message',
        message: 'Failed to install thinkback source. Try /plugin to manage plugins.',
      };
    }
  }

  // Ensure plugin is loaded
  const plugins = await deps.loadAllPlugins();
  const installed = plugins.some((p) => p.name === 'thinkback');
  if (!installed) {
    await deps.installSelectedPlugins(['thinkback']);
  }

  // Get skill directory
  const skillDir = await deps.getThinkbackSkillDir();
  if (!skillDir) {
    return { type: 'message', message: 'Thinkback skill directory not found.' };
  }

  // Check for generated data
  const jsPath = nodePath.join(skillDir, 'year_in_review.js').replace(/\\/g, '/');
  const hasData = await deps.pathExists(jsPath);
  if (!hasData) {
    return {
      type: 'message',
      message: 'No thinkback data found. Use mode=regenerate to generate your year in review.',
    };
  }

  // Play animation
  const result = await playAnimation(skillDir);
  return { type: 'message', message: result.message };
}

// ---------------------------------------------------------------------------
// thinkBackCommand
// ---------------------------------------------------------------------------

export const thinkBackCommand: RegistryCommand = {
  name: 'think-back',
  description: 'View your year in review',

  isEnabled(): boolean {
    return deps.isThinkbackEnabled();
  },

  async execute(args: string, ctx: CommandContext): Promise<CommandResult> {
    if (!deps.isThinkbackEnabled()) {
      return { type: 'message', message: 'Thinkback is not enabled.' };
    }

    // JSX render path (when renderer is configured)
    if (deps.renderThinkbackFlow) {
      await deps.renderThinkbackFlow({
        onStatus: (_s: string) => {},
        onDone: (_r) => {},
      });
      return { type: 'message', message: '' };
    }

    return runThinkbackFlow(ctx);
  },
};

// ---------------------------------------------------------------------------
// thinkbackPlayCommand
// ---------------------------------------------------------------------------

export const thinkbackPlayCommand: RegistryCommand = {
  name: 'thinkback-play',
  description: 'Play thinkback animation',

  isEnabled(): boolean {
    return deps.isThinkbackEnabled();
  },

  async execute(_args: string, _ctx: CommandContext): Promise<CommandResult> {
    // Determine source based on user type
    const userType = deps.getUserType();
    const source = userType === 'ant' ? 'ember-marketplace/thinkback' : 'thinkback-external/thinkback';

    // Resolve plugin install path
    let skillDir: string | null = null;
    const pluginId = await deps.getPluginIdForSource(source);
    if (pluginId) {
      const installPath = await deps.getPluginInstallPath(pluginId);
      if (installPath) {
        skillDir = installPath;
      }
    }

    // Fallback to getThinkbackSkillDir
    if (!skillDir) {
      skillDir = await deps.getThinkbackSkillDir();
    }

    if (!skillDir) {
      return { type: 'message', message: 'Thinkback skill directory not found.' };
    }

    const result = await playAnimation(skillDir);
    return { type: 'message', message: result.message };
  },
};
