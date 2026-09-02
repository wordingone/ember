// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for the clear (/reset, /new) slash command.

import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import {
  clearCommand,
  setClearCommandDeps,
  resetClearCommandDeps,
} from './clear.ts';
import type { CommandContext } from '../types/command-types.ts';
import type { Message } from '../types/message-types.ts';
import type { ClearTask } from './clear.ts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMsg(text: string): Message {
  return {
    role: 'user',
    content: [{ type: 'text', text }],
    uuid: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  } as Message;
}

function makeTask(overrides: Partial<ClearTask> = {}): ClearTask {
  return {
    taskType: 'LocalAgentTask',
    isBackgrounded: true,
    agentId: crypto.randomUUID(),
    ...overrides,
  };
}

const baseContext: CommandContext = {
  sessionId: 'old-session-id',
  mode: 'default',
  cwd: '/proj',
};

beforeEach(() => {
  resetClearCommandDeps();
  delete process.env['USER_TYPE'];
  delete process.env['EMBER_SESSION_ID'];
});

afterEach(() => {
  delete process.env['USER_TYPE'];
  delete process.env['EMBER_SESSION_ID'];
});

// ---------------------------------------------------------------------------
// AC1: After /clear, message history is empty and a new session ID is in use.
// ---------------------------------------------------------------------------
describe('AC1: session reset', () => {
  it('sets messages to empty array', async () => {
    let capturedMessages: Message[] | undefined;
    setClearCommandDeps({
      setMessages: (msgs) => { capturedMessages = msgs; },
      regenerateSessionId: () => 'new-session-123',
    });

    await clearCommand.execute('', baseContext);
    expect(capturedMessages).toEqual([]);
  });

  it('calls regenerateSessionId with the old session ID', async () => {
    let oldId = '';
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: (opts) => { oldId = opts.oldSessionId; return 'new-id'; },
    });

    await clearCommand.execute('', baseContext);
    expect(oldId).toBe('old-session-id');
  });

  it('calls resetSessionFilePointer with the new session ID', async () => {
    let resetWith = '';
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'brand-new-session',
      resetSessionFilePointer: (id) => { resetWith = id; },
    });

    await clearCommand.execute('', baseContext);
    expect(resetWith).toBe('brand-new-session');
  });

  it('has aliases reset and new', () => {
    expect(clearCommand.aliases).toContain('reset');
    expect(clearCommand.aliases).toContain('new');
  });
});

// ---------------------------------------------------------------------------
// AC2: Backgrounded agent task remains running and gets transcript symlink.
// ---------------------------------------------------------------------------
describe('AC2: backgrounded agent preserved and relinked', () => {
  it('does NOT kill a backgrounded task', async () => {
    let killed = false;
    const bgTask = makeTask({ isBackgrounded: true });

    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-id',
      getTasks: () => [bgTask],
      killTask: () => { killed = true; },
    });

    await clearCommand.execute('', baseContext);
    expect(killed).toBe(false);
  });

  it('calls relinkBackgroundedAgents with new session ID and preserved agent IDs', async () => {
    let relinkedSessionId = '';
    let relinkedAgentIds: string[] = [];
    const agentId = 'agent-abc';
    const bgTask = makeTask({ isBackgrounded: true, agentId, taskType: 'LocalAgentTask' });

    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-session',
      getTasks: () => [bgTask],
      relinkBackgroundedAgents: (sid, aids) => {
        relinkedSessionId = sid;
        relinkedAgentIds = aids;
      },
    });

    await clearCommand.execute('', baseContext);
    expect(relinkedSessionId).toBe('new-session');
    expect(relinkedAgentIds).toContain(agentId);
  });
});

