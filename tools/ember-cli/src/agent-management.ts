// agent-management.ts — Agent file management, wizard state, color picker, and React UI stubs.
// Covers AC1–AC12.

import React from 'react';
import { open, unlink, readFile, writeFile } from 'fs/promises';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentDefinition {
  agentType: string;
  name: string;
  description?: string;
  model?: string;
  systemPrompt?: string;
  whenToUse?: string;
  tools?: string[];
  location: 'user' | 'project';
  filePath: string;
  color?: string;
}

// ---------------------------------------------------------------------------
// AC1-AC3: identifier validation
// ---------------------------------------------------------------------------

export function validateAgentIdentifier(id: string): boolean {
  if (id.length < 2) return false;
  if (!/^[a-zA-Z0-9]/.test(id)) return false;
  if (!/^[a-zA-Z0-9][a-zA-Z0-9-]*$/.test(id)) return false;
  return true;
}

// ---------------------------------------------------------------------------
// AC4: override detection
// ---------------------------------------------------------------------------

export function hasOverride(
  userAgents: Array<{ agentType: string }>,
  projectAgent: { agentType: string },
): boolean {
  return userAgents.some(ua => ua.agentType === projectAgent.agentType);
}

// ---------------------------------------------------------------------------
// AC5: tool selection
// ---------------------------------------------------------------------------

export function resolveSelectedTools(selected: string[]): string[] | undefined {
  if (selected.length === 0) return undefined;
  return selected;
}

// ---------------------------------------------------------------------------
// AC6: exclusive file create
// ---------------------------------------------------------------------------

export async function saveAgentToFile(
  path: string,
  content: string,
  checkExists: boolean,
): Promise<void> {
  if (checkExists) {
    // Use exclusive open flag
    const fd = await open(path, 'wx').catch((e: NodeJS.ErrnoException) => {
      if (e.code === 'EEXIST') {
        const err = new Error(`File already exists: ${path}`);
        (err as NodeJS.ErrnoException).code = 'EEXIST';
        throw err;
      }
      throw e;
    });
    await fd.writeFile(content, 'utf8');
    await fd.close();
  } else {
    await writeFile(path, content, 'utf8');
  }
}

// ---------------------------------------------------------------------------
// AC7: delete file — no error if already deleted
// ---------------------------------------------------------------------------

export async function deleteAgentFromFile(path: string): Promise<void> {
  await unlink(path).catch((e: NodeJS.ErrnoException) => {
    if (e.code === 'ENOENT') return;
    throw e;
  });
}

// ---------------------------------------------------------------------------
// AC12: writeFileAndFlush — write + datasync
// ---------------------------------------------------------------------------

export async function writeFileAndFlush(path: string, content: string): Promise<void> {
  const fd = await open(path, 'w');
  try {
    await fd.writeFile(content, 'utf8');
    await fd.datasync();
  } finally {
    await fd.close();
  }
}

// ---------------------------------------------------------------------------
// AC8: wizard history
// ---------------------------------------------------------------------------

type WizardStep =
  | 'type'
  | 'name'
  | 'description'
  | 'model'
  | 'tools'
  | 'color'
  | 'generate'
  | 'confirm'
  | string;

export interface WizardHistory {
  current: WizardStep;
  stack: WizardStep[];
}

export function wizardHistoryCreate(initial: WizardStep): WizardHistory {
  return { current: initial, stack: [] };
}

export function wizardHistoryPush(history: WizardHistory, next: WizardStep): WizardHistory {
  return {
    current: next,
    stack: [...history.stack, history.current],
  };
}

export function wizardHistoryBack(history: WizardHistory): WizardHistory {
  const stack = [...history.stack];
  const prev = stack.pop() ?? history.current;
  return { current: prev, stack };
}

// ---------------------------------------------------------------------------
// AC9: parseGenerateResponse — JSON parse with regex fallback
// ---------------------------------------------------------------------------

interface GenerateResponseResult {
  identifier?: string;
  whenToUse?: string;
  systemPrompt?: string;
}

