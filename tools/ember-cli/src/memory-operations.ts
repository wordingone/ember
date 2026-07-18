// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// memory-operations.ts — memory file scanning, prompt assembly, and relevance selection.

import { readdir, readFile, stat } from 'fs/promises';
import { join } from 'path';
import type { SelectedModelContract } from './entrypoints/model-seat';

// ---- Constants ----

/** Maximum number of lines to include from a single memory file. */
export const PER_FILE_LINE_LIMIT = 200;

/** Maximum byte size of content from a single memory file before truncation. */
export const PER_FILE_SIZE_LIMIT = 25 * 1024; // 25 KB

/** Maximum total byte size of the assembled memory block. */
export const TOTAL_BLOCK_LIMIT = 100 * 1024; // 100 KB

// ---- Types ----

export interface MemoryFileEntry {
  name: string;
  description: string;
  type: string;
  filePath: string;
  body: string;
  modifiedAt: Date;
}

export type SelectModelFn = (opts: {
  model: string;
  descriptions: Array<{ name: string; description: string }>;
}) => Promise<string[]>;

// ---- Frontmatter parsing ----

interface Frontmatter {
  name?: string;
  description?: string;
  type?: string;
}

/**
 * Extracts YAML frontmatter from a markdown file.
 * Returns null when the file does not start with a valid "---" block.
 *
 * Supported frontmatter keys: name, description, metadata.type
 */
function parseFrontmatter(content: string): Frontmatter | null {
  if (!content.startsWith('---')) return null;
  const end = content.indexOf('\n---', 3);
  if (end === -1) return null;

  const block = content.slice(3, end);
  const result: Frontmatter = {};

  for (const line of block.split('\n')) {
    const trimmed = line.trim();
    const colonIdx = trimmed.indexOf(':');
    if (colonIdx === -1) continue;
    const key = trimmed.slice(0, colonIdx).trim();
    const value = trimmed.slice(colonIdx + 1).trim();
    if (key === 'name') result.name = value;
    if (key === 'description') result.description = value;
    // metadata.type is nested under a "metadata:" block
    if (key === 'type') result.type = value;
  }

  return result.name !== undefined && result.description !== undefined ? result : null;
}

// ---- File scanner ----

/**
 * Scans `dir` (non-recursively) for .md files with valid frontmatter.
 * Returns entries sorted newest-first by modification time.
 */
export async function scanMemoryFiles(dir: string): Promise<MemoryFileEntry[]> {
  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch {
    return [];
  }

  const results: MemoryFileEntry[] = [];

  for (const filename of entries) {
    if (!filename.endsWith('.md')) continue;
    const filePath = join(dir, filename);

    let fileStat: { mtimeMs: number; isDirectory(): boolean };
    try {
      fileStat = await stat(filePath);
    } catch {
      continue;
    }
    if (fileStat.isDirectory()) continue;

    let body: string;
    try {
      body = await readFile(filePath, 'utf-8');
    } catch {
      continue;
    }

    const fm = parseFrontmatter(body);
    if (!fm || !fm.name || !fm.description) continue;

    results.push({
      name: fm.name,
      description: fm.description,
      type: fm.type ?? 'user',
      filePath,
      body,
      modifiedAt: new Date(fileStat.mtimeMs),
    });
  }

  // Sort newest-first
  results.sort((a, b) => b.modifiedAt.getTime() - a.modifiedAt.getTime());
  return results;
}

// ---- Per-file truncation ----

const TRUNCATION_NOTICE = '[...truncated...]';

/** Truncates `text` to `maxLines` lines and `maxBytes` bytes, appending a notice when cut.
 *
 * Line counting applies to body content only — frontmatter lines (the opening `---` block)
 * are excluded from the line budget so the limit reflects meaningful content lines.
 */
