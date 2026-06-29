// Tests for the resume (/continue) slash command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  resumeCommand,
  setResumeDeps,
  resetResumeDeps,
  handleSessionSelect,
} from './resume.ts';
import type { CommandContext } from '../types/command-types.ts';
import type { LogOption } from '../types/session-persistence-types.ts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeLog(overrides: Partial<LogOption> = {}): LogOption {
  return {
    date: '2024-01-01',
    messages: [],
    fullPath: '/tmp/sess.jsonl',
    value: 1,
    created: new Date('2024-01-01'),
    modified: new Date('2024-01-01'),
    firstPrompt: 'hello world',
    messageCount: 1,
    fileSize: 100,
    isSidechain: false,
    isLite: false,
    sessionId: 'sess-abc',
    projectPath: '/proj',
    ...overrides,
  };
}

const baseContext: CommandContext = {
  sessionId: 'current-session',
  mode: 'default',
  cwd: '/proj',
};

beforeEach(() => {
  resetResumeDeps();
});

// ---------------------------------------------------------------------------
// AC1: /resume and /continue both invoke the same behavior.
// ---------------------------------------------------------------------------
describe('AC1: registration', () => {
  it('has name "resume"', () => {
    expect(resumeCommand.name).toBe('resume');
  });

  it('has alias "continue"', () => {
    expect(resumeCommand.aliases).toContain('continue');
  });

  it('is always enabled', () => {
    expect(resumeCommand.isEnabled()).toBe(true);
  });

  it('has type local-jsx', () => {
    expect(resumeCommand.type).toBe('local-jsx');
  });
});

// ---------------------------------------------------------------------------
// AC2: The current session is excluded from the list.
// ---------------------------------------------------------------------------
describe('AC2: current session excluded', () => {
  it('filters out the current session ID', async () => {
    const currentLog = makeLog({ sessionId: 'current-session' });
    const otherLog = makeLog({ sessionId: 'other-session', firstPrompt: 'other' });
    let capturedSessions: LogOption[] = [];

    setResumeDeps({
      getSessions: async () => [currentLog, otherLog],
      openPicker: async (opts) => {
        capturedSessions = opts.sessions;
        return { type: 'none' as const };
      },
    });

    await resumeCommand.execute('', baseContext);
    expect(capturedSessions.map((s) => s.sessionId)).not.toContain('current-session');
    expect(capturedSessions.map((s) => s.sessionId)).toContain('other-session');
  });
});

// ---------------------------------------------------------------------------
// AC3: Sidechain/sub-agent session logs are excluded.
// ---------------------------------------------------------------------------
describe('AC3: sidechain sessions excluded', () => {
  it('filters out sidechain sessions', async () => {
    const sidechain = makeLog({ sessionId: 'sc-1', isSidechain: true });
    const normal = makeLog({ sessionId: 'normal-1', firstPrompt: 'normal' });
    let capturedSessions: LogOption[] = [];

    setResumeDeps({
      getSessions: async () => [sidechain, normal],
      openPicker: async (opts) => {
        capturedSessions = opts.sessions;
        return { type: 'none' as const };
      },
    });

    await resumeCommand.execute('', baseContext);
    expect(capturedSessions.map((s) => s.sessionId)).not.toContain('sc-1');
    expect(capturedSessions.map((s) => s.sessionId)).toContain('normal-1');
  });
});

