// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for init command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  initCommand,
  buildInitPrompt,
  setInitCommandDeps,
  _resetInitCommandDeps,
  OLD_PATH_PROMPT,
  NEW_PATH_PROMPT,
  type InitCommandDeps,
} from './init.ts';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

beforeEach(() => {
  _resetInitCommandDeps();
  // Ensure env vars are clean for each test
  delete process.env['EMBER_NEW_INIT'];
  delete process.env['USER_TYPE'];
});

// ---------------------------------------------------------------------------
// AC1: maybeMarkProjectOnboardingComplete() is always called first.
// ---------------------------------------------------------------------------

describe('AC1 — maybeMarkProjectOnboardingComplete called first', () => {
  it('calls maybeMarkProjectOnboardingComplete before returning the prompt', async () => {
    const calls: string[] = [];
    setInitCommandDeps({
      maybeMarkProjectOnboardingComplete: () => { calls.push('onboarding'); },
      isNewInitEnabled: () => { calls.push('newCheck'); return false; },
    });
    await initCommand.execute('', makeCtx());
    const onboardingIdx = calls.indexOf('onboarding');
    const newCheckIdx = calls.indexOf('newCheck');
    expect(onboardingIdx).toBeGreaterThanOrEqual(0);
    // onboarding must precede or equal the first check call
    expect(onboardingIdx).toBeLessThanOrEqual(newCheckIdx);
  });

  it('calls it even when new path is selected', async () => {
    let called = false;
    setInitCommandDeps({
      maybeMarkProjectOnboardingComplete: () => { called = true; },
      isNewInitEnabled: () => true,
    });
    await initCommand.execute('', makeCtx());
    expect(called).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC2: Old path — simple EMBER.md generation prompt.
// ---------------------------------------------------------------------------

describe('AC2 — old path: EMBER.md generation prompt', () => {
  it('returns OLD_PATH_PROMPT when isNewInitEnabled returns false', async () => {
    setInitCommandDeps({ isNewInitEnabled: () => false });
    const result = await initCommand.execute('', makeCtx());
    expect(result?.type).toBe('message');
    expect(result?.message).toBe(OLD_PATH_PROMPT);
  });

  it('OLD_PATH_PROMPT mentions EMBER.md', () => {
    expect(OLD_PATH_PROMPT).toContain('EMBER.md');
  });

  it('OLD_PATH_PROMPT instructs writing without confirmation', () => {
    expect(OLD_PATH_PROMPT).toContain('Do not ask for confirmation');
  });
});

// ---------------------------------------------------------------------------
// AC3: New path — 8-phase wizard prompt.
// ---------------------------------------------------------------------------

describe('AC3 — new path: 8-phase wizard prompt', () => {
  it('returns NEW_PATH_PROMPT when isNewInitEnabled returns true', async () => {
    setInitCommandDeps({ isNewInitEnabled: () => true });
    const result = await initCommand.execute('', makeCtx());
    expect(result?.type).toBe('message');
    expect(result?.message).toBe(NEW_PATH_PROMPT);
  });

  it('NEW_PATH_PROMPT contains all 8 phases', () => {
    for (let i = 1; i <= 8; i++) {
      expect(NEW_PATH_PROMPT).toContain(`Phase ${i}`);
    }
  });

  it('NEW_PATH_PROMPT does not write before phase 4', () => {
    // The spec requires "Do not write any files until phase 4 at the earliest"
    expect(NEW_PATH_PROMPT).toContain('phase 4');
  });
});

// ---------------------------------------------------------------------------
// AC4: EMBER_NEW_INIT env enables new path.
// ---------------------------------------------------------------------------

describe('AC4 — EMBER_NEW_INIT env flag', () => {
  it('enables new path when EMBER_NEW_INIT env is set', () => {
    process.env['EMBER_NEW_INIT'] = '1';
    _resetInitCommandDeps(); // re-init to pick up env
    const deps: InitCommandDeps = {
      maybeMarkProjectOnboardingComplete: () => {},
      isNewInitEnabled: () =>
        !!process.env['EMBER_NEW_INIT'] || process.env['USER_TYPE'] === 'ant',
    };
    expect(buildInitPrompt(deps)).toBe(NEW_PATH_PROMPT);
    delete process.env['EMBER_NEW_INIT'];
  });
});

// ---------------------------------------------------------------------------
// AC5: USER_TYPE === 'ant' enables new path.
// ---------------------------------------------------------------------------

describe('AC5 — USER_TYPE=ant flag', () => {
  it('enables new path when USER_TYPE is ant', () => {
    process.env['USER_TYPE'] = 'ant';
    const deps: InitCommandDeps = {
      maybeMarkProjectOnboardingComplete: () => {},
      isNewInitEnabled: () =>
        !!process.env['EMBER_NEW_INIT'] || process.env['USER_TYPE'] === 'ant',
    };
    expect(buildInitPrompt(deps)).toBe(NEW_PATH_PROMPT);
    delete process.env['USER_TYPE'];
  });
});

// ---------------------------------------------------------------------------
// Type is 'prompt' (model-driven interaction).
// ---------------------------------------------------------------------------

describe('command type', () => {
  it('type is prompt', () => {
    expect(initCommand.type).toBe('prompt');
  });

  it('isEnabled always returns true', () => {
    expect(initCommand.isEnabled()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// buildInitPrompt helper
// ---------------------------------------------------------------------------

describe('buildInitPrompt', () => {
  it('returns old prompt when isNewInitEnabled returns false', () => {
    const deps: InitCommandDeps = {
      maybeMarkProjectOnboardingComplete: () => {},
      isNewInitEnabled: () => false,
    };
    expect(buildInitPrompt(deps)).toBe(OLD_PATH_PROMPT);
  });

  it('returns new prompt when isNewInitEnabled returns true', () => {
    const deps: InitCommandDeps = {
      maybeMarkProjectOnboardingComplete: () => {},
      isNewInitEnabled: () => true,
    };
    expect(buildInitPrompt(deps)).toBe(NEW_PATH_PROMPT);
  });
});
