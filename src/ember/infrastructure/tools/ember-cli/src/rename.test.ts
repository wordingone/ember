// Tests for the rename slash command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  renameCommand,
  setRenameDeps,
  resetRenameDeps,
} from './rename.ts';
import type { CommandContext } from '../types/command-types.ts';
import type { Message } from '../types/message-types.ts';

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

const baseContext: CommandContext = {
  sessionId: 'session-abc',
  mode: 'default',
  cwd: '/proj',
};

beforeEach(() => {
  resetRenameDeps();
});

// ---------------------------------------------------------------------------
// AC1: Teammate sessions and sessions without an ID are rejected.
// ---------------------------------------------------------------------------
describe('AC1: guards', () => {
  it('rejects teammate sessions with an error message', async () => {
    setRenameDeps({ isTeammate: () => true });
    const result = await renameCommand.execute('my-name', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toMatch(/teammate/i);
  });

  it('rejects when no session ID is available', async () => {
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => undefined,
    });
    // Use a context with no sessionId
    const noSessCtx: CommandContext = { sessionId: '' as unknown as string, mode: 'default', cwd: '/' };
    const result = await renameCommand.execute('my-name', noSessCtx);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toMatch(/no active session/i);
  });

  it('proceeds when isTeammate returns false and session ID exists', async () => {
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/transcripts/session-abc.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
    });

    const result = await renameCommand.execute('my-name', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    // Should NOT be an error about teammate / no session
    expect((result as { message?: string }).message).not.toMatch(/teammate|no active session/i);
  });
});

// ---------------------------------------------------------------------------
// AC2: With a name argument, the name is applied directly without a model call.
// ---------------------------------------------------------------------------
describe('AC2: manual rename', () => {
  it('saves the provided name without calling queryLocalModel', async () => {
    let haikuCalled = false;
    let savedName = '';
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      queryLocalModel: async () => { haikuCalled = true; return null; },
      saveCustomTitle: async (_sid, name) => { savedName = name; },
      saveAgentName: async () => {},
    });

    await renameCommand.execute('fix-login-bug', baseContext);
    expect(haikuCalled).toBe(false);
    expect(savedName).toBe('fix-login-bug');
  });

  it('returns a confirmation message including the new name', async () => {
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
    });

    const result = await renameCommand.execute('refactor-api-client', baseContext);
    expect((result as { message?: string }).message).toContain('refactor-api-client');
  });
});

// ---------------------------------------------------------------------------
// AC3: Without a name argument, Haiku is called with kebab-case generation prompt.
// ---------------------------------------------------------------------------
describe('AC3: auto-rename via Haiku', () => {
  it('calls queryLocalModel when no argument is provided', async () => {
    let haikuCalled = false;
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      getMessages: () => [makeMsg('Fix the login bug')],
      extractConversationText: (msgs) => msgs.map((m) => {
        const c = m.content as Array<{ type: string; text?: string }>;
        return c.filter((b) => b.type === 'text').map((b) => b.text ?? '').join('');
      }).join('\n'),
      queryLocalModel: async (_prompt, _ctx, _tag) => {
        haikuCalled = true;
        return { name: 'fix-login-bug' };
      },
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
    });

    await renameCommand.execute('', baseContext);
    expect(haikuCalled).toBe(true);
  });

  it('uses the name returned by Haiku', async () => {
    let savedName = '';
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      getMessages: () => [makeMsg('some context')],
      extractConversationText: () => 'some context',
      queryLocalModel: async () => ({ name: 'generated-name' }),
      saveCustomTitle: async (_sid, name) => { savedName = name; },
      saveAgentName: async () => {},
    });

    await renameCommand.execute('', baseContext);
    expect(savedName).toBe('generated-name');
  });

  it('passes the rename_generate_name source tag to queryLocalModel', async () => {
    let capturedTag = '';
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      getMessages: () => [makeMsg('context')],
      extractConversationText: () => 'context',
      queryLocalModel: async (_prompt, _ctx, tag) => { capturedTag = tag; return { name: 'x' }; },
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
    });

    await renameCommand.execute('', baseContext);
    expect(capturedTag).toBe('rename_generate_name');
  });
});

