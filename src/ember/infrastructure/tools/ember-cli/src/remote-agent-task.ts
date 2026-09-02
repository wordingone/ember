// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// remote-agent-task.ts — lifecycle and poll-result tracking for remote subagent tasks.
// Remote agents are polled periodically; this module manages the local mirror of their state.

import type { KillableTask } from './task-infrastructure.ts';
import type { AgentId } from '../types/id-types.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const REMOTE_AGENT_DEFAULT_POLL_INTERVAL_MS = 5_000;
export const REMOTE_AGENT_DEFAULT_MAX_POLL_ATTEMPTS = 720;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RemoteAgentStatus = 'pending' | 'running' | 'complete' | 'stopped' | 'error';

/** Status strings returned by the remote agent API. */
export type RemoteApiStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface RemoteAgentTask extends KillableTask {
  readonly id: string;
  readonly type: 'remote_agent';
  readonly agentId: AgentId;
  readonly remoteSessionId: string;
  readonly prompt: string;
  readonly model: string;
  status: RemoteAgentStatus;
  readonly createdAt: string;
  completedAt: string | undefined;
  result: string | undefined;
  errorOutput: string | undefined;
  error: string | undefined;
  remoteStatus: RemoteApiStatus | undefined;
  pollCount: number;
  readonly pollIntervalMs: number;
  readonly maxPollAttempts: number;
}

// ---------------------------------------------------------------------------
// Status mapping
// ---------------------------------------------------------------------------

/**
 * Maps a remote API status string to the local task status.
 */
export function mapRemoteStatus(
  remoteStatus: RemoteApiStatus,
): RemoteAgentStatus {
  switch (remoteStatus) {
    case 'pending':
    case 'running':
      return 'running';
    case 'completed':
      return 'complete';
    case 'failed':
      return 'error';
    case 'cancelled':
      return 'stopped';
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return 'r' + hex;
}

function isTerminal(status: RemoteAgentStatus): boolean {
  return status === 'complete' || status === 'error' || status === 'stopped';
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export interface CreateRemoteAgentTaskOptions {
  agentId: AgentId;
  remoteSessionId: string;
  prompt: string;
  model: string;
  pollIntervalMs?: number;
  maxPollAttempts?: number;
  cancelFn?: (remoteSessionId: string) => Promise<void>;
}

export function createRemoteAgentTask(
  opts: CreateRemoteAgentTaskOptions,
): RemoteAgentTask {
  const _cancelFn = opts.cancelFn;
  const _remoteSessionId = opts.remoteSessionId;
  let _status: RemoteAgentStatus = 'pending';

  const task: RemoteAgentTask = {
    id: generateId(),
    type: 'remote_agent',
    agentId: opts.agentId,
    remoteSessionId: _remoteSessionId,
    prompt: opts.prompt,
    model: opts.model,
    get status(): RemoteAgentStatus { return _status; },
    set status(s: RemoteAgentStatus) { _status = s; },
    createdAt: new Date().toISOString(),
    completedAt: undefined,
    result: undefined,
    errorOutput: undefined,
    error: undefined,
    remoteStatus: undefined,
    pollCount: 0,
    pollIntervalMs: opts.pollIntervalMs ?? REMOTE_AGENT_DEFAULT_POLL_INTERVAL_MS,
    maxPollAttempts: opts.maxPollAttempts ?? REMOTE_AGENT_DEFAULT_MAX_POLL_ATTEMPTS,
    kill(): void {
      if (isTerminal(_status)) return;
      _status = 'stopped';
      task.completedAt = new Date().toISOString();
      // Fire-and-forget: best-effort cancellation
      if (_cancelFn) {
        void Promise.resolve().then(() => _cancelFn(_remoteSessionId));
      }
    },
    isKilled(): boolean {
      return isTerminal(_status);
    },
  };

  return task;
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function markRemoteAgentStarted(task: RemoteAgentTask): void {
  task.status = 'running';
}

// ---------------------------------------------------------------------------
// Poll result application
// ---------------------------------------------------------------------------

export interface RemotePollResult {
  status: RemoteApiStatus;
  result?: string;
  errorOutput?: string;
}

/**
 * Applies a poll result to the task, advancing its state.
 * No-op when the task is already in a terminal state.
 * Transitions to 'error' when maxPollAttempts is reached.
 */
export function applyRemotePollResult(
  task: RemoteAgentTask,
  poll: RemotePollResult,
): void {
  if (isTerminal(task.status)) return;

  task.remoteStatus = poll.status;
  task.pollCount += 1;

  const localStatus = mapRemoteStatus(poll.status);

  if (localStatus === 'complete') {
    task.result = poll.result;
    task.completedAt = new Date().toISOString();
    task.status = 'complete';
    return;
  }

  if (localStatus === 'error') {
    task.errorOutput = poll.errorOutput;
    task.completedAt = new Date().toISOString();
    task.status = 'error';
    return;
  }

  if (localStatus === 'stopped') {
    task.completedAt = new Date().toISOString();
    task.status = 'stopped';
    return;
  }

  // Still running — check poll cap
  if (task.pollCount >= task.maxPollAttempts) {
    task.error = `Remote agent timed out after ${task.maxPollAttempts} poll attempts.`;
    task.status = 'error';
    return;
  }

  task.status = 'running';
}
