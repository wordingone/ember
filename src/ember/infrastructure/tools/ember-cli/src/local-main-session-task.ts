// local-main-session-task.ts — singleton task representing the active main session.
// Enforces one-per-session invariant; unregisters itself on terminal state.

import type { AgentId } from '../types/id-types.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MainSessionStatus = 'pending' | 'running' | 'complete' | 'stopped';

export interface LocalMainSessionTask {
  readonly id: string;
  readonly type: 'local_main_session';
  readonly sessionId: string;
  readonly agentId: AgentId;
  readonly cwd: string;
  readonly model: string;
  status: MainSessionStatus;
  readonly createdAt: string;
  completedAt: string | undefined;
  readonly activeSubtaskIds: string[];
  isConductor: boolean;
}

// ---------------------------------------------------------------------------
// Singleton registry (one task per sessionId)
// ---------------------------------------------------------------------------

const _registry = new Map<string, LocalMainSessionTask>();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return 'm' + hex;
}

function isTerminal(status: MainSessionStatus): boolean {
  return status === 'complete' || status === 'stopped';
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export interface CreateLocalMainSessionTaskOptions {
  sessionId: string;
  agentId: AgentId;
  cwd: string;
  model: string;
}

export function createLocalMainSessionTask(
  opts: CreateLocalMainSessionTaskOptions,
): LocalMainSessionTask {
  if (_registry.has(opts.sessionId)) {
    throw new Error(
      `A LocalMainSessionTask already exists for session '${opts.sessionId}'.`,
    );
  }

  const task: LocalMainSessionTask = {
    id: generateId(),
    type: 'local_main_session',
    sessionId: opts.sessionId,
    agentId: opts.agentId,
    cwd: opts.cwd,
    model: opts.model,
    status: 'pending',
    createdAt: new Date().toISOString(),
    completedAt: undefined,
    activeSubtaskIds: [],
    isConductor: false,
  };

  _registry.set(opts.sessionId, task);
  return task;
}

// ---------------------------------------------------------------------------
// Status synchronization
// ---------------------------------------------------------------------------

/**
 * Syncs task status with AppState.isLoading.
 * No-op when the task is already in a terminal state.
 */
export function syncMainSessionStatus(
  task: LocalMainSessionTask,
  isLoading: boolean,
): void {
  if (isTerminal(task.status)) return;
  task.status = isLoading ? 'running' : 'pending';
}

// ---------------------------------------------------------------------------
// Terminal transitions
// ---------------------------------------------------------------------------

export function markMainSessionComplete(task: LocalMainSessionTask): void {
  if (isTerminal(task.status)) return;
  task.status = 'complete';
  task.completedAt = new Date().toISOString();
  _registry.delete(task.sessionId);
}

export function markMainSessionStopped(task: LocalMainSessionTask): void {
  if (isTerminal(task.status)) return;
  task.status = 'stopped';
  task.completedAt = new Date().toISOString();
  _registry.delete(task.sessionId);
}

// ---------------------------------------------------------------------------
// Active subtask tracking
// ---------------------------------------------------------------------------

/**
 * Adds a subtask ID to the active set (no duplicates).
 * When isTeammateTask is true, promotes this session to conductor status.
 */
export function addActiveSubtask(
  task: LocalMainSessionTask,
  subtaskId: string,
  isTeammateTask?: boolean,
): void {
  if (!task.activeSubtaskIds.includes(subtaskId)) {
    task.activeSubtaskIds.push(subtaskId);
  }
  if (isTeammateTask) {
    task.isConductor = true;
  }
}

export function removeActiveSubtask(
  task: LocalMainSessionTask,
  subtaskId: string,
): void {
  const idx = task.activeSubtaskIds.indexOf(subtaskId);
  if (idx !== -1) {
    task.activeSubtaskIds.splice(idx, 1);
  }
}

// ---------------------------------------------------------------------------
// Registry queries
// ---------------------------------------------------------------------------

export function hasMainSessionTask(sessionId: string): boolean {
  return _registry.has(sessionId);
}

export function unregisterMainSessionTask(sessionId: string): void {
  _registry.delete(sessionId);
}
