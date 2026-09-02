// Tests for web-setup command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  webSetupCommand,
  runWebSetup,
  isWebSetupEnabled,
  RedactedGithubToken,
  setWebSetupDeps,
  _resetWebSetupDeps,
  EMBER_WEB_URL_LEGACY,
  GH_TOKEN_TIMEOUT_MS,
  IMPORT_TOKEN_TIMEOUT_MS,
  IMPORT_TOKEN_BETA_HEADER,
  type WebSetupDeps,
  type ImportTokenError,
} from './web-setup.ts';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

const makeEnabledDeps = (): WebSetupDeps => ({
  isCobaltLanternEnabled: () => true,
  isPolicyAllowed: () => true,
  isSignedIn: () => true,
  getGhAuthToken: async () => 'ghp_testtoken',
  importGithubToken: async () => {},
  createDefaultEnvironment: async () => {},
  openBrowser: async () => {},
  logAnalyticsEvent: () => {},
  openLoginPage: async () => {},
});

beforeEach(() => {
  _resetWebSetupDeps();
});

// ---------------------------------------------------------------------------
// AC1: isEnabled requires cobalt-lantern flag + policy.
// ---------------------------------------------------------------------------

describe('AC1 — availability: cobalt-lantern + allow_remote_sessions', () => {
  it('isWebSetupEnabled returns false when cobalt lantern is off', () => {
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      isCobaltLanternEnabled: () => false,
    };
    expect(isWebSetupEnabled(deps)).toBe(false);
  });

  it('isWebSetupEnabled returns false when policy denied', () => {
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      isPolicyAllowed: () => false,
    };
    expect(isWebSetupEnabled(deps)).toBe(false);
  });

  it('isWebSetupEnabled returns true when both conditions met', () => {
    expect(isWebSetupEnabled(makeEnabledDeps())).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC2: Redirects to login when not signed in.
// ---------------------------------------------------------------------------

describe('AC2 — redirects to login when not signed in', () => {
  it('opens login page and returns a sign-in message when not signed in', async () => {
    let loginOpened = false;
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      isSignedIn: () => false,
      openLoginPage: async () => { loginOpened = true; },
    };
    const result = await runWebSetup(deps);
    expect(loginOpened).toBe(true);
    expect(result.type).toBe('message');
    expect((result.message ?? '').toLowerCase()).toContain('sign in');
  });
});

// ---------------------------------------------------------------------------
// AC3: GitHub CLI token fetched with 5-second timeout.
// ---------------------------------------------------------------------------

describe('AC3 — gh token fetch has 5-second timeout', () => {
  it('GH_TOKEN_TIMEOUT_MS is 5000', () => {
    expect(GH_TOKEN_TIMEOUT_MS).toBe(5_000);
  });

  it('returns error message when gh times out (simulated via rejection)', async () => {
    // Simulate the race expiring: getGhAuthToken rejects as if the 5s timer won.
    // The real race uses GH_TOKEN_TIMEOUT_MS=5000; here we test the error path directly.
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      getGhAuthToken: async () => { throw new Error('timeout'); },
    };
    const result = await runWebSetup(deps);
    expect(result.type).toBe('message');
    expect((result.message ?? '').toLowerCase()).toContain('github');
  });
});

// ---------------------------------------------------------------------------
// AC4: RedactedGithubToken — toString/toJSON return redaction marker; reveal() returns value.
// ---------------------------------------------------------------------------

describe('AC4 — RedactedGithubToken redaction', () => {
  it('toString returns [REDACTED_GITHUB_TOKEN]', () => {
    const tok = new RedactedGithubToken('ghp_real');
    expect(tok.toString()).toBe('[REDACTED_GITHUB_TOKEN]');
  });

  it('toJSON returns [REDACTED_GITHUB_TOKEN]', () => {
    const tok = new RedactedGithubToken('ghp_real');
    expect(tok.toJSON()).toBe('[REDACTED_GITHUB_TOKEN]');
  });

  it('reveal() returns the actual value', () => {
    const tok = new RedactedGithubToken('ghp_actual_value');
    expect(tok.reveal()).toBe('ghp_actual_value');
  });

  it('JSON.stringify serializes as the redaction marker', () => {
    const tok = new RedactedGithubToken('ghp_secret');
    const serialized = JSON.stringify({ token: tok });
    expect(serialized).toContain('[REDACTED_GITHUB_TOKEN]');
    expect(serialized).not.toContain('ghp_secret');
  });
});

// ---------------------------------------------------------------------------
// AC5: Import token uses beta header and 15-second timeout.
// ---------------------------------------------------------------------------

describe('AC5 — import token beta header and timeout', () => {
  it('IMPORT_TOKEN_BETA_HEADER is the expected value', () => {
    expect(IMPORT_TOKEN_BETA_HEADER).toBe('ccr-byoc-2025-07-29');
  });

  it('IMPORT_TOKEN_TIMEOUT_MS is 15000', () => {
    expect(IMPORT_TOKEN_TIMEOUT_MS).toBe(15_000);
  });
});

// ---------------------------------------------------------------------------
// AC6: createDefaultEnvironment failures are non-fatal.
// ---------------------------------------------------------------------------

describe('AC6 — createDefaultEnvironment failure is non-fatal', () => {
  it('does not fail the overall flow when createDefaultEnvironment throws', async () => {
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      createDefaultEnvironment: async () => { throw new Error('env create failed'); },
    };
    const result = await runWebSetup(deps);
    expect(result.type).toBe('message');
    expect((result.message ?? '').toLowerCase()).toContain('success');
  });
});

// ---------------------------------------------------------------------------
// AC7: Opens ember.ai/code on success.
// ---------------------------------------------------------------------------

describe('AC7 — opens ember.ai/code on success', () => {
  it('EMBER_WEB_URL_LEGACY is https://ember.ai/code', () => {
    expect(EMBER_WEB_URL_LEGACY).toBe('https://ember.ai/code');
  });

  it('opens the ember web URL after successful import', async () => {
    const openedUrls: string[] = [];
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      openBrowser: async (url) => { openedUrls.push(url); },
    };
    await runWebSetup(deps);
    expect(openedUrls).toContain(EMBER_WEB_URL_LEGACY);
  });
});

// ---------------------------------------------------------------------------
// isEnabled wires to deps.
// ---------------------------------------------------------------------------

describe('webSetupCommand isEnabled', () => {
  it('uses injected deps for availability check', () => {
    setWebSetupDeps({
      isCobaltLanternEnabled: () => true,
      isPolicyAllowed: () => true,
    });
    expect(webSetupCommand.isEnabled()).toBe(true);
  });

  it('returns false by default (safe default — feature gated)', () => {
    _resetWebSetupDeps();
    expect(webSetupCommand.isEnabled()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Not signed in — gh CLI not installed error.
// ---------------------------------------------------------------------------

describe('gh CLI not installed', () => {
  it('returns install guidance when gh is not installed', async () => {
    const deps: WebSetupDeps = {
      ...makeEnabledDeps(),
      getGhAuthToken: async () => { throw new Error('not_installed'); },
    };
    const result = await runWebSetup(deps);
    expect(result.type).toBe('message');
    expect((result.message ?? '').toLowerCase()).toContain('not installed');
  });
});
