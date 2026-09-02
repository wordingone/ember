// Teammate view state and helpers for multi-agent coordinator mode.
// One panel visible at a time; entering B while A is shown exits A first.

import type { AgentId } from "../types/id-types.ts";
import type { Message } from "../types/message-types.ts";
import type { Store } from "./state-store.ts";
import type { AppState, TeammateTaskView } from "./app-state.ts";
import { PANEL_GRACE_MS } from "./state-lifecycle.ts";

// Re-export for external consumers.
export type { TeammateTaskView } from "./app-state.ts";

/** Options accepted by enterTeammateView. */
export interface EnterTeammateViewOptions {
  /** When true, route user input to this agent. Default: false. */
  routeInput?: boolean;
  taskId?: string;
  agentName?: string;
  agentColor?: string;
  teamName?: string;
}

/**
 * Activates the teammate view panel for the given agent.
 * If another panel is already open, it is dismissed first.
 * Returns a teardown function that calls exitTeammateView.
 */
export function enterTeammateView(
  store: Store<AppState>,
  agentId: AgentId,
  options: EnterTeammateViewOptions,
): () => void {
  // Dismiss any existing panel first (AC1)
  const current = store.getState().viewedTeammateTask;
  if (current !== null) {
    exitTeammateView(store);
  }

  const panel: TeammateTaskView = {
    agentId,
    taskId: options.taskId,
    agentName: options.agentName,
    agentColor: options.agentColor,
    teamName: options.teamName,
    status: "running",
    startedAt: new Date().toISOString(),
    messages: [],
    inputRouted: options.routeInput ?? false,
  };

  store.setState((s) => ({
    ...s,
    viewedTeammateTask: panel,
    activeAgentForInput: options.routeInput ? agentId : s.activeAgentForInput,
  }));

  return () => exitTeammateView(store);
}

/**
 * Deactivates the teammate view.
 * Clears viewedTeammateTask and activeAgentForInput to null.
 */
export function exitTeammateView(store: Store<AppState>): void {
  store.setState((s) => ({
    ...s,
    viewedTeammateTask: null,
    activeAgentForInput: null,
  }));
}

/**
 * Dismisses the teammate panel for the given agent.
 * - If the agent is running, sets panel status to 'dismissed' (stop signal is
 *   the caller's responsibility to send — this module only manages display state).
 * - If already dismissed, this is a no-op.
 * Idempotent: calling multiple times has no additional effect after the first.
 */
export function stopOrDismissAgent(store: Store<AppState>, agentId: AgentId): void {
  const panel = store.getState().viewedTeammateTask;
  if (panel === null || panel.agentId !== agentId) return;
  // Once dismissed, no further status transitions (AC5)
  if (panel.status === "dismissed") return;

  store.setState((s) => {
    const p = s.viewedTeammateTask;
    if (p === null || p.agentId !== agentId || p.status === "dismissed") return s;
    return {
      ...s,
      viewedTeammateTask: { ...p, status: "dismissed" as const },
    };
  });
}

/**
 * Transitions the panel to 'complete' or 'error'.
 * No-op if the panel is already in 'dismissed' status (AC5).
 */
export function setTeammateTaskTerminal(
  store: Store<AppState>,
  agentId: AgentId,
  outcome: "complete" | "error",
): void {
  store.setState((s) => {
    const p = s.viewedTeammateTask;
    // Dismissed panels do not accept further transitions (AC5)
    if (p === null || p.agentId !== agentId || p.status === "dismissed") return s;
    return {
      ...s,
      viewedTeammateTask: {
        ...p,
        status: outcome,
        completedAt: new Date().toISOString(),
      },
    };
  });
}
