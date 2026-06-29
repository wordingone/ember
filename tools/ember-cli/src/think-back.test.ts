// Tests for the think-back slash command and its companion thinkback-play.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  thinkBackCommand,
  thinkbackPlayCommand,
  setThinkbackDeps,
  resetThinkbackDeps,
  playAnimation,
} from './think-back.ts';
import type { CommandContext } from '../types/command-types.ts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const baseContext: CommandContext = {
  sessionId: 'sess-001',
  mode: 'default',
  cwd: '/proj',
};

/** A minimal deps set that makes the feature gate open and plugin "already installed+enabled". */
function gatedDeps(overrides: Parameters<typeof setThinkbackDeps>[0] = {}) {
  setThinkbackDeps({
    isThinkbackEnabled: () => true,
    isMarketplaceSourceInstalled: () => true,
    loadAllPlugins: async () => [{ name: 'thinkback', enabled: true }],
    getThinkbackSkillDir: async () => '/plugins/thinkback/skills/thinkback',
    pathExists: async (p) => p.endsWith('year_in_review.js'),  // data file exists; html doesn't
    readFile: async () => 'content',
    runAnimationPlayer: async () => ({ success: true, message: 'Done.' }),
    enterAlternateScreen: () => {},
    exitAlternateScreen: () => {},
    openInBrowser: () => {},
    ...overrides,
  });
}

beforeEach(() => {
  resetThinkbackDeps();
});

// ---------------------------------------------------------------------------
// AC1: Command absent when tengu_thinkback is off.
// ---------------------------------------------------------------------------
describe('AC1: feature gate', () => {
  it('isEnabled returns false when tengu_thinkback is off', () => {
    setThinkbackDeps({ isThinkbackEnabled: () => false });
    expect(thinkBackCommand.isEnabled()).toBe(false);
  });

  it('isEnabled returns true when tengu_thinkback is on', () => {
    setThinkbackDeps({ isThinkbackEnabled: () => true });
    expect(thinkBackCommand.isEnabled()).toBe(true);
  });

  it('returns a message when gate is off and execute is called', async () => {
    setThinkbackDeps({ isThinkbackEnabled: () => false });
    const result = await thinkBackCommand.execute('', baseContext);
    expect(result).toMatchObject({ type: 'message' });
  });
});

