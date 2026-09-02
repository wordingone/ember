// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// copy.ts — /copy slash command.

import type { RegistryCommand, CommandContext, CommandResult } from './types/command-types.ts';
import type { Message } from './types/message-types.ts';
import * as nodePath from 'node:path';

// ---------------------------------------------------------------------------
// Code block extraction
// ---------------------------------------------------------------------------

export interface CodeBlock {
  language: string;
  code: string;
}

export function extractCodeBlocks(markdown: string): CodeBlock[] {
  const blocks: CodeBlock[] = [];
  const re = /```([^\n]*)\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(markdown)) !== null) {
    blocks.push({ language: match[1]?.trim() ?? '', code: match[2] ?? '' });
  }
  return blocks;
}

// ---------------------------------------------------------------------------
// Extension helper
// ---------------------------------------------------------------------------

export function codeBlockExtension(language: string): string {
  const normalized = language.toLowerCase();
  if (!normalized || normalized === 'plaintext' || normalized === 'text') return '.txt';
  // Strip non-alphanumeric chars, then prepend dot
  const clean = normalized.replace(/[^a-z0-9]/g, '');
  return clean ? `.${clean}` : '.txt';
}

// ---------------------------------------------------------------------------
// Recent response collector
// ---------------------------------------------------------------------------

export interface RecentResponse {
  text: string;
  message: Message;
}

function getTextContent(msg: Message): string {
  if (!Array.isArray(msg.content)) return '';
  return (msg.content as Array<{ type: string; text?: string }>)
    .filter((b) => b.type === 'text')
    .map((b) => b.text ?? '')
    .join('');
}

export function collectRecentResponses(messages: Message[]): RecentResponse[] {
  const results: RecentResponse[] = [];
  // Iterate newest-first
  for (let i = messages.length - 1; i >= 0; i--) {
    if (results.length >= 20) break;
    const msg = messages[i]!;
    if (msg.role !== 'assistant') continue;
    if (msg.isApiErrorMessage) continue;
    const text = getTextContent(msg);
    if (!text.trim()) continue; // skip tool-only messages
    results.push({ text, message: msg });
  }
  return results;
}

// ---------------------------------------------------------------------------
// Temp path builder
// ---------------------------------------------------------------------------

export function buildTempPath(tmpDir: string, fullResponse: boolean, language?: string): string {
  const subdir = nodePath.join(tmpDir, 'ember');
  if (fullResponse) return nodePath.join(subdir, 'response.md').replace(/\\/g, '/');
  const ext = codeBlockExtension(language ?? '');
  return nodePath.join(subdir, `copy${ext}`).replace(/\\/g, '/');
}

// ---------------------------------------------------------------------------
// Deps
// ---------------------------------------------------------------------------

type PickerSelectResult =
  | { type: 'none' }
  | { type: 'always-full' }
  | { type: 'full' }
  | { type: 'block'; blockIndex: number };

interface CopyCommandDeps {
  getMessages: () => Message[];
  getCopyFullResponse: () => boolean;
  setCopyFullResponse: (v: boolean) => Promise<void>;
  writeToClipboard: (text: string) => void;
  writeTempFile: (path: string, content: string) => Promise<void>;
  getTmpDir: () => string;
  openCopyPicker: (opts: { responses: RecentResponse[]; onSelect: (r: PickerSelectResult) => Promise<void> | void }) => Promise<PickerSelectResult | void>;
}

const noopDeps: CopyCommandDeps = {
  getMessages: () => [],
  getCopyFullResponse: () => false,
  setCopyFullResponse: async () => {},
  writeToClipboard: () => {},
  writeTempFile: async () => {},
  getTmpDir: () => '/tmp',
  openCopyPicker: async () => {},
};

let deps: CopyCommandDeps = { ...noopDeps };

export function setCopyCommandDeps(overrides: Partial<CopyCommandDeps>): void {
  deps = { ...deps, ...overrides };
}

export function resetCopyCommandDeps(): void {
  deps = { ...noopDeps };
}

// ---------------------------------------------------------------------------
// performCopy — uses module-level deps for IO
// ---------------------------------------------------------------------------

export interface PerformCopyOpts {
  writeShortcut?: boolean;
  age?: number;
  blockCount?: number;
}

export async function performCopy(
  content: string,
  fullResponse: boolean,
  language: string | undefined,
  opts?: PerformCopyOpts,
): Promise<void> {
  const tmpPath = buildTempPath(deps.getTmpDir(), fullResponse, language);
  await deps.writeTempFile(tmpPath, content);
  if (!opts?.writeShortcut) {
    deps.writeToClipboard(content);
  }
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const copyCommand: RegistryCommand = {
  name: 'copy',
  description: 'Copy the most recent response or a code block to clipboard',

  isEnabled(): boolean {
    return true;
  },

  async execute(_args: string, _ctx: CommandContext): Promise<CommandResult | void> {
    const messages = deps.getMessages();
    const responses = collectRecentResponses(messages);

    if (responses.length === 0) {
      return { type: 'message', message: 'No responses available to copy.' };
    }

    // AC2: skip picker when copyFullResponse preference set
    if (deps.getCopyFullResponse()) {
      await performCopy(responses[0]!.text, true, undefined);
      return;
    }

    // AC1: no picker configured → copy most recent headlessly
    if (!deps.openCopyPicker) {
      await performCopy(responses[0]!.text, true, undefined);
      return;
    }

    // Interactive picker flow
    const most = responses[0]!;
    let selectionHandled = false;

    await deps.openCopyPicker({
      responses,
      onSelect: async (sel) => {
        selectionHandled = true;
        if (sel.type === 'none') return;
        if (sel.type === 'always-full') {
          await deps.setCopyFullResponse(true);
          await performCopy(most.text, true, undefined);
        } else if (sel.type === 'full') {
          await performCopy(most.text, true, undefined);
        } else if (sel.type === 'block') {
          const blocks = extractCodeBlocks(most.text);
          const block = blocks[sel.blockIndex];
          if (block) {
            await performCopy(block.code, false, block.language);
          }
        }
      },
    });

    // Fallback: picker did not invoke onSelect → copy most recent
    if (!selectionHandled) {
      await performCopy(most.text, true, undefined);
    }
  },
};