// ---------------------------------------------------------------------------
// AC4: No conversation context → error returned (no model call).
// ---------------------------------------------------------------------------
describe('AC4: no conversation context guard', () => {
  it('returns an error without calling queryLocalModel when conversation is empty', async () => {
    let haikuCalled = false;
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      getMessages: () => [],
      extractConversationText: () => '',
      queryLocalModel: async () => { haikuCalled = true; return null; },
    });

    const result = await renameCommand.execute('', baseContext);
    expect(haikuCalled).toBe(false);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toMatch(/no conversation context/i);
  });
});

// ---------------------------------------------------------------------------
// AC5: Name persisted via saveCustomTitle; app state updated; saveAgentName called.
// ---------------------------------------------------------------------------
describe('AC5: persistence and app state', () => {
  it('calls saveCustomTitle with the correct session ID, name, and path', async () => {
    const calls: Array<{ sid: string; name: string; path: string }> = [];
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/path/to/transcript.jsonl',
      saveCustomTitle: async (sid, name, path) => { calls.push({ sid, name, path }); },
      saveAgentName: async () => {},
    });

    await renameCommand.execute('new-session-name', baseContext);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      sid: 'session-abc',
      name: 'new-session-name',
      path: '/path/to/transcript.jsonl',
    });
  });

  it('updates standaloneAgentContext.name in-place', async () => {
    const ctx = { name: 'old-name' };
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
      getStandaloneAgentContext: () => ctx,
    });

    await renameCommand.execute('new-name', baseContext);
    expect(ctx.name).toBe('new-name');
  });

  it('calls saveAgentName with the same args as saveCustomTitle', async () => {
    const agentCalls: Array<{ sid: string; name: string; path: string }> = [];
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async (sid, name, path) => { agentCalls.push({ sid, name, path }); },
    });

    await renameCommand.execute('the-name', baseContext);
    expect(agentCalls).toHaveLength(1);
    expect(agentCalls[0]).toMatchObject({ sid: 'session-abc', name: 'the-name', path: '/t.jsonl' });
  });
});

// ---------------------------------------------------------------------------
// AC6: Bridge session title synced best-effort when bridge ID exists.
// ---------------------------------------------------------------------------
describe('AC6: bridge sync', () => {
  it('calls updateBridgeSessionTitle when a bridge session ID exists', async () => {
    let bridgeSynced = false;
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
      getReplBridgeSessionId: () => 'bridge-session-xyz',
      updateBridgeSessionTitle: async (_bid, _name) => { bridgeSynced = true; },
    });

    await renameCommand.execute('my-name', baseContext);
    // Give the best-effort fire-and-forget a moment to settle
    await new Promise<void>((r) => setTimeout(r, 10));
    expect(bridgeSynced).toBe(true);
  });

  it('does NOT call updateBridgeSessionTitle when no bridge session', async () => {
    let bridgeCalled = false;
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
      getReplBridgeSessionId: () => undefined,
      updateBridgeSessionTitle: async () => { bridgeCalled = true; },
    });

    await renameCommand.execute('my-name', baseContext);
    await new Promise<void>((r) => setTimeout(r, 10));
    expect(bridgeCalled).toBe(false);
  });

  it('does not propagate bridge sync errors', async () => {
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      saveCustomTitle: async () => {},
      saveAgentName: async () => {},
      getReplBridgeSessionId: () => 'bridge-xyz',
      updateBridgeSessionTitle: async () => { throw new Error('network failure'); },
    });

    await expect(renameCommand.execute('my-name', baseContext)).resolves.toMatchObject({ type: 'message' });
  });
});

// ---------------------------------------------------------------------------
// Haiku null result
// ---------------------------------------------------------------------------
describe('Haiku null result', () => {
  it('returns an error when queryLocalModel returns null', async () => {
    setRenameDeps({
      isTeammate: () => false,
      getSessionId: () => 'session-abc',
      getTranscriptPath: () => '/t.jsonl',
      getMessages: () => [makeMsg('context')],
      extractConversationText: () => 'context',
      queryLocalModel: async () => null,
    });

    const result = await renameCommand.execute('', baseContext);
    expect(result).toMatchObject({ type: 'message' });
    expect((result as { message?: string }).message).toMatch(/model unavailable|could not generate/i);
  });
});