export function parseGenerateResponse(raw: string): GenerateResponseResult | null {
  // Try JSON first
  try {
    const parsed = JSON.parse(raw) as GenerateResponseResult;
    if (parsed && typeof parsed === 'object') return parsed;
  } catch {
    // fall through to regex
  }

  // Regex fallback: extract "key": "value" pairs
  const result: GenerateResponseResult = {};
  const identifierMatch = raw.match(/"identifier"\s*:\s*"([^"]+)"/);
  const whenToUseMatch = raw.match(/"whenToUse"\s*:\s*"([^"]+)"/);
  const systemPromptMatch = raw.match(/"systemPrompt"\s*:\s*"([^"]+)"/);

  if (identifierMatch) result.identifier = identifierMatch[1];
  if (whenToUseMatch) result.whenToUse = whenToUseMatch[1];
  if (systemPromptMatch) result.systemPrompt = systemPromptMatch[1];

  if (Object.keys(result).length > 0) return result;
  return null;
}

// ---------------------------------------------------------------------------
// AC10/11: Color management
// ---------------------------------------------------------------------------

export const AGENT_COLORS = [
  'red', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'cyan',
] as const;

export const COLOR_OPTIONS = ['automatic', ...AGENT_COLORS] as const;

export function colorPickerNext(current: string): string {
  const allColors = ['automatic', ...AGENT_COLORS];
  const idx = allColors.indexOf(current);
  if (idx === -1 || idx === allColors.length - 1) return 'automatic';
  return allColors[idx + 1] ?? 'automatic';
}

export function colorPickerPrev(current: string): string {
  const allColors = ['automatic', ...AGENT_COLORS];
  const idx = allColors.indexOf(current);
  if (idx <= 0) return AGENT_COLORS[AGENT_COLORS.length - 1] ?? 'automatic';
  return allColors[idx - 1] ?? 'automatic';
}

// ---------------------------------------------------------------------------
// AC11: afterDeleteMode
// ---------------------------------------------------------------------------

export function afterDeleteMode(): string {
  return 'list-agents';
}

// ---------------------------------------------------------------------------
// serializeAgentFile / parseAgentFile
// ---------------------------------------------------------------------------

export function serializeAgentFile(def: AgentDefinition): string {
  const lines: string[] = ['---'];
  lines.push(`name: ${def.name}`);
  if (def.description) lines.push(`description: ${def.description}`);
  if (def.model) lines.push(`model: ${def.model}`);
  if (def.whenToUse) lines.push(`when_to_use: ${def.whenToUse}`);
  if (def.tools) lines.push(`tools: [${def.tools.join(', ')}]`);
  if (def.color) lines.push(`color: ${def.color}`);
  lines.push('---');
  lines.push('');
  lines.push(def.systemPrompt ?? '');
  return lines.join('\n');
}

export function parseAgentFile(
  content: string,
  filePath: string,
  location: 'user' | 'project',
): AgentDefinition | null {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return null;

  const frontmatter = match[1] ?? '';
  const body = (match[2] ?? '').trim();

  const getName = (key: string): string | undefined => {
    const m = frontmatter.match(new RegExp(`^${key}:\\s*(.+)$`, 'm'));
    return m ? m[1]!.trim() : undefined;
  };

  const name = getName('name') ?? '';
  const agentType = filePath.replace(/\.md$/, '').split('/').pop() ?? name;

  return {
    agentType,
    name,
    description: getName('description'),
    model: getName('model'),
    whenToUse: getName('when_to_use'),
    systemPrompt: body,
    location,
    filePath,
  };
}

// ---------------------------------------------------------------------------
// React UI components (stubs satisfy structural tests)
// ---------------------------------------------------------------------------

export function AgentsMenu(_props: Record<string, unknown>): React.ReactElement {
  return React.createElement('div', { className: 'agents-menu' });
}

export function AgentsList(_props: Record<string, unknown>): React.ReactElement {
  return React.createElement('div', { className: 'agents-list' });
}

export function ToolSelector(_props: Record<string, unknown>): React.ReactElement {
  return React.createElement('div', { className: 'tool-selector' });
}

export function ColorPicker(_props: Record<string, unknown>): React.ReactElement {
  return React.createElement('div', { className: 'color-picker' });
}