function truncateBody(text: string, maxLines: number, maxBytes: number): string {
  // Separate frontmatter from body content so the line limit applies to body only
  let frontmatter = '';
  let bodyContent = text;

  if (text.startsWith('---')) {
    const fmEnd = text.indexOf('\n---', 3);
    if (fmEnd !== -1) {
      // Advance past '\n---'
      let closingEnd = fmEnd + 4;
      // Consume the newline that terminates the closing '---' line
      if (closingEnd < text.length && text[closingEnd] === '\n') closingEnd++;
      // Consume one conventional blank separator line (---\n\n<body>)
      if (closingEnd < text.length && text[closingEnd] === '\n') closingEnd++;
      frontmatter = text.slice(0, closingEnd);
      bodyContent = text.slice(closingEnd);
    }
  }

  let truncated = false;

  // Line truncation — body content only
  const bodyLines = bodyContent.split('\n');
  if (bodyLines.length > maxLines) {
    bodyContent = bodyLines.slice(0, maxLines).join('\n');
    truncated = true;
  }

  let result = frontmatter + bodyContent;

  // Size truncation — whole assembled result
  const bytes = Buffer.byteLength(result, 'utf-8');
  if (bytes > maxBytes) {
    const ratio = maxBytes / bytes;
    const safeLen = Math.floor(result.length * ratio);
    result = result.slice(0, safeLen);
    truncated = true;
  }

  if (truncated) {
    result = result + '\n' + TRUNCATION_NOTICE;
  }

  return result;
}

// ---- Line/size-limited body assembly ----

/**
 * Returns an array of strings — one per entry — with line and size truncation applied.
 * Each entry is rendered with a header containing its structured name and description
 * fields followed by the (possibly truncated) body content.
 */
export function buildMemoryLines(entries: MemoryFileEntry[]): string[] {
  return entries.map((e) => {
    const header = `${e.name}: ${e.description}`;
    const body = truncateBody(e.body, PER_FILE_LINE_LIMIT, PER_FILE_SIZE_LIMIT);
    return `${header}\n${body}`;
  });
}

// ---- Prompt sections ----

const TYPES_SECTION = `Memory type guide (metadata.type values):
- user: personal preferences and working style
- project: project-specific context and conventions
- feedback: lessons learned and corrections
- codebase: architectural context and code patterns`;

const TRUSTING_RECALL =
  'When memory contradicts what you observe in the codebase, codebase takes precedence.';

/**
 * Assembles a `<ember_memory>` prompt block from the given entries.
 * Returns an empty string when `entries` is empty.
 */
export function buildMemoryPrompt(entries: MemoryFileEntry[]): string {
  if (entries.length === 0) return '';

  const lines = buildMemoryLines(entries);
  const content = lines.join('\n\n---\n\n');

  return [
    '<ember_memory>',
    TYPES_SECTION,
    '',
    content,
    '',
    TRUSTING_RECALL,
    '</ember_memory>',
  ].join('\n');
}

// ---- Daily log prompt ----

/**
 * Assembles a `<ember_daily_log>` prompt block for daily assistant log entries.
 * Returns an empty string when `entries` is empty.
 */
export function buildAssistantDailyLogPrompt(
  entries: Array<{ date: string; summary: string }>,
): string {
  if (entries.length === 0) return '';

  const lines = entries
    .map((e) => `[${e.date}] ${e.summary}`)
    .join('\n');

  return ['<ember_daily_log>', lines, '</ember_daily_log>'].join('\n');
}

// ---- Combined memory prompt ----

/**
 * Assembles personal and team memory into a single `<ember_memory>` block.
 * Returns an empty string when both lists are empty.
 * Team entries are prefixed with a "Team memories" section label.
 */
export function buildCombinedMemoryPrompt(
  personal: MemoryFileEntry[],
  team: MemoryFileEntry[],
): string {
  if (personal.length === 0 && team.length === 0) return '';

  const sections: string[] = [TYPES_SECTION, ''];

  if (personal.length > 0) {
    const personalLines = buildMemoryLines(personal).join('\n\n---\n\n');
    sections.push(personalLines);
  }

  if (team.length > 0) {
    sections.push('Team memories:');
    sections.push('');
    const teamLines = buildMemoryLines(team).join('\n\n---\n\n');
    sections.push(teamLines);
  }

  sections.push('');
  sections.push(TRUSTING_RECALL);

  return ['<ember_memory>', ...sections, '</ember_memory>'].join('\n');
}

// ---- Memory manifest ----

const HOOK_MAX_LENGTH = 60;

/** Extracts a short hook from the body (first non-empty line after frontmatter). */
function extractHook(body: string): string {
  // Skip the frontmatter block
  let startIdx = 0;
  if (body.startsWith('---')) {
    const end = body.indexOf('\n---', 3);
    startIdx = end !== -1 ? end + 4 : 0;
  }
  const rest = body.slice(startIdx).trim();
  const firstLine = rest.split('\n')[0]?.trim() ?? '';
  return firstLine.slice(0, HOOK_MAX_LENGTH);
}

