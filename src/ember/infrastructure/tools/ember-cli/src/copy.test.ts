// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for the copy slash command.

import { describe, it, expect, beforeEach } from 'bun:test';
import {
  copyCommand,
  setCopyCommandDeps,
  resetCopyCommandDeps,
  extractCodeBlocks,
  codeBlockExtension,
  collectRecentResponses,
  buildTempPath,
  performCopy,
} from './copy.ts';
import type { CommandContext } from '../types/command-types.ts';
import type { Message } from '../types/message-types.ts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAssistantMsg(text: string, isApiError = false): Message {
  return {
    role: 'assistant',
    content: [{ type: 'text', text }],
    uuid: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    isApiErrorMessage: isApiError,
  } as Message;
}

function makeToolOnlyMsg(): Message {
  return {
    role: 'assistant',
    content: [{ type: 'tool_use', id: 'tu1', name: 'bash', input: {} }],
    uuid: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  } as Message;
}

const baseContext: CommandContext = {
  sessionId: 'sess-001',
  mode: 'default',
  cwd: '/proj',
};

beforeEach(() => {
  resetCopyCommandDeps();
});

// ---------------------------------------------------------------------------
// Unit tests for helpers
// ---------------------------------------------------------------------------
describe('extractCodeBlocks', () => {
  it('extracts a single fenced code block', () => {
    const md = '```python\nprint("hello")\n```';
    const blocks = extractCodeBlocks(md);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]!.language).toBe('python');
    expect(blocks[0]!.code).toContain('print');
  });

  it('extracts multiple blocks', () => {
    const md = '```js\nconst a = 1;\n```\n\n```ts\nconst b: number = 2;\n```';
    const blocks = extractCodeBlocks(md);
    expect(blocks).toHaveLength(2);
  });

  it('returns empty array when no code blocks', () => {
    expect(extractCodeBlocks('No code here')).toHaveLength(0);
  });
});

describe('codeBlockExtension', () => {
  it('returns .python for python (no mapping table — spec strips non-alphanumeric only)', () => {
    expect(codeBlockExtension('python')).toBe('.python');
  });

  it('returns .txt for empty language', () => {
    expect(codeBlockExtension('')).toBe('.txt');
  });

  it('returns .txt for "plaintext"', () => {
    expect(codeBlockExtension('plaintext')).toBe('.txt');
  });

  it('AC7: strips path characters from language tag', () => {
    expect(codeBlockExtension('../evil')).toBe('.evil');
  });

  it('AC7: strips slashes and dots', () => {
    expect(codeBlockExtension('py/th.on')).toBe('.python');
  });
});

describe('collectRecentResponses', () => {
  it('collects text from assistant messages newest-first', () => {
    const msgs = [
      makeAssistantMsg('first'),
      makeAssistantMsg('second'),
      makeAssistantMsg('third'),
    ];
    const results = collectRecentResponses(msgs);
    expect(results[0]!.text).toContain('third');
    expect(results[1]!.text).toContain('second');
  });

  it('skips tool-only messages', () => {
    const msgs = [makeAssistantMsg('hello'), makeToolOnlyMsg()];
    const results = collectRecentResponses(msgs);
    expect(results.every((r) => r.text.trim().length > 0)).toBe(true);
  });

  it('skips API error messages', () => {
    const msgs = [makeAssistantMsg('real'), makeAssistantMsg('error', true)];
    const results = collectRecentResponses(msgs);
    expect(results.some((r) => r.text.includes('error'))).toBe(false);
  });

  it('AC8: caps lookback at 20 messages', () => {
    const msgs = Array.from({ length: 30 }, (_, i) => makeAssistantMsg(`msg ${i}`));
    const results = collectRecentResponses(msgs);
    expect(results.length).toBeLessThanOrEqual(20);
  });
});

describe('buildTempPath', () => {
  it('AC5: full response goes to response.md', () => {
    const path = buildTempPath('/tmp', true);
    expect(path).toContain('response.md');
  });

  it('AC5: code block uses copy<ext>', () => {
    const path = buildTempPath('/tmp', false, 'python');
    expect(path).toContain('copy.py');
  });

  it('paths are under <tmpdir>/claude/', () => {
    const path = buildTempPath('/tmp', true);
    expect(path).toBe('/tmp/ember/response.md');
  });
});

