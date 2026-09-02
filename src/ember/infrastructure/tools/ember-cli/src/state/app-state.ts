// Central immutable application state tree. All mutable state changes flow
// through the store; this module defines the shape and factory functions only.

import type { PermissionMode } from "../types/permission-types.ts";
import type { PermissionRequest, ToolPermissionStatus } from "../types/permission-types.ts";
import type { Message } from "../types/message-types.ts";
import type { AgentId } from "../types/id-types.ts";
import type { BetaStopReason } from "../types/api-protocol.ts";
import type { TaskStateBase } from "../core/task-primitives.ts";
import type { LoopPhase, CognitiveMode } from "../cognitive-mode.ts";
import { deriveCognitiveMode } from "../cognitive-mode.ts";

// ---- Inline types from state-lifecycle (shared here to avoid circular dep) ----

export interface SpeculationState {
  isSpeculating: boolean;
  speculatedMessages?: Message[];
  speculatedToolCalls?: Array<{ toolName: string; estimatedDurationMs: number }>;
}

export interface CompletionBoundary {
  messageIndex: number;
  tokenCount: number;
  timestamp: string;
  // null = intermediate / streaming boundary (no terminal stop reason yet).
  stopReason: BetaStopReason | null;
}

// ---- Teammate view type (defined in teammate-view.ts; referenced here) ----

export interface TeammateTaskView {
  agentId: AgentId;
  taskId?: string;
  agentName?: string;
  agentColor?: string;
  teamName?: string;
  status: "running" | "complete" | "error" | "dismissed";
  startedAt: string;
  completedAt?: string;
  messages: Message[];
  inputRouted: boolean;
}

// ---- AppState ----

/**
 * Central application state tree.
 * IMMUTABLE portion: set at session start, never changes mid-session.
 * MUTABLE portion: changed during the session via store actions.
 */
export interface AppState {
  // --- IMMUTABLE ---
  sessionId: string;
  cwd: string;
  entrypoint: string;
  mode: PermissionMode;
  agentId?: string;
  teamName?: string;
  agentName?: string;
  agentColor?: string;
  isSubagent: boolean;
  isConductor: boolean;
  initialMessage?: string;
  toolPermissions: Record<string, ToolPermissionStatus>;

  // --- MUTABLE ---
  messages: Message[];
  isLoading: boolean;
  inputValue: string;
  currentTask: TaskStateBase | null;
  speculationState: SpeculationState;
  completionBoundary: CompletionBoundary | null;
  viewedTeammateTask: TeammateTaskView | null;
  activeAgentForInput: AgentId | null;
  permissionRequests: PermissionRequest[];
  isDirty: boolean;
  isCompacting: boolean;
  contextWindowTokens: number;
  queueDepth: number;
}

/** Required fields for getDefaultAppState. */
export interface AppStateRequiredOverrides {
  sessionId: string;
  cwd: string;
  entrypoint: string;
  mode: PermissionMode;
}

/** Optional additional overrides accepted by getDefaultAppState. */
export type AppStateOverrides = AppStateRequiredOverrides &
  Partial<
    Pick<
      AppState,
      | "agentId"
      | "teamName"
      | "agentName"
      | "agentColor"
      | "isSubagent"
      | "isConductor"
      | "initialMessage"
      | "toolPermissions"
      | "queueDepth"
    >
  >;

/** Zero-value SpeculationState constant (imported by state-lifecycle). */
const IDLE_SPECULATION_STATE_CONSTANT: SpeculationState = {
  isSpeculating: false,
  speculatedMessages: undefined,
  speculatedToolCalls: undefined,
};

/**
 * Factory function returning a fresh AppState with all mutable fields at zero
 * and the immutable fields populated from `overrides`.
 */
export function getDefaultAppState(overrides: AppStateOverrides): AppState {
  return {
    // Immutable portion
    sessionId: overrides.sessionId,
    cwd: overrides.cwd,
    entrypoint: overrides.entrypoint,
    mode: overrides.mode,
    agentId: overrides.agentId,
    teamName: overrides.teamName,
    agentName: overrides.agentName,
    agentColor: overrides.agentColor,
    isSubagent: overrides.isSubagent ?? false,
    isConductor: overrides.isConductor ?? false,
    initialMessage: overrides.initialMessage,
    toolPermissions: overrides.toolPermissions ?? {},

    // Mutable portion — zero state
    messages: [],
    isLoading: false,
    inputValue: "",
    currentTask: null,
    speculationState: IDLE_SPECULATION_STATE_CONSTANT,
    completionBoundary: null,
    viewedTeammateTask: null,
    activeAgentForInput: null,
    permissionRequests: [],
    isDirty: false,
    isCompacting: false,
    contextWindowTokens: 0,
    queueDepth: overrides.queueDepth ?? 0,
  };
}

/**
 * Converts an externally-provided session metadata object into the IMMUTABLE
 * portion of AppState. Returns a partial state compatible with getDefaultAppState.
 * Pure function — no I/O, no mutation, no external calls.
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
}): Partial<AppState> {
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

// ---- Selector functions ----

/** Returns the currently viewed teammate's active task, or null. */
export function getViewedTeammateTask(state: AppState): TeammateTaskView | null {
  return state.viewedTeammateTask;
}

/**
 * Returns the agent whose input the user is currently directing, or null.
 * Non-null only in multi-agent coordinator mode.
 */
export function getActiveAgentForInput(state: AppState): AgentId | null {
  return state.activeAgentForInput;
}

// ---- Loop-phase ring (AC9-AC10) ----

/**
 * Bounded ring capacity for cognitive-mode history.
 * Eviction keeps newest entries (mirrors telemetry's slice strategy).
 */
const MAX_MODE_HISTORY = 100;

let _currentPhase: LoopPhase = "idle";
let _modeHistory: CognitiveMode[] = [];

/**
 * Publishes a loop-phase transition.
 * Appends the derived CognitiveMode to the bounded history ring.
 * Evicts the oldest entries when the ring exceeds MAX_MODE_HISTORY.
 */
export function setLoopPhase(phase: LoopPhase): void {
  _currentPhase = phase;
  _modeHistory.push(deriveCognitiveMode(phase));
  if (_modeHistory.length > MAX_MODE_HISTORY) {
    _modeHistory = _modeHistory.slice(_modeHistory.length - MAX_MODE_HISTORY);
  }
}

/**
 * Returns the CognitiveMode derived from the most recently published LoopPhase.
 * Defaults to "observe" (idle) before any phase has been published.
 */
export function getCognitiveMode(): CognitiveMode {
  return deriveCognitiveMode(_currentPhase);
}

/**
 * Returns a shallow copy of the cognitive-mode history ring (newest at the end).
 * The ring holds at most MAX_MODE_HISTORY entries.
 */
export function getModeHistory(): CognitiveMode[] {
  return [..._modeHistory];
}

/**
 * Resets loop-phase state to initial values.
 * For use in tests only — isolates module-level state between test cases.
 */
export function resetLoopPhaseForTests(): void {
  _currentPhase = "idle";
  _modeHistory = [];
}