/**
 * Formats entries as a MEMORY.md index manifest.
 * Format per line: `- [description](name.md) — hook`
 */
export function formatMemoryManifest(entries: MemoryFileEntry[]): string {
  if (entries.length === 0) return '';
  return entries
    .map((e) => `- [${e.description}](${e.name}.md) — ${extractHook(e.body)}`)
    .join('\n');
}

// ---- Keyword-based pre-filter ----

/**
 * Filters entries to those whose name or description contains any of the provided
 * keywords (case-insensitive OR match). Returns all entries when keywords is empty.
 */
export function findRelevantMemories(
  entries: MemoryFileEntry[],
  opts: { keywords: string[] },
): MemoryFileEntry[] {
  if (opts.keywords.length === 0) return entries;

  const lower = opts.keywords.map((k) => k.toLowerCase());
  return entries.filter((e) => {
    const target = (e.name + ' ' + e.description).toLowerCase();
    return lower.some((kw) => target.includes(kw));
  });
}

// ---- Semantic selection ----

/**
 * Uses the provided model function to select the most relevant entries for `query`.
 *
 * - Consumes the currently selected model contract (see
 *   `entrypoints/model-seat.ts::selectedModelContract`) — NOT a bare
 *   modelName string, so a caller can never inject an arbitrary model
 *   identity without it being seat-authorized.
 * - Returns entries in model-returned order (with unselected entries appended)
 * - Falls back to all entries on model error
 * - Returns all entries when `callModel` or `modelContract` is not provided
 *   (e.g. OFFLINE or a refused seat, which never produce a contract at all)
 */
export async function selectRelevantMemories(
  entries: MemoryFileEntry[],
  query: string,
  callModel?: SelectModelFn,
  modelContract?: SelectedModelContract,
): Promise<MemoryFileEntry[]> {
  if (!callModel || !modelContract || entries.length === 0) return entries;

  try {
    const descriptions = entries.map((e) => ({ name: e.name, description: e.description }));
    const selected = await callModel({ model: modelContract.modelName, descriptions });

    // Build a map for fast lookup
    const byName = new Map(entries.map((e) => [e.name, e]));

    // Return in model order, then append any unselected entries
    const ordered: MemoryFileEntry[] = [];
    const seen = new Set<string>();

    for (const name of selected) {
      const entry = byName.get(name);
      if (entry && !seen.has(name)) {
        ordered.push(entry);
        seen.add(name);
      }
    }

    for (const e of entries) {
      if (!seen.has(e.name)) ordered.push(e);
    }

    return ordered;
  } catch {
    return entries;
  }
}

// ---- Top-level loader ----

export interface LoadMemoryPromptOpts {
  dir: string;
  query?: string;
  callModel?: SelectModelFn;
  /** Fix #51 P1 repair (3): the seat-authorized identity + capability contract
   *  (see `entrypoints/model-seat.ts::selectedModelContract`), threaded through
   *  to `selectRelevantMemories` so semantic selection is reachable only via
   *  the same seat-authorized identity every other consumer uses -- never a
   *  bare modelName string. Omitted/undefined never executes selection
   *  (falls back to returning all entries), matching `selectRelevantMemories`. */
  modelContract?: SelectedModelContract;
}

/**
 * Loads, filters, and assembles all memory files from `dir` into a prompt block.
 *
 * - Scans for valid .md files
 * - Applies semantic selection when query + callModel are provided
 * - Enforces TOTAL_BLOCK_LIMIT by dropping trailing entries until the block fits
 * - Returns an empty string when the directory is empty or no files are valid
 */
export async function loadMemoryPrompt(opts: LoadMemoryPromptOpts): Promise<string> {
  const entries = await scanMemoryFiles(opts.dir);
  if (entries.length === 0) return '';

  const ranked =
    opts.query && opts.callModel
      ? await selectRelevantMemories(entries, opts.query, opts.callModel, opts.modelContract)
      : entries;

  // Drop trailing entries until the assembled block fits within TOTAL_BLOCK_LIMIT
  let kept = ranked;
  while (kept.length > 0) {
    const prompt = buildMemoryPrompt(kept);
    if (Buffer.byteLength(prompt, 'utf-8') <= TOTAL_BLOCK_LIMIT) return prompt;
    kept = kept.slice(0, kept.length - 1);
  }

  return '';
}
