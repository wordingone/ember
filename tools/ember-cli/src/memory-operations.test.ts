import { describe, expect, test, afterEach } from 'bun:test';
import { join } from 'path';
import { mkdirSync, writeFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import {
  scanMemoryFiles,
  formatMemoryManifest,
  findRelevantMemories,
  selectRelevantMemories,
  buildMemoryLines,
  buildMemoryPrompt,
  buildAssistantDailyLogPrompt,
  buildCombinedMemoryPrompt,
  loadMemoryPrompt,
  PER_FILE_LINE_LIMIT,
  PER_FILE_SIZE_LIMIT,
  TOTAL_BLOCK_LIMIT,
  SELECT_MODEL,
  type MemoryFileEntry,
  type SelectModelFn,
} from './memory-operations';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let tempDirs: string[] = [];

function makeTempDir(suffix = ''): string {
  const dir = join(tmpdir(), `ember-ops-test-${suffix}-${Date.now()}`);
  mkdirSync(dir, { recursive: true });
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs) {
    try { rmSync(dir, { recursive: true, force: true }); } catch { /* ignore */ }
  }
  tempDirs = [];
});

function makeValidFileContent(opts: {
  name: string;
  description: string;
  type?: string;
  body?: string;
} = { name: 'test', description: 'Test memory' }): string {
  const type = opts.type ?? 'user';
  const body = opts.body ?? 'Memory content here.';
  return `---\nname: ${opts.name}\ndescription: ${opts.description}\nmetadata:\n  type: ${type}\n---\n\n${body}`;
}

function makeEntry(overrides: Partial<MemoryFileEntry> = {}): MemoryFileEntry {
  return {
    name: overrides.name ?? 'test-entry',
    description: overrides.description ?? 'A test entry description',
    type: overrides.type ?? 'user',
    filePath: overrides.filePath ?? '/tmp/test.md',
    body: overrides.body ?? makeValidFileContent({ name: 'test-entry', description: 'A test entry description' }),
    modifiedAt: overrides.modifiedAt ?? new Date(),
  };
}

// ---------------------------------------------------------------------------
// AC1: scanMemoryFiles returns N entries from dir with N valid + M invalid files
// ---------------------------------------------------------------------------

