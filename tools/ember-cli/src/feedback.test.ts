// Tests for feedback command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  feedbackCommand,
  isFeedbackEnabled,
  setFeedbackCommandDeps,
  _resetFeedbackCommandDeps,
  type FeedbackCommandDeps,
} from './feedback.ts';

const makeCtx = () => ({
  sessionId: 'test',
  mode: 'default' as const,
  cwd: '/tmp',
});

const makeEnabledDeps = (): FeedbackCommandDeps => ({
  isManagedCloudPlatform: () => false,
  isEssentialTrafficOnly: () => false,
  isPolicyAllowed: (_p) => true,
  renderFeedbackComponent: async () => {},
});

beforeEach(() => {
  _resetFeedbackCommandDeps();
  delete process.env['USER_TYPE'];
  delete process.env['EMBER_DISABLE_NONESSENTIAL_TRAFFIC'];
});

// ---------------------------------------------------------------------------
// AC1: Disabled on Bedrock / Vertex / Foundry (managed cloud platforms).
// ---------------------------------------------------------------------------

describe('AC1 — disabled on managed cloud platforms', () => {
  it('isFeedbackEnabled returns false when isManagedCloudPlatform is true', () => {
    const deps: FeedbackCommandDeps = {
      ...makeEnabledDeps(),
      isManagedCloudPlatform: () => true,
    };
    expect(isFeedbackEnabled(deps)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC2: Disabled for ant users.
// ---------------------------------------------------------------------------

describe('AC2 — disabled for ant users', () => {
  it('isFeedbackEnabled returns false when USER_TYPE is ant', () => {
    process.env['USER_TYPE'] = 'ant';
    expect(isFeedbackEnabled(makeEnabledDeps())).toBe(false);
    delete process.env['USER_TYPE'];
  });

  it('isFeedbackEnabled returns true for non-ant users', () => {
    process.env['USER_TYPE'] = 'external';
    expect(isFeedbackEnabled(makeEnabledDeps())).toBe(true);
    delete process.env['USER_TYPE'];
  });
});

// ---------------------------------------------------------------------------
// AC3: Disabled in essential-traffic mode.
// ---------------------------------------------------------------------------

describe('AC3 — disabled in essential-traffic mode', () => {
  it('isFeedbackEnabled returns false when isEssentialTrafficOnly is true', () => {
    const deps: FeedbackCommandDeps = {
      ...makeEnabledDeps(),
      isEssentialTrafficOnly: () => true,
    };
    expect(isFeedbackEnabled(deps)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC4: Disabled when allow_product_feedback policy is denied.
// ---------------------------------------------------------------------------

describe('AC4 — disabled when policy denied', () => {
  it('isFeedbackEnabled returns false when allow_product_feedback not permitted', () => {
    const deps: FeedbackCommandDeps = {
      ...makeEnabledDeps(),
      isPolicyAllowed: (p) => p !== 'allow_product_feedback',
    };
    expect(isFeedbackEnabled(deps)).toBe(false);
  });

  it('isFeedbackEnabled returns true when allow_product_feedback is permitted', () => {
    const deps: FeedbackCommandDeps = {
      ...makeEnabledDeps(),
      isPolicyAllowed: () => true,
    };
    expect(isFeedbackEnabled(deps)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC5: Command has alias 'bug'.
// ---------------------------------------------------------------------------

describe('AC5 — alias registered: bug', () => {
  it('aliases array contains "bug"', () => {
    expect(feedbackCommand.aliases).toContain('bug');
  });
});

// ---------------------------------------------------------------------------
// AC6: Args pre-fill the description (renderFeedbackComponent called with args).
// ---------------------------------------------------------------------------

describe('AC6 — args pre-fill description', () => {
  it('renderFeedbackComponent receives args text as initialDescription', async () => {
    let capturedDesc: string | undefined;
    setFeedbackCommandDeps({
      ...makeEnabledDeps(),
      renderFeedbackComponent: async (_ctx, desc) => { capturedDesc = desc; },
    });
    await feedbackCommand.execute('  my feedback text  ', makeCtx());
    expect(capturedDesc).toBe('my feedback text');
  });

  it('passes empty string when no args', async () => {
    let capturedDesc: string | undefined;
    setFeedbackCommandDeps({
      ...makeEnabledDeps(),
      renderFeedbackComponent: async (_ctx, desc) => { capturedDesc = desc; },
    });
    await feedbackCommand.execute('', makeCtx());
    expect(capturedDesc).toBe('');
  });
});

// ---------------------------------------------------------------------------
// Execute returns message when feedback disabled.
// ---------------------------------------------------------------------------

describe('execute when disabled', () => {
  it('returns message when feedback is disabled at execute time', async () => {
    setFeedbackCommandDeps({
      isManagedCloudPlatform: () => true,
      isEssentialTrafficOnly: () => false,
      isPolicyAllowed: () => true,
      renderFeedbackComponent: async () => {},
    });
    const result = await feedbackCommand.execute('', makeCtx());
    expect(result?.type).toBe('message');
    expect(result?.message).toContain('not available');
  });
});

// ---------------------------------------------------------------------------
// Execute returns none when feedback rendered.
// ---------------------------------------------------------------------------

describe('execute when enabled', () => {
  it('returns type none after rendering', async () => {
    setFeedbackCommandDeps(makeEnabledDeps());
    const result = await feedbackCommand.execute('', makeCtx());
    expect(result?.type).toBe('none');
  });
});

// ---------------------------------------------------------------------------
// Command type is local-jsx.
// ---------------------------------------------------------------------------

describe('command type', () => {
  it('type is local-jsx', () => {
    expect(feedbackCommand.type).toBe('local-jsx');
  });

  it('name is feedback', () => {
    expect(feedbackCommand.name).toBe('feedback');
  });
});
