// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// in-process-teammate-task.ts — task and message-delivery for an in-process teammate agent.
// The factory returns { task, delivery } so the runtime layer can push messages into
// the task's inbox without the task holding a direct reference to the runner.

import type { KillableTask } from './task-infrastructure.ts';
import type { AgentId } from '../types/id-types.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TeammateMessage {
  role: 'assistant' | 'user';
  content: string;
  uuid: string;
  timestamp: string;
}

export type TeammateStatus = 'pending' | 'running' | 'stopped';

export interface InProcessTeammateTask extends KillableTask {
  readonly id: string;
  readonly type: 'in_process_teammate';
  readonly identity: string;
  readonly agentName: string;
  readonly teamName: string;
  readonly sessionId: string;
  readonly agentId: AgentId;
  readonly cwd: string;
  status: TeammateStatus;
  readonly createdAt: string;
  completedAt: string | undefined;
  isRunning: boolean;
  sendMessage(content: string): Promise<void>;
  getMessages(): TeammateMessage[];
  onMessage(cb: (msg: TeammateMessage) => void): () => void;
  stop(): Promise<void>;
}

export interface TeammateDelivery {
  deliver(msg: TeammateMessage): void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return 't' + hex;
}

function isTerminal(status: TeammateStatus): boolean {
  return status === 'stopped';
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export interface CreateInProcessTeammateTaskOptions {
  agentId: AgentId;
  teamName: string;
  agentName: string;
  identity: string;
  cwd: string;
  sessionId: string;
  stopFn?: () => Promise<void>;
}

export function createInProcessTeammateTaskWithDelivery(
  opts: CreateInProcessTeammateTaskOptions,
): { task: InProcessTeammateTask; delivery: TeammateDelivery } {
  const _messages: TeammateMessage[] = [];
  const _listeners = new Set<(msg: TeammateMessage) => void>();
  const _stopFn = opts.stopFn;
  let _status: TeammateStatus = 'pending';
  let _isRunning = false;
  let _completedAt: string | undefined;

  async function stop(): Promise<void> {
    if (isTerminal(_status)) return;
    _status = 'stopped';
    _completedAt = new Date().toISOString();
    _isRunning = false;
    if (_stopFn) {
      await _stopFn();
    }
  }

  const task: InProcessTeammateTask = {
    id: generateId(),
    type: 'in_process_teammate',
    identity: opts.identity,
    agentName: opts.agentName,
    teamName: opts.teamName,
    sessionId: opts.sessionId,
    agentId: opts.agentId,
    cwd: opts.cwd,
    get status(): TeammateStatus { return _status; },
    set status(s: TeammateStatus) { _status = s; },
    createdAt: new Date().toISOString(),
    get completedAt(): string | undefined { return _completedAt; },
    set completedAt(v: string | undefined) { _completedAt = v; },
    get isRunning(): boolean { return _isRunning; },
    set isRunning(v: boolean) { _isRunning = v; },
    async sendMessage(_content: string): Promise<void> {
      // Non-blocking send to runtime layer (deferred dep).
    },
    getMessages(): TeammateMessage[] {
      return [..._messages];
    },
    onMessage(cb: (msg: TeammateMessage) => void): () => void {
      _listeners.add(cb);
      return () => _listeners.delete(cb);
    },
    stop,
    kill(): void {
      // Synchronously starts stop(); async tail (stopFn await) runs in background.
      void stop();
    },
    isKilled(): boolean {
      return isTerminal(_status);
    },
  };

  const delivery: TeammateDelivery = {
    deliver(msg: TeammateMessage): void {
      _messages.push(msg);
      for (const cb of [..._listeners]) {
        try {
          cb(msg);
        } catch {
          // Resilient delivery — one bad subscriber must not block others.
        }
      }
    },
  };

  return { task, delivery };
}

// ---------------------------------------------------------------------------
// Lifecycle mutators
// ---------------------------------------------------------------------------

export function markTeammateStarted(task: InProcessTeammateTask): void {
  task.status = 'running';
}

export function markTeammateTurnStart(task: InProcessTeammateTask): void {
  task.isRunning = true;
}

export function markTeammateTurnEnd(task: InProcessTeammateTask): void {
  task.isRunning = false;
}
