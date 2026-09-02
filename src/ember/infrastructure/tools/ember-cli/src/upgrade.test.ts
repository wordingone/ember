// Tests for upgrade command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  upgradeCommand,
  isUpgradeEnabled,
  isAlreadyOnMax20x,
  setUpgradeCommandDeps,
  _resetUpgradeCommandDeps,
  UPGRADE_URL,
  MAX_20X_RATE_LIMIT_TIER,
  type UpgradeCommandDeps,
} from './upgrade.ts';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

const makeEnabledDeps = (): UpgradeCommandDeps => ({
  isCloudSurface: () => true,
  isEnterpriseSubscription: () => false,
  getOAuthTokenInfo: () => null,
  getOAuthProfileFromToken: async () => null,
  openBrowser: async () => true,
  renderLoginComponent: async () => false,
  onChangeAPIKey: () => {},
});

beforeEach(() => {
  _resetUpgradeCommandDeps();
  delete process.env['DISABLE_UPGRADE_COMMAND'];
});

// ---------------------------------------------------------------------------
// AC1: Only available on cloud surface.
// ---------------------------------------------------------------------------

describe('AC1 — only available on cloud surface', () => {
  it('isUpgradeEnabled returns false when not on cloud surface', () => {
    const deps: UpgradeCommandDeps = {
      ...makeEnabledDeps(),
      isCloudSurface: () => false,
    };
    expect(isUpgradeEnabled(deps)).toBe(false);
  });

  it('isUpgradeEnabled returns true when on cloud surface', () => {
    expect(isUpgradeEnabled(makeEnabledDeps())).toBe(true);
  });

  it('command has availability: cloud', () => {
    expect(upgradeCommand.availability).toContain('cloud');
  });
});

// ---------------------------------------------------------------------------
// AC2: DISABLE_UPGRADE_COMMAND env gate.
// ---------------------------------------------------------------------------

describe('AC2 — DISABLE_UPGRADE_COMMAND env gate', () => {
  it('isUpgradeEnabled returns false when env is set', () => {
    process.env['DISABLE_UPGRADE_COMMAND'] = '1';
    expect(isUpgradeEnabled(makeEnabledDeps())).toBe(false);
    delete process.env['DISABLE_UPGRADE_COMMAND'];
  });
});

// ---------------------------------------------------------------------------
// AC3: Disabled for enterprise subscriptions.
// ---------------------------------------------------------------------------

describe('AC3 — disabled for enterprise', () => {
  it('isUpgradeEnabled returns false for enterprise subscriptions', () => {
    const deps: UpgradeCommandDeps = {
      ...makeEnabledDeps(),
      isEnterpriseSubscription: () => true,
    };
    expect(isUpgradeEnabled(deps)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC4: Already on Max 20x — no login component shown.
// ---------------------------------------------------------------------------

describe('AC4 — already on Max 20x shows message only', () => {
  it('isAlreadyOnMax20x returns true when tokenInfo matches max 20x', async () => {
    const deps: UpgradeCommandDeps = {
      ...makeEnabledDeps(),
      getOAuthTokenInfo: () => ({
        subscriptionType: 'max',
        rateLimitTier: MAX_20X_RATE_LIMIT_TIER,
      }),
    };
    expect(await isAlreadyOnMax20x(deps)).toBe(true);
  });

  it('isAlreadyOnMax20x returns false when subscriptionType is not max', async () => {
    const deps: UpgradeCommandDeps = {
      ...makeEnabledDeps(),
      getOAuthTokenInfo: () => ({
        subscriptionType: 'pro',
        rateLimitTier: MAX_20X_RATE_LIMIT_TIER,
      }),
    };
    expect(await isAlreadyOnMax20x(deps)).toBe(false);
  });

  it('falls back to profile fetch when tokenInfo is null', async () => {
    const deps: UpgradeCommandDeps = {
      ...makeEnabledDeps(),
      getOAuthTokenInfo: () => null,
      getOAuthProfileFromToken: async () => ({
        organization_type: 'cloud_max',
        rate_limit_tier: MAX_20X_RATE_LIMIT_TIER,
      }),
    };
    expect(await isAlreadyOnMax20x(deps)).toBe(true);
  });

  it('execute returns "already have Max" message when on 20x', async () => {
    let loginCalled = false;
    setUpgradeCommandDeps({
      ...makeEnabledDeps(),
      getOAuthTokenInfo: () => ({
        subscriptionType: 'max',
        rateLimitTier: MAX_20X_RATE_LIMIT_TIER,
      }),
      renderLoginComponent: async () => { loginCalled = true; return false; },
    });
    const result = await upgradeCommand.execute('', makeCtx());
    expect(loginCalled).toBe(false);
    expect(result?.type).toBe('message');
    expect(result?.message).toContain('already');
  });
});

// ---------------------------------------------------------------------------
// AC5: Standard upgrade flow opens UPGRADE_URL.
// ---------------------------------------------------------------------------

describe('AC5 — standard upgrade flow', () => {
  it('opens UPGRADE_URL in the browser', async () => {
    const openedUrls: string[] = [];
    setUpgradeCommandDeps({
      ...makeEnabledDeps(),
      openBrowser: async (url) => { openedUrls.push(url); return true; },
    });
    await upgradeCommand.execute('', makeCtx());
    expect(openedUrls).toContain(UPGRADE_URL);
  });
});

// ---------------------------------------------------------------------------
// AC6: onChangeAPIKey called after successful re-login.
// ---------------------------------------------------------------------------

describe('AC6 — onChangeAPIKey called after login success', () => {
  it('calls onChangeAPIKey when renderLoginComponent returns true', async () => {
    let apiKeyCalled = false;
    setUpgradeCommandDeps({
      ...makeEnabledDeps(),
      renderLoginComponent: async () => true,
      onChangeAPIKey: () => { apiKeyCalled = true; },
    });
    await upgradeCommand.execute('', makeCtx());
    expect(apiKeyCalled).toBe(true);
  });

  it('does NOT call onChangeAPIKey when login cancelled', async () => {
    let apiKeyCalled = false;
    setUpgradeCommandDeps({
      ...makeEnabledDeps(),
      renderLoginComponent: async () => false,
      onChangeAPIKey: () => { apiKeyCalled = true; },
    });
    await upgradeCommand.execute('', makeCtx());
    expect(apiKeyCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC7: Browser failures handled gracefully (no throw).
// ---------------------------------------------------------------------------

describe('AC7 — browser failures are graceful', () => {
  it('does not throw when openBrowser rejects', async () => {
    setUpgradeCommandDeps({
      ...makeEnabledDeps(),
      openBrowser: async () => { throw new Error('no browser'); },
    });
    const result = await upgradeCommand.execute('', makeCtx());
    // Should return a message pointing to the URL
    expect(result?.message).toContain(UPGRADE_URL);
  });
});

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

describe('constants', () => {
  it('UPGRADE_URL is the expected ember.ai URL', () => {
    expect(UPGRADE_URL).toBe('https://ember.ai/upgrade/max');
  });

  it('MAX_20X_RATE_LIMIT_TIER has the expected value', () => {
    expect(MAX_20X_RATE_LIMIT_TIER).toBe('default_cloud_max_20x');
  });
});