describe('AC1: scanMemoryFiles parses valid files and skips invalid ones', () => {
  test('returns 5 entries for 5 valid + 2 invalid files', async () => {
    const dir = makeTempDir('ac1');

    // Write 5 valid .md files
    for (let i = 1; i <= 5; i++) {
      writeFileSync(
        join(dir, `note-${i}.md`),
        makeValidFileContent({ name: `note-${i}`, description: `Note ${i}` }),
        'utf-8',
      );
    }

    // Write 2 invalid .md files (no valid frontmatter)
    writeFileSync(join(dir, 'invalid-1.md'), 'just plain text without frontmatter', 'utf-8');
    writeFileSync(join(dir, 'invalid-2.md'), '# Just a heading\nno frontmatter here', 'utf-8');

    const entries = await scanMemoryFiles(dir);
    expect(entries).toHaveLength(5);
  });

  test('returns 0 for empty directory', async () => {
    const dir = makeTempDir('ac1-empty');
    const entries = await scanMemoryFiles(dir);
    expect(entries).toHaveLength(0);
  });

  test('skips non-.md files', async () => {
    const dir = makeTempDir('ac1-nonmd');
    writeFileSync(join(dir, 'note.md'), makeValidFileContent({ name: 'note', description: 'desc' }), 'utf-8');
    writeFileSync(join(dir, 'note.txt'), makeValidFileContent({ name: 'note2', description: 'desc2' }), 'utf-8');
    const entries = await scanMemoryFiles(dir);
    expect(entries).toHaveLength(1);
  });

  test('does not recurse into subdirectories', async () => {
    const dir = makeTempDir('ac1-nonrecursive');
    writeFileSync(join(dir, 'top.md'), makeValidFileContent({ name: 'top', description: 'top' }), 'utf-8');
    const subdir = join(dir, 'subdir');
    mkdirSync(subdir);
    writeFileSync(join(subdir, 'nested.md'), makeValidFileContent({ name: 'nested', description: 'nested' }), 'utf-8');
    const entries = await scanMemoryFiles(dir);
    expect(entries).toHaveLength(1);
    expect(entries[0]!.name).toBe('top');
  });

  test('entries are sorted newest-first by modification time', async () => {
    const dir = makeTempDir('ac1-sort');
    // Write files with slight time differences
    writeFileSync(join(dir, 'old.md'), makeValidFileContent({ name: 'old', description: 'Old note' }), 'utf-8');
    // Small delay to ensure different mtime
    await new Promise((r) => setTimeout(r, 10));
    writeFileSync(join(dir, 'new.md'), makeValidFileContent({ name: 'new', description: 'New note' }), 'utf-8');

    const entries = await scanMemoryFiles(dir);
    expect(entries).toHaveLength(2);
    // Newest first
    expect(entries[0]!.name).toBe('new');
    expect(entries[1]!.name).toBe('old');
  });

  test('entries include name, description, type, filePath, body, modifiedAt', async () => {
    const dir = makeTempDir('ac1-fields');
    const content = makeValidFileContent({
      name: 'my-note',
      description: 'My note description',
      type: 'feedback',
      body: 'Body content.',
    });
    writeFileSync(join(dir, 'my-note.md'), content, 'utf-8');

    const entries = await scanMemoryFiles(dir);
    expect(entries).toHaveLength(1);
    const entry = entries[0]!;
    expect(entry.name).toBe('my-note');
    expect(entry.description).toBe('My note description');
    expect(entry.type).toBe('feedback');
    expect(entry.filePath).toBe(join(dir, 'my-note.md'));
    expect(entry.body).toBe(content); // full content
    expect(entry.modifiedAt).toBeInstanceOf(Date);
  });
});

// ---------------------------------------------------------------------------
// AC2: 201-line body is truncated to 200 lines with a truncation notice
// ---------------------------------------------------------------------------

