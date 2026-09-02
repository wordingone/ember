// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for tool-use-summary.ts — maps to spec Acceptance Criteria.

import { describe, it, expect } from 'bun:test';
import {
  generateToolUseSummary,
  truncateJson,
  TRUNCATE_MAX_LENGTH,
  MAX_SUMMARY_LENGTH,
  SUMMARY_MODEL,
  type ModelCallOptions,
  type SummarizedToolCall,
} from './tool-use-summary.ts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeModelCall(response: string): (opts: ModelCallOptions) => Promise<string> {
  return async (_opts) => response;
}

function makeFailingModelCall(): (opts: ModelCallOptions) => Promise<string> {
  return async () => { throw new Error('API unavailable'); };
}

// ---------------------------------------------------------------------------
// AC2: truncateJson
// ---------------------------------------------------------------------------

describe('truncateJson — AC2', () => {
  it('returns full JSON when within limit', () => {
    const obj = { key: 'value', num: 42 };
    const json = JSON.stringify(obj);
    expect(truncateJson(obj)).toBe(json);
  });

  it('truncates to maxLength characters and appends ...', () => {
    const longObj = { content: 'x'.repeat(500) };
    const result = truncateJson(longObj, TRUNCATE_MAX_LENGTH);
    expect(result.length).toBe(TRUNCATE_MAX_LENGTH + 3); // 300 + '...'
    expect(result.endsWith('...')).toBe(true);
  });

  it('respects custom maxLength', () => {
    const result = truncateJson('hello world', 5);
    expect(result).toBe('"hell...');
  });

  it('handles null, numbers, and arrays', () => {
    expect(truncateJson(null)).toBe('null');
    expect(truncateJson(42)).toBe('42');
    expect(truncateJson([1, 2, 3])).toBe('[1,2,3]');
  });
});

// ---------------------------------------------------------------------------
// AC1: Uses Haiku model with enablePromptCaching: true
// ---------------------------------------------------------------------------

describe('generateToolUseSummary — AC1 model call', () => {
  it('calls the model function with Haiku model and enablePromptCaching', async () => {
    let capturedOpts: ModelCallOptions | null = null;

    const modelCallFn = async (opts: ModelCallOptions): Promise<string> => {
      capturedOpts = opts;
      return 'Read file.ts';
    };

    await generateToolUseSummary(
      [{ name: 'Read', input: { file_path: 'file.ts' }, output: 'file contents' }],
      modelCallFn,
    );

    expect(capturedOpts).not.toBeNull();
    const opts = capturedOpts as unknown as ModelCallOptions;
    expect(opts.model).toBe(SUMMARY_MODEL);
    expect(opts.enablePromptCaching).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC2: Each tool's input/output truncated to 300 chars
// ---------------------------------------------------------------------------

describe('generateToolUseSummary — AC2 input/output truncation', () => {
  it('truncates large inputs before sending to model', async () => {
    const largeInput = { data: 'x'.repeat(2000) };
    let capturedContent: string | null = null;

    const modelCallFn = async (opts: ModelCallOptions): Promise<string> => {
      capturedContent = opts.messages[0]?.content ?? '';
      return 'Processed data';
    };

    await generateToolUseSummary(
      [{ name: 'Write', input: largeInput, output: 'ok' }],
      modelCallFn,
    );

    // The prompt content should contain the truncated input (max 300 chars + '...')
    expect(capturedContent).not.toBeNull();
    const inputPart = capturedContent!;
    // Check that no raw un-truncated version appears
    expect(inputPart.includes('x'.repeat(301))).toBe(false);
  });

  it('truncates large outputs before sending to model', async () => {
    const largeOutput = 'z'.repeat(2000);
    let capturedContent: string | null = null;

    const modelCallFn = async (opts: ModelCallOptions): Promise<string> => {
      capturedContent = opts.messages[0]?.content ?? '';
      return 'Read data';
    };

    await generateToolUseSummary(
      [{ name: 'Read', input: {}, output: largeOutput }],
      modelCallFn,
    );

    expect(capturedContent!.includes('z'.repeat(301))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: Returned summary is at most 30 characters
// ---------------------------------------------------------------------------

describe('generateToolUseSummary — AC3 length limit', () => {
  it('trims model output to MAX_SUMMARY_LENGTH characters', async () => {
    const longResponse = 'This is a very long summary that exceeds thirty characters by quite a lot';

    const result = await generateToolUseSummary(
      [{ name: 'Read', input: {}, output: 'ok' }],
      makeModelCall(longResponse),
    );

    expect(result.length).toBeLessThanOrEqual(MAX_SUMMARY_LENGTH);
  });

  it('does not trim short responses', async () => {
    const shortResponse = 'Read file.ts';

    const result = await generateToolUseSummary(
      [{ name: 'Read', input: {}, output: 'ok' }],
      makeModelCall(shortResponse),
    );

    expect(result).toBe(shortResponse);
  });
});

// ---------------------------------------------------------------------------
// AC4: Model call failure returns fallback string, not error
// ---------------------------------------------------------------------------

describe('generateToolUseSummary — AC4 error fallback', () => {
  it('returns fallback (first tool name) when model call fails', async () => {
    let threw = false;
    let result: string | undefined;

    try {
      result = await generateToolUseSummary(
        [{ name: 'Bash', input: { command: 'ls' }, output: 'file1' }],
        makeFailingModelCall(),
      );
    } catch {
      threw = true;
    }

    expect(threw).toBe(false);
    expect(result).toBeDefined();
    // Fallback includes the tool name
    expect(result!.toLowerCase()).toContain('bash');
  });

  it('returns fallback for empty tool calls array', async () => {
    const result = await generateToolUseSummary([], makeFailingModelCall());
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC5: Summary in past-tense verb + noun style (tested via model call content)
// ---------------------------------------------------------------------------

describe('generateToolUseSummary — AC5 prompt style', () => {
  it('prompt instructs past-tense verb + noun style', async () => {
    let capturedPrompt: string | null = null;

    const modelCallFn = async (opts: ModelCallOptions): Promise<string> => {
      capturedPrompt = opts.messages[0]?.content ?? '';
      return 'Created file.ts';
    };

    await generateToolUseSummary(
      [{ name: 'Write', input: { file_path: 'file.ts' }, output: 'ok' }],
      modelCallFn,
    );

    expect(capturedPrompt).not.toBeNull();
    expect(capturedPrompt!).toContain('past-tense');
    expect(capturedPrompt!).toContain('30 characters');
  });

  it('summary returned matches expected past-tense form', async () => {
    const result = await generateToolUseSummary(
      [{ name: 'Read', input: { file_path: 'main.ts' }, output: 'content' }],
      makeModelCall('Read main.ts'),
    );

    expect(result).toBe('Read main.ts');
  });
});
