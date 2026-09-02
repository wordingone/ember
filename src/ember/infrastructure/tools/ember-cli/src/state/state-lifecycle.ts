// State lifecycle types and constants: speculation state, completion boundary,
// teammate panel grace period, and the external-metadata → AppState mapper.

import type { BetaStopReason } from "../types/api-protocol.ts";
import type { PermissionMode } from "../types/permission-types.ts";
import type { Message } from "../types/message-types.ts";

// Re-export for consumers who import from here (avoids double-import from app-state).
export type { SpeculationState, CompletionBoundary } from "./app-state.ts";
import type { SpeculationState, CompletionBoundary } from "./app-state.ts";

/**
 * The reset value for speculationState.
 * MUST be the constant reference — === comparisons in onChangeAppState depend on it.
 */
export const IDLE_SPECULATION_STATE: SpeculationState = Object.freeze({
  isSpeculating: false,
  speculatedMessages: undefined,
  speculatedToolCalls: undefined,
});

/**
 * Duration for which a teammate view panel remains visible after the teammate's
 * task completes. Auto-dismisses after 30 000 ms if the user has not interacted.
 */
export const PANEL_GRACE_MS = 30_000;

/**
 * Converts an externally-supplied session metadata block into the IMMUTABLE
 * portion of AppState. Pure function — no I/O, no state, no side effects.
 */
export function externalMetadataToAppState(metadata: {
  sessionId: string;
  cwd?: string;
  mode?: PermissionMode;
  agentId?: string;
  teamName?: string;
  agentName?: string;
  agentColor?: string;
  isSubagent?: boolean;
  isConductor?: boolean;
  initialMessage?: string;
}): {
  sessionId: string;
  cwd?: string;
  mode?: PermissionMode;
  agentId?: string;
  teamName?: string;
  agentName?: string;
  agentColor?: string;
  isSubagent?: boolean;
  isConductor?: boolean;
  initialMessage?: string;
} {
  return {
    sessionId: metadata.sessionId,
    cwd: metadata.cwd,
    mode: metadata.mode,
    agentId: metadata.agentId,
    teamName: metadata.teamName,
    agentName: metadata.agentName,
    agentColor: metadata.agentColor,
    isSubagent: metadata.isSubagent,
    isConductor: metadata.isConductor,
    initialMessage: metadata.initialMessage,
  };
}