// ---------------------------------------------------------------------------
// AC4: Different-project session copies CLI command to clipboard.
// ---------------------------------------------------------------------------
describe('AC4: cross-project → clipboard', () => {
  it('copies "claude -r <id>" to clipboard for different-project session', async () => {
    const log = makeLog({ sessionId: 'remote-sess' });
    let clipboardText = '';

    setResumeDeps({
      checkCrossProjectResume: () => ({ type: 'different-project' }),
      writeToClipboard: (t) => { clipboardText = t; },
    });

    const result = await handleSessionSelect(log, '/other-proj');

    expect(clipboardText).toContain('remote-sess');
    expect(result).toMatchObject({ type: 'message' });
  });

  it('does not call onResume for different-project sessions', async () => {
    const log = makeLog({ sessionId: 'remote-sess' });
    let resumeCalled = false;

    setResumeDeps({
      checkCrossProjectResume: () => ({ type: 'different-project' }),
      writeToClipboard: () => {},
      onResume: () => { resumeCalled = true; },
    });

    await handleSessionSelect(log, '/other-proj');
    expect(resumeCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC5: Lite log entries are fully loaded before resuming.
// ---------------------------------------------------------------------------
describe('AC5: lite log loaded before resume', () => {
  it('calls loadFullLog for lite entries', async () => {
    const liteLog = makeLog({ sessionId: 'lite-sess', isLite: true });
    const fullLog = makeLog({ sessionId: 'lite-sess', isLite: false, firstPrompt: 'full' });
    let loadCalled = false;
    let resumedWith: LogOption | undefined;

    setResumeDeps({
      loadFullLog: async () => { loadCalled = true; return fullLog; },
      checkCrossProjectResume: () => ({ type: 'same-dir' }),
      onResume: (_id, log) => { resumedWith = log; },
    });

    await handleSessionSelect(liteLog, '/proj');
    expect(loadCalled).toBe(true);
    expect(resumedWith?.isLite).toBe(false);
  });

  it('does not call loadFullLog for non-lite entries', async () => {
    const log = makeLog({ isLite: false });
    let loadCalled = false;

    setResumeDeps({
      loadFullLog: async () => { loadCalled = true; return log; },
      checkCrossProjectResume: () => ({ type: 'same-dir' }),
      onResume: () => {},
    });

    await handleSessionSelect(log, '/proj');
    expect(loadCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC6: All-projects toggle (verified via filterResumableSessions dep).
// ---------------------------------------------------------------------------
describe('AC6: all-projects filtering', () => {
  it('uses custom filterResumableSessions when provided (overrides default filter)', async () => {
    const logs = [
      makeLog({ sessionId: 's1', projectPath: '/proj-a' }),
      makeLog({ sessionId: 's2', projectPath: '/proj-b' }),
    ];
    let capturedSessions: LogOption[] = [];

    setResumeDeps({
      getSessions: async () => logs,
      // Simulate "all projects" mode: return everything
      filterResumableSessions: (allLogs) => allLogs,
      openPicker: async (opts) => {
        capturedSessions = opts.sessions;
        return { type: 'none' as const };
      },
    });

    await resumeCommand.execute('', baseContext);
    expect(capturedSessions).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Headless path: error messages for search term misses
// ---------------------------------------------------------------------------
describe('headless fallback', () => {
  it('returns session-not-found message when search term has no match', async () => {
    setResumeDeps({
      getSessions: async () => [makeLog({ firstPrompt: 'buy groceries' })],
      resumeHelpMessage: () => 'Session not found',
    });

    const result = await resumeCommand.execute('nonexistent-term', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toContain('not found');
  });

  it('returns multiple-matches message when search term matches more than one', async () => {
    const logs = [
      makeLog({ sessionId: 's1', firstPrompt: 'fix bug' }),
      makeLog({ sessionId: 's2', firstPrompt: 'fix issue' }),
    ];

    setResumeDeps({
      getSessions: async () => logs,
      resumeHelpMessage: () => 'Multiple sessions match',
    });

    const result = await resumeCommand.execute('fix', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toContain('Multiple');
  });

  it('resumes directly when headless and exactly one match found', async () => {
    const log = makeLog({ sessionId: 'exact-match', firstPrompt: 'unique phrase' });
    let resumedId = '';

    setResumeDeps({
      getSessions: async () => [log],
      checkCrossProjectResume: () => ({ type: 'same-dir' }),
      onResume: (id) => { resumedId = id; },
    });

    await resumeCommand.execute('unique phrase', baseContext);
    expect(resumedId).toBe('exact-match');
  });
});