// ---------------------------------------------------------------------------
// AC3: Foreground task is killed.
// ---------------------------------------------------------------------------
describe('AC3: foreground task killed', () => {
  it('calls killTask for foreground (isBackgrounded === false) tasks', async () => {
    const killed: ClearTask[] = [];
    const fgTask = makeTask({ isBackgrounded: false });

    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-id',
      getTasks: () => [fgTask],
      killTask: (t) => killed.push(t),
    });

    await clearCommand.execute('', baseContext);
    expect(killed).toContain(fgTask);
  });

  it('does NOT call relinkBackgroundedAgents when no backgrounded agents', async () => {
    let relinkCalled = false;
    const fgTask = makeTask({ isBackgrounded: false, taskType: 'LocalAgentTask' });

    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-id',
      getTasks: () => [fgTask],
      relinkBackgroundedAgents: () => { relinkCalled = true; },
    });

    await clearCommand.execute('', baseContext);
    expect(relinkCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC4: Session-start hooks run after clear; their messages appear in new conversation.
// ---------------------------------------------------------------------------
describe('AC4: session-start hooks', () => {
  it('runs session-start hooks with "clear" source', async () => {
    let hookSource = '';
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-id',
      runSessionStartHooks: async (src) => { hookSource = src; return []; },
    });

    await clearCommand.execute('', baseContext);
    expect(hookSource).toBe('clear');
  });

  it('sets hook messages as initial messages when hooks return messages', async () => {
    const hookMsg = makeMsg('hook init');
    let lastMessages: Message[] = [];

    setClearCommandDeps({
      setMessages: (msgs) => { lastMessages = msgs; },
      regenerateSessionId: () => 'new-id',
      runSessionStartHooks: async () => [hookMsg],
    });

    await clearCommand.execute('', baseContext);
    expect(lastMessages).toContain(hookMsg);
  });
});

// ---------------------------------------------------------------------------
// AC5: Working directory reset to original CWD.
// ---------------------------------------------------------------------------
describe('AC5: working directory reset', () => {
  it('calls resetWorkingDirectory during clear', async () => {
    let resetCalled = false;
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-id',
      resetWorkingDirectory: () => { resetCalled = true; },
    });

    await clearCommand.execute('', baseContext);
    expect(resetCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC6: Session-end hooks run before the clear; cache-eviction event emitted.
// ---------------------------------------------------------------------------
describe('AC6: session-end hooks and cache eviction', () => {
  it('runs session-end hooks before clearing messages', async () => {
    const callOrder: string[] = [];
    setClearCommandDeps({
      runSessionEndHooks: async () => { callOrder.push('end-hooks'); },
      setMessages: () => { callOrder.push('set-messages'); },
      regenerateSessionId: () => 'new-id',
    });

    await clearCommand.execute('', baseContext);
    expect(callOrder.indexOf('end-hooks')).toBeLessThan(callOrder.indexOf('set-messages'));
  });

  it('emits cache-eviction event with scope "conversation_clear"', async () => {
    let evictedScope = '';
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'new-id',
      emitCacheEvictionEvent: (scope) => { evictedScope = scope; },
    });

    await clearCommand.execute('', baseContext);
    expect(evictedScope).toBe('conversation_clear');
  });
});

// ---------------------------------------------------------------------------
// AC7: USER_TYPE === "ant" updates EMBER_SESSION_ID.
// ---------------------------------------------------------------------------
describe('AC7: ant user type', () => {
  it('updates EMBER_SESSION_ID when USER_TYPE is "ant"', async () => {
    process.env['USER_TYPE'] = 'ant';
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'ant-new-session',
    });

    await clearCommand.execute('', baseContext);
    expect(process.env['EMBER_SESSION_ID']).toBe('ant-new-session');
  });

  it('does NOT update EMBER_SESSION_ID when USER_TYPE is not "ant"', async () => {
    process.env['USER_TYPE'] = 'other';
    setClearCommandDeps({
      setMessages: () => {},
      regenerateSessionId: () => 'normal-new-session',
    });

    await clearCommand.execute('', baseContext);
    expect(process.env['EMBER_SESSION_ID']).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Availability
// ---------------------------------------------------------------------------
describe('availability', () => {
  it('is disabled when isInteractive returns false', () => {
    setClearCommandDeps({ isInteractive: () => false });
    expect(clearCommand.isEnabled()).toBe(false);
  });

  it('is enabled when isInteractive returns true', () => {
    setClearCommandDeps({ isInteractive: () => true });
    expect(clearCommand.isEnabled()).toBe(true);
  });
});