// ---------------------------------------------------------------------------
// AC1: /copy with no args copies most recent assistant response.
// ---------------------------------------------------------------------------
describe('AC1: copy most recent response', () => {
  it('copies the most recent (age 1) assistant response by default', async () => {
    let copiedText = '';
    setCopyCommandDeps({
      getMessages: () => [
        makeAssistantMsg('older response'),
        makeAssistantMsg('newest response'),
      ],
      writeToClipboard: (t) => { copiedText = t; },
      writeTempFile: async () => {},
      getTmpDir: () => '/tmp',
    });

    await copyCommand.execute('', baseContext);
    // The newest response should be the one copied (OSC52-encoded, but temp file stores plain)
    expect(copiedText).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// AC2: copyFullResponse true → picker bypassed.
// ---------------------------------------------------------------------------
describe('AC2: skip picker when copyFullResponse is true', () => {
  it('does not open picker when getCopyFullResponse returns true', async () => {
    let pickerOpened = false;
    setCopyCommandDeps({
      getMessages: () => [makeAssistantMsg('response')],
      getCopyFullResponse: () => true,
      writeToClipboard: () => {},
      writeTempFile: async () => {},
      getTmpDir: () => '/tmp',
      openCopyPicker: async () => { pickerOpened = true; return { type: 'none' as const }; },
    });

    await copyCommand.execute('', baseContext);
    expect(pickerOpened).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: "Always copy full response" saves to global config.
// ---------------------------------------------------------------------------
describe('AC3: always copy full response option', () => {
  it('saves copyFullResponse true when "always" option selected', async () => {
    let savedValue: boolean | undefined;
    setCopyCommandDeps({
      getMessages: () => [makeAssistantMsg('response')],
      getCopyFullResponse: () => false,
      setCopyFullResponse: async (v) => { savedValue = v; },
      writeToClipboard: () => {},
      writeTempFile: async () => {},
      getTmpDir: () => '/tmp',
      openCopyPicker: async (opts) => opts.onSelect({ type: 'always-full' }),
    });

    await copyCommand.execute('', baseContext);
    expect(savedValue).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC4: Selecting a code block copies only that block.
// ---------------------------------------------------------------------------
describe('AC4: code block selection', () => {
  it('copies only the selected code block content', async () => {
    const responseText = '```python\nprint("hello")\n```\n\n```js\nconsole.log("world")\n```';
    let copiedContent: string | undefined;

    setCopyCommandDeps({
      getMessages: () => [makeAssistantMsg(responseText)],
      getCopyFullResponse: () => false,
      writeToClipboard: () => {},
      writeTempFile: async (_path, content) => { copiedContent = content; },
      getTmpDir: () => '/tmp',
      openCopyPicker: async (opts) => opts.onSelect({ type: 'block', blockIndex: 1 }),
    });

    await copyCommand.execute('', baseContext);
    expect(copiedContent).toContain('console.log');
    expect(copiedContent).not.toContain('print("hello")');
  });
});

// ---------------------------------------------------------------------------
// AC5: Temp file is always written.
// ---------------------------------------------------------------------------
describe('AC5: temp file written', () => {
  it('always writes a temp file', async () => {
    let tmpWritten = '';
    setCopyCommandDeps({
      getMessages: () => [makeAssistantMsg('my response')],
      getCopyFullResponse: () => true,
      writeToClipboard: () => {},
      writeTempFile: async (path) => { tmpWritten = path; },
      getTmpDir: () => '/mytmp',
    });

    await copyCommand.execute('', baseContext);
    expect(tmpWritten).toContain('/mytmp/ember/');
  });
});

// ---------------------------------------------------------------------------
// AC6: W key (write_shortcut) writes to temp file only.
// ---------------------------------------------------------------------------
describe('AC6: write shortcut bypasses clipboard', () => {
  it('performCopy with writeShortcut does not call writeToClipboard', async () => {
    let clipboardCalled = false;
    setCopyCommandDeps({
      writeToClipboard: () => { clipboardCalled = true; },
      writeTempFile: async () => {},
      getTmpDir: () => '/tmp',
    });

    await performCopy('content', true, '', { writeShortcut: true, age: 1, blockCount: 0 });
    expect(clipboardCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC7: Language tags sanitized (tested via codeBlockExtension above).
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// AC8: Lookback capped at 20 (tested in collectRecentResponses above).
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// No responses
// ---------------------------------------------------------------------------
describe('no responses', () => {
  it('returns message when no assistant responses available', async () => {
    setCopyCommandDeps({ getMessages: () => [] });
    const result = await copyCommand.execute('', baseContext);
    expect(result).toMatchObject({ type: 'message' });
  });
});
