// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// local-agent-task.ts — lifecycle and token-usage tracking for local subagent tasks.
// W2-B: local-only mode. LARGE_MODELS is empty — all model names pass through unchanged.

import type { KillableTask } from './task-infrastructure.ts';
import type { AgentId } from '../types/id-types.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LocalAgentTaskStatus = 'pending' | 'running' | 'complete' | 'stopped' | 'error';

export interface TokenUsage {
  input: number;
  output: number;
  cacheRead: number;
}

export interface LocalAgentTask extends KillableTask {
  readonly id: string;
  readonly type: 'local_agent';
  readonly agentId: AgentId;
  readonly parentAgentId: AgentId;
  readonly prompt: string;
  readonly model: string;
  status: LocalAgentTaskStatus;
  readonly createdAt: string;
  readonly isSubagent: true;
  readonly isConductor: false;
  readonly signal: AbortSignal;
  tokenUsage: TokenUsage | undefined;
  result: string | undefined;
  errorOutput: string | undefined;
  durationMs: number | undefined;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SUBAGENT_MODEL = 'local';

// Empty in local-only mode — all model names pass through unchanged.
const LARGE_MODELS: ReadonlySet<string> = new Set();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return 'a' + hex;
}

function isTerminal(status: LocalAgentTaskStatus): boolean {
  return status === 'complete' || status === 'error' || status === 'stopped';
}

// ---------------------------------------------------------------------------
// Model normalization
// ---------------------------------------------------------------------------

/**
 * Normalizes the agent model name.
 * In local-only mode LARGE_MODELS is empty, so all names pass through unchanged.
 * undefined → DEFAULT_SUBAGENT_MODEL ('local').
 */
export function normalizeAgentModel(
  model: string | undefined,
  _allowLargeModels: boolean,
): string {
  if (model === undefined) return DEFAULT_SUBAGENT_MODEL;
  // LARGE_MODELS is empty — no substitution regardless of allowLargeModels
  void LARGE_MODELS;
  return model;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export interface CreateLocalAgentTaskOptions {
  agentId: AgentId;
  parentAgentId: AgentId;
  prompt: string;
  model?: string;
  allowLargeModels?: boolean;
}

export function createLocalAgentTask(
  opts: CreateLocalAgentTaskOptions,
): LocalAgentTask {
  const controller = new AbortController();
  let _status: LocalAgentTaskStatus = 'pending';

  const task: LocalAgentTask = {
    id: generateId(),
    type: 'local_agent',
    agentId: opts.agentId,
    parentAgentId: opts.parentAgentId,
    prompt: opts.prompt,
    model: normalizeAgentModel(opts.model, opts.allowLargeModels ?? false),
    get status(): LocalAgentTaskStatus { return _status; },
    set status(s: LocalAgentTaskStatus) { _status = s; },
    createdAt: new Date().toISOString(),
    isSubagent: true,
    isConductor: false,
    signal: controller.signal,
    tokenUsage: undefined,
    result: undefined,
    errorOutput: undefined,
    durationMs: undefined,
    kill(): void {
      if (isTerminal(_status)) return;
      controller.abort();
      _status = 'stopped';
    },
    isKilled(): boolean {
      return isTerminal(_status);
    },
  };

  return task;
}

// ---------------------------------------------------------------------------
// Lifecycle mutators
// ---------------------------------------------------------------------------

export function markAgentStarted(task: LocalAgentTask): void {
  task.status = 'running';
}

export function markAgentComplete(
  task: LocalAgentTask,
  result: string,
  startTimeMs?: number,
): void {
  if (isTerminal(task.status)) return;
  task.result = result;
  if (startTimeMs !== undefined) {
    task.durationMs = Date.now() - startTimeMs;
  }
  task.status = 'complete';
}

export function markAgentError(task: LocalAgentTask, errorOutput: string): void {
  if (isTerminal(task.status)) return;
  task.errorOutput = errorOutput;
  task.status = 'error';
}

// ---------------------------------------------------------------------------
// Token usage accumulation
// ---------------------------------------------------------------------------

export function accumulateAgentTokenUsage(
  task: LocalAgentTask,
  delta: { input: number; output: number; cacheRead: number },
): void {
  if (task.tokenUsage === undefined) {
    task.tokenUsage = { input: delta.input, output: delta.output, cacheRead: delta.cacheRead };
  } else {
    task.tokenUsage = {
      input: task.tokenUsage.input + delta.input,
      output: task.tokenUsage.output + delta.output,
      cacheRead: task.tokenUsage.cacheRead + delta.cacheRead,
    };
  }
}