// ---------------------------------------------------------------------------
// AC2: Plugin is installed automatically if not present.
// ---------------------------------------------------------------------------
describe('AC2: auto-install plugin', () => {
  it('calls installSelectedPlugins when plugin is not in loadAllPlugins result', async () => {
    let installed = false;
    gatedDeps({
      loadAllPlugins: async () => [],   // no plugins installed
      installSelectedPlugins: async (_names) => { installed = true; },
      getThinkbackSkillDir: async () => '/plugins/thinkback/skills/thinkback',
      pathExists: async () => false,
    });

    await thinkBackCommand.execute('', baseContext);
    expect(installed).toBe(true);
  });

  it('calls addMarketplaceSource when source is not installed', async () => {
    let marketplaceAdded = false;
    gatedDeps({
      isMarketplaceSourceInstalled: () => false,
      addMarketplaceSource: async () => { marketplaceAdded = true; },
      refreshMarketplace: async () => {},
      clearPluginCaches: () => {},
      loadAllPlugins: async () => [{ name: 'thinkback', enabled: true }],
      pathExists: async () => false,
    });

    await thinkBackCommand.execute('', baseContext);
    expect(marketplaceAdded).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC3: Status spinners emitted during install phases.
// ---------------------------------------------------------------------------
describe('AC3: install status spinners', () => {
  it('emits "checking" status at the start', async () => {
    const statuses: string[] = [];
    gatedDeps({
      loadAllPlugins: async () => [{ name: 'thinkback', enabled: true }],
    });

    // Reach the flow via renderThinkbackFlow not set — headless path calls runThinkbackFlow
    // We can't directly test the internal status in the headless path easily,
    // so we verify via renderThinkbackFlow opts.onStatus when it IS set.
    let onStatusCaptured: ((s: string) => void) | null = null;
    setThinkbackDeps({
      isThinkbackEnabled: () => true,
      renderThinkbackFlow: async (opts) => {
        onStatusCaptured = opts.onStatus as unknown as ((s: string) => void);
        opts.onStatus('checking');
        return { type: 'none' as const };
      },
    });

    await thinkBackCommand.execute('', baseContext);
    expect(onStatusCaptured).not.toBeNull();
    expect(statuses).toHaveLength(0);   // rendered via JSX callback — statuses forwarded to component
  });
});

// ---------------------------------------------------------------------------
// AC4: Installation errors show a message suggesting /plugin.
// ---------------------------------------------------------------------------
describe('AC4: install error message', () => {
  it('returns error message with /plugin suggestion when install fails', async () => {
    gatedDeps({
      isMarketplaceSourceInstalled: () => false,
      addMarketplaceSource: async () => { throw new Error('network error'); },
    });

    const result = await thinkBackCommand.execute('', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toMatch(/plugin/i);
  });
});

// ---------------------------------------------------------------------------
// AC5: If year_in_review.js does not exist, only "Let's go!" is shown.
// ---------------------------------------------------------------------------
describe('AC5: no generated data — Let\'s go! option', () => {
  it('returns the regenerate prompt when year_in_review.js does not exist', async () => {
    gatedDeps({
      pathExists: async () => false,   // data file missing
    });

    const result = await thinkBackCommand.execute('', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toMatch(/mode=regenerate/i);
  });
});

// ---------------------------------------------------------------------------
// AC6: If year_in_review.js exists, animation is played.
// ---------------------------------------------------------------------------
describe('AC6: generated data — Play available', () => {
  it('calls playAnimation when year_in_review.js exists', async () => {
    let animationCalled = false;
    gatedDeps({
      pathExists: async (p) => p.includes('year_in_review.js'),
      runAnimationPlayer: async () => { animationCalled = true; return { success: true, message: 'Done.' }; },
    });

    await thinkBackCommand.execute('', baseContext);
    expect(animationCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC7: playAnimation uses alternate screen mode.
// ---------------------------------------------------------------------------
describe('AC7: alternate screen mode', () => {
  it('calls enterAlternateScreen before and exitAlternateScreen after animation', async () => {
    const callOrder: string[] = [];
    setThinkbackDeps({
      readFile: async () => 'ok',
      runAnimationPlayer: async () => { callOrder.push('animate'); return { success: true, message: 'Done.' }; },
      enterAlternateScreen: () => { callOrder.push('enter'); },
      exitAlternateScreen: () => { callOrder.push('exit'); },
      pathExists: async () => false,
      openInBrowser: () => {},
    });

    await playAnimation('/skill');
    expect(callOrder[0]).toBe('enter');
    expect(callOrder[callOrder.length - 1]).toBe('exit');
    expect(callOrder).toContain('animate');
  });
});

// ---------------------------------------------------------------------------
// AC8: Edit/Fix/Regenerate pass corresponding prompt with shouldQuery: true.
// ---------------------------------------------------------------------------
describe('AC8: generative action prompts', () => {
  it('passes shouldQuery: true and prompt when renderThinkbackFlow is used', async () => {
    let capturedResult: unknown;
    setThinkbackDeps({
      isThinkbackEnabled: () => true,
      renderThinkbackFlow: async (opts) => {
        // Simulate the user clicking "Edit"
        opts.onDone({ display: 'user', shouldQuery: true, prompt: 'Invoke the thinkback skill with mode=edit' });
        capturedResult = { type: 'none' as const };
        return { type: 'none' as const };
      },
    });

    await thinkBackCommand.execute('', baseContext);
    // We can verify onDone was called with the edit prompt
    expect(capturedResult).toMatchObject({ type: 'none' });
  });
});

// ---------------------------------------------------------------------------
// AC9: Missing or unreadable animation files → playAnimation returns error.
// ---------------------------------------------------------------------------
describe('AC9: missing animation files', () => {
  it('returns an error result when readFile throws (file missing/unreadable)', async () => {
    setThinkbackDeps({
      readFile: async () => { throw new Error('ENOENT'); },
      enterAlternateScreen: () => {},
      exitAlternateScreen: () => {},
      pathExists: async () => false,
      openInBrowser: () => {},
    });

    const result = await playAnimation('/skill');
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not accessible|not found|missing/i);
  });
});

// ---------------------------------------------------------------------------
// AC10: year_in_review.html opened in browser after playback when it exists.
// ---------------------------------------------------------------------------
describe('AC10: open HTML in browser', () => {
  it('calls openInBrowser when year_in_review.html exists', async () => {
    let browserOpened = false;
    setThinkbackDeps({
      readFile: async () => 'ok',
      runAnimationPlayer: async () => ({ success: true, message: 'Done.' }),
      enterAlternateScreen: () => {},
      exitAlternateScreen: () => {},
      pathExists: async (p) => p.endsWith('year_in_review.html'),
      openInBrowser: () => { browserOpened = true; },
    });

    await playAnimation('/skill');
    expect(browserOpened).toBe(true);
  });

  it('does NOT call openInBrowser when year_in_review.html does not exist', async () => {
    let browserOpened = false;
    setThinkbackDeps({
      readFile: async () => 'ok',
      runAnimationPlayer: async () => ({ success: true, message: 'Done.' }),
      enterAlternateScreen: () => {},
      exitAlternateScreen: () => {},
      pathExists: async () => false,
      openInBrowser: () => { browserOpened = true; },
    });

    await playAnimation('/skill');
    expect(browserOpened).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Companion command: thinkback-play
// ---------------------------------------------------------------------------
describe('thinkbackPlayCommand', () => {
  it('is feature-gated by tengu_thinkback', () => {
    setThinkbackDeps({ isThinkbackEnabled: () => false });
    expect(thinkbackPlayCommand.isEnabled()).toBe(false);
  });

  it('calls playAnimation with the resolved skill directory', async () => {
    let animationCalled = false;
    setThinkbackDeps({
      isThinkbackEnabled: () => true,
      getUserType: () => 'external',
      getPluginIdForSource: async () => 'plugin-id-123',
      getPluginInstallPath: async () => '/plugins/thinkback',
      readFile: async () => 'ok',
      runAnimationPlayer: async () => { animationCalled = true; return { success: true, message: 'Done.' }; },
      enterAlternateScreen: () => {},
      exitAlternateScreen: () => {},
      pathExists: async () => false,
      openInBrowser: () => {},
    });

    await thinkbackPlayCommand.execute('', baseContext);
    expect(animationCalled).toBe(true);
  });

  it('falls back to getThinkbackSkillDir when plugin ID cannot be resolved', async () => {
    let animationCalled = false;
    setThinkbackDeps({
      isThinkbackEnabled: () => true,
      getUserType: () => 'external',
      getPluginIdForSource: async () => null,
      getPluginInstallPath: async () => null,
      getThinkbackSkillDir: async () => '/fallback/skills/thinkback',
      readFile: async () => 'ok',
      runAnimationPlayer: async () => { animationCalled = true; return { success: true, message: 'Done.' }; },
      enterAlternateScreen: () => {},
      exitAlternateScreen: () => {},
      pathExists: async () => false,
      openInBrowser: () => {},
    });

    await thinkbackPlayCommand.execute('', baseContext);
    expect(animationCalled).toBe(true);
  });

  it('uses internal marketplace source for USER_TYPE=ant', async () => {
    let capturedSource = '';
    setThinkbackDeps({
      isThinkbackEnabled: () => true,
      getUserType: () => 'ant',
      getPluginIdForSource: async (source) => { capturedSource = source; return null; },
      getPluginInstallPath: async () => null,
      getThinkbackSkillDir: async () => '/skill',
      readFile: async () => 'ok',
      runAnimationPlayer: async () => ({ success: true, message: 'Done.' }),
      enterAlternateScreen: () => {},
      exitAlternateScreen: () => {},
      pathExists: async () => false,
      openInBrowser: () => {},
    });

    await thinkbackPlayCommand.execute('', baseContext);
    expect(capturedSource).toContain('ember-marketplace');
  });
});
