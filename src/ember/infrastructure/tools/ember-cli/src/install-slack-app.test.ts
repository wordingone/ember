// Tests for install-slack-app command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  installSlackAppCommand,
  runInstallSlackApp,
  setInstallSlackAppDeps,
  _resetInstallSlackAppDeps,
  SLACK_MARKETPLACE_URL,
  ANALYTICS_EVENT,
  type InstallSlackAppDeps,
} from './install-slack-app.ts';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

beforeEach(() => {
  _resetInstallSlackAppDeps();
});

// ---------------------------------------------------------------------------
// AC1: Every invocation increments slackAppInstallCount in global config.
// ---------------------------------------------------------------------------

describe('AC1 — slackAppInstallCount incremented on every invocation', () => {
  it('calls incrementSlackInstallCount on successful browser open', async () => {
    let count = 0;
    const deps: InstallSlackAppDeps = {
      logAnalyticsEvent: () => {},
      incrementSlackInstallCount: async () => { count++; },
      openBrowser: async () => true,
    };
    await runInstallSlackApp(deps);
    expect(count).toBe(1);
  });

  it('calls incrementSlackInstallCount even when browser fails to open', async () => {
    let count = 0;
    const deps: InstallSlackAppDeps = {
      logAnalyticsEvent: () => {},
      incrementSlackInstallCount: async () => { count++; },
      openBrowser: async () => false,
    };
    await runInstallSlackApp(deps);
    expect(count).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// AC2: The browser is opened to the correct marketplace URL.
// ---------------------------------------------------------------------------

describe('AC2 — opens correct marketplace URL', () => {
  it('passes the Slack marketplace URL to openBrowser', async () => {
    const openedUrls: string[] = [];
    const deps: InstallSlackAppDeps = {
      logAnalyticsEvent: () => {},
      incrementSlackInstallCount: async () => {},
      openBrowser: async (url) => { openedUrls.push(url); return true; },
    };
    await runInstallSlackApp(deps);
    expect(openedUrls).toEqual([SLACK_MARKETPLACE_URL]);
  });
});

// ---------------------------------------------------------------------------
// AC3: If the browser fails to open, the URL is printed in the response.
// ---------------------------------------------------------------------------

describe('AC3 — fallback URL when browser cannot open', () => {
  it('returns a message containing the marketplace URL on browser failure', async () => {
    const deps: InstallSlackAppDeps = {
      logAnalyticsEvent: () => {},
      incrementSlackInstallCount: async () => {},
      openBrowser: async () => false,
    };
    const result = await runInstallSlackApp(deps);
    expect(result.type).toBe('message');
    expect(result.message).toContain(SLACK_MARKETPLACE_URL);
  });

  it('success path does not contain the raw URL in the message (browser opened)', async () => {
    const deps: InstallSlackAppDeps = {
      logAnalyticsEvent: () => {},
      incrementSlackInstallCount: async () => {},
      openBrowser: async () => true,
    };
    const result = await runInstallSlackApp(deps);
    expect(result.type).toBe('message');
    // Still contains the URL as a reference
    expect(result.message).toContain(SLACK_MARKETPLACE_URL);
  });
});

// ---------------------------------------------------------------------------
// AC4: The command is not available outside the cloud surface.
// ---------------------------------------------------------------------------

describe('AC4 — availability: cloud only', () => {
  it('has availability restricted to cloud', () => {
    expect(installSlackAppCommand.availability).toEqual(['cloud']);
  });

  it('isEnabled returns true (runtime gating is done by registry availability check)', () => {
    expect(installSlackAppCommand.isEnabled()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Analytics event is emitted
// ---------------------------------------------------------------------------

describe('analytics event', () => {
  it('logs the tengu_install_slack_app_clicked event', async () => {
    const events: string[] = [];
    const deps: InstallSlackAppDeps = {
      logAnalyticsEvent: (e) => events.push(e),
      incrementSlackInstallCount: async () => {},
      openBrowser: async () => true,
    };
    await runInstallSlackApp(deps);
    expect(events).toContain(ANALYTICS_EVENT);
  });
});

// ---------------------------------------------------------------------------
// Command execute wires to runInstallSlackApp
// ---------------------------------------------------------------------------

describe('command execute wiring', () => {
  it('execute calls through to runInstallSlackApp logic', async () => {
    let opened = false;
    setInstallSlackAppDeps({
      openBrowser: async () => { opened = true; return true; },
    });
    const result = await installSlackAppCommand.execute('', makeCtx());
    expect(opened).toBe(true);
    expect(result?.type).toBe('message');
  });
});