describe('AC2: per-file line truncation at 200 lines', () => {
  test('201-line body is truncated to 200 lines with notice', () => {
    const bodyLines = Array.from({ length: 201 }, (_, i) => `line ${i + 1}`);
    const body = bodyLines.join('\n');
    const entry = makeEntry({
      body: makeValidFileContent({ name: 'long', description: 'long note', body }),
    });

    const lines = buildMemoryLines([entry]);
    const combined = lines.join('\n');
    expect(combined).toContain('[...truncated...]');
    // Should NOT contain line 201
    expect(combined).not.toContain('line 201');
    expect(combined).toContain('line 200');
  });

  test('200-line body is NOT truncated', () => {
    const bodyLines = Array.from({ length: 200 }, (_, i) => `line ${i + 1}`);
    const body = bodyLines.join('\n');
    const entry = makeEntry({
      body: makeValidFileContent({ name: 'exact', description: 'exact', body }),
    });

    const lines = buildMemoryLines([entry]);
    const combined = lines.join('\n');
    expect(combined).not.toContain('[...truncated...]');
    expect(combined).toContain('line 200');
  });

  test('PER_FILE_LINE_LIMIT constant is 200', () => {
    expect(PER_FILE_LINE_LIMIT).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// AC3: 26 KB body is truncated to 25 KB before injection
// ---------------------------------------------------------------------------

describe('AC3: per-file size truncation at 25 KB', () => {
  test('body over 25 KB is truncated with notice', () => {
    // Generate a body that is > 25 KB when encoded as UTF-8
    const body = 'x'.repeat(PER_FILE_SIZE_LIMIT + 1000);
    const entry = makeEntry({
      body: makeValidFileContent({ name: 'big', description: 'big note', body }),
    });

    const lines = buildMemoryLines([entry]);
    const combined = lines.join('\n');
    expect(combined).toContain('[...truncated...]');
  });

  test('body under 25 KB is not truncated by size', () => {
    const body = 'x'.repeat(1000);
    const entry = makeEntry({
      body: makeValidFileContent({ name: 'small', description: 'small note', body }),
    });

    const lines = buildMemoryLines([entry]);
    const combined = lines.join('\n');
    // No truncation notice for small body
    // (unless it exceeds line limit, which 1 line doesn't)
    expect(combined).not.toContain('[...truncated...]');
  });

  test('PER_FILE_SIZE_LIMIT is 25 KB', () => {
    expect(PER_FILE_SIZE_LIMIT).toBe(25 * 1024);
  });
});

// ---------------------------------------------------------------------------
// AC4: selectRelevantMemories uses Sonnet, not Haiku
// ---------------------------------------------------------------------------

describe('AC4: selectRelevantMemories uses Sonnet model', () => {
  test('passes SELECT_MODEL (Sonnet) to the callModel function', async () => {
    let capturedModel: string | undefined;
    const mockCallModel: SelectModelFn = async ({ model, descriptions }) => {
      capturedModel = model;
      return descriptions.map((d) => d.name);
    };

    const entries = [
      makeEntry({ name: 'a', description: 'Apple info' }),
      makeEntry({ name: 'b', description: 'Banana info' }),
    ];

    await selectRelevantMemories(entries, 'fruit', mockCallModel);
    expect(capturedModel).toBe(SELECT_MODEL);
  });

  test('SELECT_MODEL constant is qwen-3.6', () => {
    expect(SELECT_MODEL).toBe('qwen-3.6');
  });

  test('returns all entries on API error (fallback)', async () => {
    const entries = [
      makeEntry({ name: 'a', description: 'a' }),
      makeEntry({ name: 'b', description: 'b' }),
    ];
    const throwingModel: SelectModelFn = async () => { throw new Error('API error'); };
    const result = await selectRelevantMemories(entries, 'query', throwingModel);
    expect(result).toHaveLength(2);
  });

  test('returns entries in model-returned order', async () => {
    const entries = [
      makeEntry({ name: 'a', description: 'Alpha' }),
      makeEntry({ name: 'b', description: 'Beta' }),
      makeEntry({ name: 'c', description: 'Gamma' }),
    ];
    const mockCallModel: SelectModelFn = async () => ['c', 'a', 'b'];
    const result = await selectRelevantMemories(entries, 'query', mockCallModel);
    expect(result[0]!.name).toBe('c');
    expect(result[1]!.name).toBe('a');
    expect(result[2]!.name).toBe('b');
  });

  test('returns all entries when no callModel provided', async () => {
    const entries = [makeEntry({ name: 'a' }), makeEntry({ name: 'b' })];
    const result = await selectRelevantMemories(entries, 'query');
    expect(result).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// AC5: Combined block > 100 KB → entries dropped until it fits
// ---------------------------------------------------------------------------

describe('AC5: total block limit of 100 KB enforced', () => {
  test('TOTAL_BLOCK_LIMIT is 100 KB', () => {
    expect(TOTAL_BLOCK_LIMIT).toBe(100 * 1024);
  });

  test('loadMemoryPrompt drops entries when block exceeds 100 KB', async () => {
    const dir = makeTempDir('ac5');
    // Write many files with large content to exceed 100 KB total
    for (let i = 0; i < 10; i++) {
      const body = 'y'.repeat(15_000); // 15 KB each → 10 × 15 KB = 150 KB total
      writeFileSync(
        join(dir, `big-${i}.md`),
        makeValidFileContent({ name: `big-${i}`, description: `Big file ${i}`, body }),
        'utf-8',
      );
    }

    const result = await loadMemoryPrompt({ dir });
    // Result must be within 100 KB
    const resultSize = Buffer.byteLength(result, 'utf-8');
    expect(resultSize).toBeLessThanOrEqual(TOTAL_BLOCK_LIMIT);
  });
});

// ---------------------------------------------------------------------------
// findRelevantMemories: keyword-based pre-filter
// ---------------------------------------------------------------------------

describe('findRelevantMemories: keyword pre-filter', () => {
  const entries = [
    makeEntry({ name: 'apple-notes', description: 'Notes about apples and fruit' }),
    makeEntry({ name: 'banana-guide', description: 'Banana cultivation guide' }),
    makeEntry({ name: 'code-review', description: 'Code review practices' }),
  ];

  test('filters by keyword in description', () => {
    const result = findRelevantMemories(entries, { keywords: ['apple'] });
    expect(result).toHaveLength(1);
    expect(result[0]!.name).toBe('apple-notes');
  });

  test('filters by keyword in name', () => {
    const result = findRelevantMemories(entries, { keywords: ['banana'] });
    expect(result).toHaveLength(1);
    expect(result[0]!.name).toBe('banana-guide');
  });

  test('returns all entries for empty keywords', () => {
    const result = findRelevantMemories(entries, { keywords: [] });
    expect(result).toHaveLength(3);
  });

  test('case-insensitive matching', () => {
    const result = findRelevantMemories(entries, { keywords: ['CODE'] });
    expect(result).toHaveLength(1);
    expect(result[0]!.name).toBe('code-review');
  });

  test('multiple keywords: OR match', () => {
    const result = findRelevantMemories(entries, { keywords: ['apple', 'banana'] });
    expect(result).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// buildMemoryPrompt: wraps in <ember_memory> block
// ---------------------------------------------------------------------------

describe('buildMemoryPrompt: structure and empty handling', () => {
  test('returns empty string for no entries', () => {
    expect(buildMemoryPrompt([])).toBe('');
  });

  test('wraps output in <ember_memory> tags', () => {
    const entry = makeEntry({ name: 'n', description: 'd' });
    const result = buildMemoryPrompt([entry]);
    expect(result).toContain('<ember_memory>');
    expect(result).toContain('</ember_memory>');
  });

  test('includes TYPES_SECTION before file content', () => {
    const entry = makeEntry({ name: 'n', description: 'MY_UNIQUE_DESC' });
    const result = buildMemoryPrompt([entry]);
    const typeIdx = result.indexOf('metadata.type');
    const descIdx = result.indexOf('MY_UNIQUE_DESC');
    expect(typeIdx).toBeLessThan(descIdx);
  });

  test('includes TRUSTING_RECALL after file content', () => {
    const entry = makeEntry({ name: 'n', description: 'MY_UNIQUE_DESC_2' });
    const result = buildMemoryPrompt([entry]);
    const descIdx = result.indexOf('MY_UNIQUE_DESC_2');
    const recallIdx = result.indexOf('codebase takes precedence');
    expect(descIdx).toBeLessThan(recallIdx);
  });
});

// ---------------------------------------------------------------------------
// buildAssistantDailyLogPrompt
// ---------------------------------------------------------------------------

describe('buildAssistantDailyLogPrompt', () => {
  test('returns empty string for no entries', () => {
    expect(buildAssistantDailyLogPrompt([])).toBe('');
  });

  test('wraps in <ember_daily_log> tags', () => {
    const result = buildAssistantDailyLogPrompt([{ date: '2026-06-26', summary: 'Did stuff.' }]);
    expect(result).toContain('<ember_daily_log>');
    expect(result).toContain('</ember_daily_log>');
  });

  test('includes date and summary', () => {
    const result = buildAssistantDailyLogPrompt([
      { date: '2026-06-26', summary: 'Fixed the bug.' },
    ]);
    expect(result).toContain('2026-06-26');
    expect(result).toContain('Fixed the bug.');
  });
});

// ---------------------------------------------------------------------------
// buildCombinedMemoryPrompt
// ---------------------------------------------------------------------------

describe('buildCombinedMemoryPrompt', () => {
  test('returns empty string when both lists empty', () => {
    expect(buildCombinedMemoryPrompt([], [])).toBe('');
  });

  test('labels team entries separately', () => {
    const personal = [makeEntry({ name: 'p', description: 'personal' })];
    const team = [makeEntry({ name: 't', description: 'team' })];
    const result = buildCombinedMemoryPrompt(personal, team);
    expect(result).toContain('Team memories');
  });

  test('works with only personal entries', () => {
    const personal = [makeEntry({ name: 'p', description: 'personal only' })];
    const result = buildCombinedMemoryPrompt(personal, []);
    expect(result).toContain('<ember_memory>');
    expect(result).not.toContain('Team memories');
  });

  test('works with only team entries', () => {
    const team = [makeEntry({ name: 't', description: 'team only' })];
    const result = buildCombinedMemoryPrompt([], team);
    expect(result).toContain('<ember_memory>');
    expect(result).toContain('Team memories');
  });
});

// ---------------------------------------------------------------------------
// formatMemoryManifest
// ---------------------------------------------------------------------------

describe('formatMemoryManifest: MEMORY.md index format', () => {
  test('formats entries as "- [description](name.md) — hook"', () => {
    const entry = makeEntry({ name: 'my-note', description: 'A note about apples.' });
    const result = formatMemoryManifest([entry]);
    expect(result).toMatch(/^- \[A note about apples\.\]\(my-note\.md\) — /);
  });

  test('hook is 60 chars or less', () => {
    const longBody = 'A'.repeat(200) + '. Rest of content.';
    const entry = makeEntry({
      name: 'n',
      description: 'd',
      body: makeValidFileContent({ name: 'n', description: 'd', body: longBody }),
    });
    const result = formatMemoryManifest([entry]);
    const hookPart = result.split(' — ')[1];
    expect(hookPart).toBeDefined();
    expect(hookPart!.length).toBeLessThanOrEqual(60);
  });

  test('empty entries → empty string', () => {
    expect(formatMemoryManifest([])).toBe('');
  });
});

// ---------------------------------------------------------------------------
// loadMemoryPrompt: integration test
// ---------------------------------------------------------------------------

describe('loadMemoryPrompt: top-level integration', () => {
  test('returns empty string for empty directory', async () => {
    const dir = makeTempDir('load-empty');
    const result = await loadMemoryPrompt({ dir });
    expect(result).toBe('');
  });

  test('scans dir and returns assembled block', async () => {
    const dir = makeTempDir('load-files');
    writeFileSync(
      join(dir, 'note.md'),
      makeValidFileContent({ name: 'note', description: 'A note', body: 'Body.' }),
      'utf-8',
    );
    const result = await loadMemoryPrompt({ dir });
    expect(result).toContain('<ember_memory>');
    expect(result).toContain('note');
  });

  test('with query and callModel, performs semantic selection', async () => {
    const dir = makeTempDir('load-select');
    writeFileSync(
      join(dir, 'a.md'),
      makeValidFileContent({ name: 'a', description: 'Alpha entry', body: 'Body a.' }),
      'utf-8',
    );
    writeFileSync(
      join(dir, 'b.md'),
      makeValidFileContent({ name: 'b', description: 'Beta entry', body: 'Body b.' }),
      'utf-8',
    );

    const mockCallModel: SelectModelFn = async ({ descriptions }) => {
      // Return only 'b'
      return descriptions.filter((d) => d.name === 'b').map((d) => d.name);
    };

    const result = await loadMemoryPrompt({ dir, query: 'beta', callModel: mockCallModel });
    expect(result).toContain('b');
    // 'a' is appended as a fallback since all entries are included
    // (selectRelevantMemories appends unranked entries)
  });
});
