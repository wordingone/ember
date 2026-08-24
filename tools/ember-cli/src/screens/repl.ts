// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl.ts — interactive REPL screen.
// Full-screen conversation loop: virtual transcript, spinner, prompt input,
// and status bar. Drives the QueryEngine via dynamic import of session-init
// and builtin-tools (loaded lazily on first user submission).
// Bundle: screens/repl.ts (line 322314)

import React, {
  useState,
  useRef,
  useCallback,
  useMemo,
  useEffect,
  useContext,
} from "react";
import { Box, Text, TerminalSizeContext } from "../ink/components.ts";
import { useInput, useInterval } from "../ink/hooks.ts";
import {
  VirtualMessageList,
  type SessionMessage,
} from "../components/app-shell.ts";
import {
  StatusLine,
  type PermissionModeState,
  type TaskPanelState,
  type Task,
  type EffortCalloutState,
} from "../components/status-bar.ts";
import {
  PromptInput,
  usePromptInput,
  parseInputMode,
  type PromptInputState,
  type PermissionMode as PromptPermissionMode,
} from "../components/prompt-input.ts";
import { IdleReturnDialog, CostDialog } from "../components/dialogs.ts";
import { Homescreen, type BoardSummary, type HomescreenProps } from "../components/logo-homescreen.ts";
import { FIREBALL_IDLE_POSE_FRAME } from "../components/fireball.ts";
import { SlashDropdown }                from "../components/slash-dropdown.ts";
import {
  shouldShowSlashDropdown,
  slashQueryFrom,
  filterSlashCommands,
  moveDropdownSelection,
  completeSlashSelection,
  computeSlashDropdownDisplay,
  slashDropdownMaxVisible,
  slashDropdownCanRender,
} from "../services/slash-dropdown.ts";
import { findCommand, getCommands } from "../command-registry.ts";
import type { RegistryCommand } from "../types/command-types.ts";
import {
  buildMessageLookups,
  UserTextMessage,
  AssistantTextMessage,
  AssistantToolUseMessage,
  SystemAPIErrorMessage,
  CompactionProgressMessage,
  UserCommandMessage,
  type MessageLookups,
} from "../components/message-renderers.ts";
import { UserToolResultMessage }        from "../components/tool-result-renderers.ts";
import {
  ActivityTranscriptBlock,
  DEFAULT_PATH_MAX_LEN,
  type ActivityFeedLine,
} from "../components/activity-feed-pane.ts";
import {
  SpinnerAnimationRow,
  ANIMATION_LOOP_MS,
}                                        from "../components/spinner.ts";
import { QueryEngine, type QueryEvent, type ResultEvent, type RetryAttemptInfo } from "../core/query-engine.ts";
import type { PermissionBehavior, Tool } from "../core/tool-interface.ts";
import {
  getDiagnostics,
  getState,
  startTelemetryWatch,
  type TelemetryState,
}                                        from "../services/telemetry-watch.ts";
import { telemetryMemoKey }              from "../services/telemetry-label.ts";
import { driveOperatorControl, type OperatorControlAction } from "../services/operator-controls.ts";
import {
  OPERATOR_CONTROL_ACTIONS,
  isOperatorControlEnabled,
  operatorControlDisabledReason,
  operatorControlStatus,
  nextOperatorFocusIndex,
} from "../components/operator-surface-pane.ts";
import {
  getActivityFeedState,
  publishActivityFeedInfrastructureFailure,
  startActivityFeed,
}                                        from "../services/activity-feed.ts";
import {
  createPollFailureStatusTracker,
  type PollFailureStatusEntry,
  type PollFailureStatusTracker,
} from "../services/poll-failure-status.ts";
import { advanceActivityTranscript }      from "../services/activity-transcript-window.ts";
import { useModelMetricsPoller }         from "../services/model-metrics-poller.ts";
import { useCircuitBreakerBanner, useRoundtripAge } from "../services/circuit-breaker-banner-poller.ts";
import { useOutageBanner }               from "../services/outage-banner-poller.ts";
import {
  executePromptSuggestion,
  makeSuggestionExecutor,
} from "../services/prompt-suggestion.ts";
import type { AppState } from "../state/app-state.ts";
import type { EmberMessage } from "../types/message-types.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";
import {
  tryDispatchSlashCommandSafely,
  parseSlashInput,
} from "../services/slash-dispatch.ts";
import { consumePostCompaction } from "../session-state.ts";
import { OperatorInjector } from "../services/operator-input.ts";
import { startOperatorPipe } from "../services/operator-pipe.ts";
import {
  createOperatorReceiptWriter,
  type OperatorReceiptWriter,
} from "../services/operator-receipts.ts";
import {
  parseLaunchAuthorityParameters,
  type StartParameters,
} from "../components/start-parameters.ts";
import {
  updateOperatorControlNotice,
  type OperatorControlNotice,
} from "../services/operator-control-notice.ts";
import {
  createLivenessHeartbeatWriter,
  isHeadlessCapture,
  readHeartbeatRow,
  type LivenessHeartbeatWriter,
} from "../services/liveness-heartbeat.ts";
import { createCockpitMemoryFootprintSupervisor } from "../services/memory-footprint-cockpit.ts";
import { createLiveServingTopologyService } from "../services/serving-topology-live.ts";
import { resolveEmberRepoRoot } from "../utils/repo-root.ts";
import { emberStatePath } from "../utils/ember-state-root.ts";
import {
  createGoalContinuationEngine,
  type ContinuationEligibilitySignals,
  type GoalContinuationEngine,
} from "../core/goal-continuation.ts";
import { getGoalStore, getGoalReceiptWriter } from "../core/goal-runtime.ts";
import {
  createGoalContinuationPoke,
  isGoalContinuationFeatureEnabled,
  startGoalContinuationRearm,
} from "../core/goal-continuation-wiring.ts";
import { setGoalSteeringInjectorProvider, setGoalContinuationTrigger } from "../commands/goal.ts";
import { buildEmberWorldState } from "../core/ember-world-state.ts";
import { useBoardTsPoller } from "../services/board-ts-poller.ts";
import { formatCockpitRestartEvent } from "../core/monitor-render.ts";
import { useGpuStatePoller, formatGpuStateLine } from "../services/gpu-state-poller.ts";
import { useHostTelemetryPoller } from "../services/host-telemetry-poller.ts";
import {
  useActiveRunPoller,
  isActiveRunFresh,
  formatActiveRunLine,
} from "../services/run-progress-scanner.ts";
import { useReceiptLandingPoller, formatLastReceiptLine } from "../services/receipt-landing-poller.ts";
import path from "node:path";
import fs from "node:fs";
import { OperatorSurfacePane } from "../components/operator-surface-pane.ts";
import { commandBarMaxRows } from "../components/command-bar-pane.ts";
import type { CommandButtonActivation } from "../services/command-buttons.ts";
import {
  buildProcessOptions,
  captureStartReview,
  outstandingProcessOffer,
  startActivation,
} from "../services/process-select.ts";
import { verifySourceBinding } from "../entrypoints/source-binding-verifier.ts";
import type { ModelSeatState } from "../entrypoints/model-seat.ts";
import { getModelSeatState } from "../entrypoints/session-init.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export type ReplPermissionMode = PromptPermissionMode;

export const DEFAULT_REPL_PERMISSION_MODE: ReplPermissionMode = "regular";

export const REPL_PERMISSION_CYCLE: ReplPermissionMode[] = [
  "regular",
  "bypass",
  "plan",
];

export const COMPACTION_TOKEN_THRESHOLD = 180_000;
export const COMPACTION_INDICATOR_TEXT  = "Razzle-dazzling...";
export const ANALYTICS_SESSION_START    = "ember_repl_session_start";
export const ANALYTICS_SESSION_END      = "ember_repl_session_end";

/** #1701: ms of report()-silence for a watcher-poller failure class before it is presumed
 *  recovered (sticky-status sweep, below). The fastest poller (memory-footprint) polls every
 *  ~1s and the slowest wired here (serving-topology) every ~5s; this sits comfortably above
 *  both so a single missed tick never flaps the status between active/recovered. */
export const POLL_FAILURE_RECOVERY_MS = 20_000;

/** Width budget for the in-window provenance/agent pane. */
export function operatorSurfaceWidth(terminalColumns: number): number {
  if (!Number.isFinite(terminalColumns) || terminalColumns <= 0) return 28;
  const minTranscript = Math.min(20, Math.max(10, Math.floor(terminalColumns * 0.5)));
  const minPane = Math.min(28, Math.max(10, Math.floor(terminalColumns * 0.5)));
  const preferred = Math.floor(terminalColumns * 0.42);
  const maxPane = Math.max(minPane, terminalColumns - minTranscript);
  return Math.max(minPane, Math.min(maxPane, preferred));
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ReplConfig {
  model:                 string;
  permissionMode:        ReplPermissionMode;
  baseSystemPrompt:      string;
  systemPromptOverride?: string;
}

export interface SystemPromptParts {
  base:         string;
  override?:    string;
  append?:      string;
  outputStyle?: string;
  ideContext?:  string;
}

export interface PermissionQueueItem {
  kind: "sandbox" | "worker-pending" | "permission";
  [key: string]: unknown;
}

export interface DialogState {
  permissionQueue: PermissionQueueItem[];
  idleReturn:      boolean;
  costThreshold:   boolean;
  promptDialog:    boolean;
}

export type ActiveDialogKind =
  | "sandbox-permission"
  | "worker-pending"
  | "permission"
  | "cost-threshold"
  | "idle-return"
  | "prompt-dialog"
  | null;

export interface ReplScreenProps {
  config:          ReplConfig;
  cwd:             string;
  /** Stable identity supplied by the mounted production entrypoint. */
  sessionId?:      string;
  env?:            NodeJS.ProcessEnv;
  analytics?:      { log: (event: string, props?: Record<string, unknown>) => void };
  ideIntegration?: { context?: string };
  outputStyles?:   { activeStylePrompt?: string };
  session?:        unknown;
  operatorReceiptWriter?: OperatorReceiptWriter;
  onExit?:         () => void;
  /** Existing model-seat authority's live lifecycle projection. */
  modelSeat?:      ModelSeatState;
}

// ---------------------------------------------------------------------------
// Pure helpers (spec — preserve exactly)
// ---------------------------------------------------------------------------

export function shouldWriteTerminalTitle(env: NodeJS.ProcessEnv = process.env): boolean {
  return !env["EMBER_DISABLE_TERMINAL_TITLE"];
}

export function shouldUseVirtualScroll(env: NodeJS.ProcessEnv = process.env): boolean {
  return !env["EMBER_DISABLE_VIRTUAL_SCROLL"];
}

export function isExitCommandInput(text: string): boolean {
  return /^\/(?:exit|quit)\s*$/i.test(text);
}

export function shouldShowMessageActions(env: NodeJS.ProcessEnv = process.env): boolean {
  return !env["EMBER_DISABLE_MESSAGE_ACTIONS"];
}

/**
 * Eagerly marks the input buffer as consumed in its ref mirror, synchronously
 * -- ember #276 (live acceptance leg (b): /goal <objective> persisted a goal
 * then fired ZERO continuations across a 30-minute wall cap).
 *
 * inputStateRef (below) is a plain ref synced to usePromptInput's React state
 * only on this component's NEXT render (`inputStateRef.current = inputState`
 * in the render body). This app's custom react-reconciler host config
 * schedules updates triggered from outside React's own event dispatch via
 * queueMicrotask/setTimeout -- and keyboard input always arrives that way
 * (ink/stdin-bridge.ts's raw stdin listener calling _deliverKeyEvent, never a
 * React SyntheticEvent) -- which needs a REAL event-loop turn to flush, not
 * just a couple of promise-microtask ticks (empirically confirmed: see
 * ink/app-resize.test.ts's resize-reflow finding, the same reconciler).
 * submitPrompt's own slash-command dispatch (tryDispatchSlashCommand) only
 * awaits already-resolved promises, so it resolves well before that pending
 * render lands. A continuation poke that reads inputStateRef.current.text
 * right after /goal's create handler cleared the input for submission
 * therefore observed the STALE pre-clear text, wrongly reported
 * queued_user_input, and silently skipped the very first continuation
 * attempt -- with no later user input or turn-completion left to ever
 * re-poke it, the goal sat at Active forever. Calling this at the exact
 * moment inputActions.setText("") is invoked to submit removes that window.
 */
export function clearInputRefForSubmit(
  inputStateRef: { current: PromptInputState },
): void {
  inputStateRef.current = { ...inputStateRef.current, text: "", cursor: 0 };
}

export function cycleReplPermissionMode(current: ReplPermissionMode): ReplPermissionMode {
  const idx  = REPL_PERMISSION_CYCLE.indexOf(current);
  const next = REPL_PERMISSION_CYCLE[(idx + 1) % REPL_PERMISSION_CYCLE.length];
  return next ?? DEFAULT_REPL_PERMISSION_MODE;
}

/** Session-level authority applied after each tool has produced its own permission verdict. */
export function authorizeReplTool(
  mode: ReplPermissionMode,
  tool: Tool<any, any>,
  input: unknown,
  behavior: PermissionBehavior,
): boolean {
  if (behavior === "deny") return false;
  if (mode === "bypass") return true;
  return behavior === "allow" && tool.isReadOnly(input);
}

/**
 * B7 item 2 ("kill the void", operator regrade 2026-07-03): bottom-anchors (flex-end) a
 * sparse/in-session transcript's content toward the prompt, unchanged from the existing
 * behavior. B7 item 2 regrade ("welcome void dominance", 2026-07-03): a FRESH BOOT (welcome
 * panel only, no conversation entry yet) instead top-anchors (flex-start) -- this flips the
 * moment a real turn lands, and is one-way for the session: no scenario removes a landed entry.
 */
export function transcriptJustifyContent(messages: SessionMessage[]): "flex-start" | "flex-end" {
  // #561/#565: the welcome/board banner is no longer a `messages[0]` entry (it's now an
  // always-mounted top-locked region, see ReplScreen's render below) -- "welcome-only" is simply
  // "no turns have landed yet".
  const isWelcomeOnly = messages.length === 0;
  return isWelcomeOnly ? "flex-start" : "flex-end";
}

// VirtualMessageList already owns newest-at-bottom placement with column-reverse. Its parent
// must stay flex-start so multi-pass text fitting cannot apply a second, stale negative offset.
export function transcriptViewportJustifyContent(
  useVirtualScroll: boolean,
  messages: SessionMessage[],
): "flex-start" | "flex-end" {
  return useVirtualScroll ? "flex-start" : transcriptJustifyContent(messages);
}

/**
 * issue #44 item (c), "document-flow" (operator's live-pixel verdict, 2026-07-04) -- REVERTED by
 * issue #114's final leg (operator's live DESKTOP-scale verdict, 2026-07-05). The document-flow
 * fix set flexGrow:0 for welcome-only sessions on the theory that the field exemplar "never
 * stretches at session start" -- a real side-by-side desktop capture (half-split 1720x1440, the
 * exemplar visible in the same frame) disproved that: the exemplar pins prompt+status to the
 * WINDOW BOTTOM even when almost no content exists above. flexGrow:0 instead left input+status
 * floating directly under a content-sized panel with ~85% of the terminal below the status bar
 * completely unclaimed. flexGrow is therefore always 1 -- input+status pin to the true bottom
 * rows in every state, welcome-only included; transcriptJustifyContent (unchanged) still controls
 * where content sits inside that grown box.
 */
export function transcriptFlexGrow(_messages: SessionMessage[]): 0 | 1 {
  return 1;
}

export function isThinkingChunk(chunk: { stop_reason: string | null }): boolean {
  return chunk.stop_reason === null;
}

export function shouldRenderChunk(chunk: { stop_reason: string | null }): boolean {
  return !isThinkingChunk(chunk);
}

export function filterRenderableChunks<T extends { stop_reason: string | null }>(
  chunks: T[],
): T[] {
  return chunks.filter(shouldRenderChunk);
}

export function shouldTriggerCompaction(tokenCount: number): boolean {
  return tokenCount >= COMPACTION_TOKEN_THRESHOLD;
}

export function addToPermissionQueue(
  queue: PermissionQueueItem[],
  item:  PermissionQueueItem,
): PermissionQueueItem[] {
  return [...queue, item];
}

export function queueActiveDialog(queue: PermissionQueueItem[]): PermissionQueueItem | null {
  return queue[0] ?? null;
}

export function resolvePermissionQueue(
  queue: PermissionQueueItem[],
): PermissionQueueItem[] {
  return queue.slice(1);
}

export function selectActiveDialog(state: DialogState): ActiveDialogKind {
  const top = queueActiveDialog(state.permissionQueue);
  if (top !== null) {
    if (top.kind === "sandbox")        return "sandbox-permission";
    if (top.kind === "worker-pending") return "worker-pending";
    return "permission";
  }
  if (state.costThreshold) return "cost-threshold";
  if (state.idleReturn)    return "idle-return";
  if (state.promptDialog)  return "prompt-dialog";
  return null;
}

export function buildJsonlEntry(
  message:   SessionMessage,
  gitBranch: string | undefined,
): SessionMessage & { gitBranch: string | undefined } {
  return { ...message, gitBranch };
}

export function assembleSystemPrompt(parts: SystemPromptParts): string {
  let prompt = parts.override !== undefined ? parts.override : parts.base;
  if (parts.append)      prompt = `${prompt}\n${parts.append}`;
  if (parts.outputStyle) prompt = `${prompt}\n${parts.outputStyle}`;
  if (parts.ideContext)  prompt = `${prompt}\n${parts.ideContext}`;
  return prompt;
}

export function isShellModeInput(text: string): boolean {
  return parseInputMode(text).mode === "bash";
}

export function extractShellCommand(text: string): string {
  const parsed = parseInputMode(text);
  return parsed.mode === "bash" ? parsed.value : text;
}

export function toggleTaskPanel(current: boolean): boolean {
  return !current;
}

// ---------------------------------------------------------------------------
// Internal: telemetry memo key (mirrors status-bar formatTelemetryLabel)
// Prevents unnecessary re-renders when telemetry hasn't changed meaningfully.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// renderMsgDispatch — routes a SessionMessage to the correct renderer
// ---------------------------------------------------------------------------

export function renderMsgDispatch(
  msg:           SessionMessage,
  lookups:       MessageLookups,
  viewportWidth: number = 80,
  /** Live command registry, threaded through so the welcome screen's spine block resolves against
   *  real commands. Omitted -> the block renders every spine function BLOCKED, which is honest but
   *  useless; both call sites pass it. */
  spineCommands?: readonly RegistryCommand[] | null,
): React.ReactElement {
  switch (msg.type) {
    case "welcome":
      // #303: Pass boardSummary and dataRoot to the Homescreen.
      return React.createElement(Homescreen, {
        key:   msg.id,
        state: {
          model:   String(msg["model"]   ?? ""),
          cwd:     String(msg["cwd"]     ?? ""),
          version: String(msg["version"] ?? "0.0.0"),
          dataRoot: String(msg["dataRoot"] ?? ""),
        },
        viewportWidth,
        boardSummary: msg["boardSummary"] as any, // eslint-disable-line @typescript-eslint/no-explicit-any
        spineCommands,
        launchDir: process.cwd(),
      });

    case "user":
      return React.createElement(UserTextMessage, {
        key:    msg.id,
        text:   String(msg["content"] ?? ""),
        origin: msg["origin"] === "operator" ? "operator" : undefined,
      });

    case "assistant":
      return React.createElement(AssistantTextMessage, {
        key:  msg.id,
        text: String(msg["content"] ?? ""),
      });

    case "tool_use":
      return React.createElement(AssistantToolUseMessage, {
        key:       msg.id,
        toolUseId: String(msg["toolUseId"] ?? msg.id),
        toolName:  String(msg["toolName"]  ?? ""),
        lookups,
      });

    case "tool_result": {
      const result = {
        type:        "tool_result"  as const,
        tool_use_id: String(msg["tool_use_id"] ?? ""),
        content:     String(msg["content"]     ?? ""),
        is_error:    msg["is_error"] === true,
      };
      return React.createElement(UserToolResultMessage, { key: msg.id, result });
    }

    case "error":
      // issue #197: default was 4 (SystemAPIErrorMessage hid EVERYTHING for
      // retryCount<=3 and showed a "Retrying…" trailer above that), so EVERY
      // terminal error message -- including one where zero retries ever
      // happened -- claimed an in-progress retry that had already ended
      // (operator session #5: "all 4 server slots idle, GPU 0%, yet
      // Retrying… persists"). Fixing just this default to 0 would have made
      // things WORSE (a deterministic 4xx, retryCount=0, would then hide the
      // error entirely) -- so message-renderers.ts's SystemAPIErrorMessage
      // was also corrected to always render a terminal error, with an
      // honest completed-attempts note instead of a live "Retrying…" claim.
      // Live in-flight retry attempts are shown separately, via the
      // status-bar effort callout (see retryStatus state below), which
      // clears the moment the turn ends -- never via a stale count baked
      // into a past transcript entry.
      return React.createElement(SystemAPIErrorMessage, {
        key:        msg.id,
        errorText:  String(msg["content"]    ?? ""),
        retryCount: Number(msg["retryCount"] ?? 0),
      });

    case "command":
      return React.createElement(UserCommandMessage, {
        key:     msg.id,
        command: String(msg["content"] ?? ""),
      });

    case "compaction": {
      const elapsed = msg["elapsedSecs"];
      return React.createElement(CompactionProgressMessage, {
        key:         msg.id,
        isComplete:  msg["isComplete"] === true,
        ...(typeof elapsed === "number" ? { elapsedSecs: elapsed } : {}),
      });
    }

    case "activity": {
      // #518: an organism activity event (receipt landing, board run, watchdog
      // transition, outage window) renders as a transcript card AT ITS TEMPORAL
      // POSITION in the scrollback -- never a ticker line pinned near the status
      // bar. See components/activity-feed-pane.ts's ActivityTranscriptBlock.
      const activityLine: ActivityFeedLine = {
        ts:     String(msg["ts"] ?? new Date().toISOString()),
        source: (msg["source"] as ActivityFeedLine["source"]) ?? "receipt",
        text:   String(msg["text"] ?? ""),
        path:   typeof msg["path"] === "string" ? (msg["path"] as string) : undefined,
      };
      // Path truncation widens with the viewport (live-resize experience-gate finding: a fixed
      // 48-char cap left a wide terminal truncating a path that had plenty of room) -- never
      // narrower than the default, so a small terminal keeps today's behavior exactly.
      const activityPathMaxLen = Math.max(DEFAULT_PATH_MAX_LEN, viewportWidth - 12);
      return React.createElement(ActivityTranscriptBlock, {
        key: msg.id,
        line: activityLine,
        pathMaxLen: activityPathMaxLen,
      });
    }

    default:
      return React.createElement(Text, { key: msg.id }, String(msg["content"] ?? ""));
  }
}

// ---------------------------------------------------------------------------
// applyResultEvent — issue #157/#49: the submit loop's for-await terminates on
// every "result" event by just breaking, discarding whatever the event carried.
// On the error/max_turns paths that's the ONLY place the loop's synthesized
// closing text (or the real transport error) ever lands -- query-engine.ts
// never emits a matching "assistant" event for those subtypes. Dropping the
// result event silently left the empty streaming placeholder on screen
// forever: exactly the "spinner alive, no answer" symptom from the operator-
// session receipts. This is a pure decision function so it's unit-testable
// without mounting the REPL; the submit loop below calls it on every result.
// ---------------------------------------------------------------------------

function extractFinalText(finalMessage: ModelResponse | undefined): string {
  if (!finalMessage || !Array.isArray(finalMessage.content)) return "";
  return (finalMessage.content as Array<{ type?: string; text?: string }>)
    .filter((b) => b && b.type === "text")
    .map((b) => b.text ?? "")
    .join("");
}

export function applyResultEvent(
  event: ResultEvent,
  messages: SessionMessage[],
  pendingId: string,
): SessionMessage[] {
  // User-initiated cancel: intentional, not a failure -- no error surface.
  if (event.subtype === "abort") return messages;

  if (event.subtype === "error") {
    const errText =
      event.errorMessage && event.errorMessage.length > 0
        ? event.errorMessage
        : "An error occurred while processing your request. Unable to complete the operation.";
    return [
      ...messages.filter((m) => m.id !== pendingId),
      { id: crypto.randomUUID(), type: "error", content: errText },
    ];
  }

  const finalMessage = (event as { finalMessage?: ModelResponse }).finalMessage;

  if (event.subtype === "max_turns") {
    // The loop's synthesized closing text (synthesizeFinalMessage in
    // query-engine.ts) never arrives via a streaming "assistant" event for
    // this subtype -- surface it here or the placeholder stays empty forever.
    const text = extractFinalText(finalMessage);
    return [
      ...messages.filter((m) => m.id !== pendingId),
      {
        id: crypto.randomUUID(),
        type: "error",
        content: text || "Reached the turn limit without a final answer.",
      },
    ];
  }

  // success / error_max_tokens: content already arrived via the preceding
  // "assistant" event -- this seam only threads stop_reason/usage metadata
  // onto the pending message, never rewriting content that's already there.
  if (!finalMessage) return messages;
  return messages.map((m) =>
    m.id === pendingId
      ? { ...m, stop_reason: finalMessage.stop_reason, usage: finalMessage.usage }
      : m,
  );
}

// ---------------------------------------------------------------------------
// adaptSessionMessagesForSuggestion — issue #50: prompt-suggestion's guard
// chain (tryGenerateSuggestion) filters on EmberMessage's `role`/`stop_reason`
// fields, but the REPL transcript is SessionMessage[] (`{id, type, ...}` --
// app-shell.ts), which has never carried a `role` field. The call site papered
// over the mismatch with `messages as any`, so Guard 2's
// `messages.filter(m => m.role === "assistant")` always saw zero matches and
// the feature could never fire (confirmed: the "as any" cast at the call site
// and this filter both date to the original publish commit 2051802 -- the
// shapes never matched in production, so the feature was never live).
//
// This is the one boundary adapter (per #50 scope clause 2 -- no forked
// message type): it maps the transcript's SessionMessage[] to the
// EmberMessage[] shape the suggestion module expects, threading the
// stop_reason/usage fields applyResultEvent already attaches at the pending
// message (see above). Guard-4 usage note (#52 clause 6): the adapter copies
// each message's `usage` through UNCHANGED -- getParentCacheSuppressReason
// (prompt-suggestion.ts) reads only the LAST assistant message's own
// input/cache-creation/output token fields (a per-turn, uncached figure, not
// a running cumulative total), so no aggregation belongs at this seam.
// ---------------------------------------------------------------------------

export function adaptSessionMessagesForSuggestion(
  messages: SessionMessage[],
): EmberMessage[] {
  const adapted: EmberMessage[] = [];
  for (const m of messages) {
    // Malformed entries (missing/non-string type, or not an object) are
    // dropped rather than crashing the adapter or the guard chain downstream.
    if (!m || typeof m !== "object" || typeof m.type !== "string") continue;

    let role: EmberMessage["role"] | null = null;
    if (m.type === "user") role = "user";
    else if (m.type === "assistant") role = "assistant";
    // A transcript entry of type "error" (applyResultEvent's error/max_turns
    // paths) replaces the pending assistant bubble for a turn that failed --
    // it IS that turn's assistant outcome, so it maps to role "assistant"
    // with the literal stop_reason "error" Guard 3 checks for.
    else if (m.type === "error") role = "assistant";
    else continue; // welcome/tool_result/compaction/command/etc. -- not a turn

    const content = typeof m["content"] === "string" ? m["content"] : "";
    const entry: EmberMessage = { role, content };
    if (m.type === "error") {
      entry.stop_reason = "error";
    } else if (
      typeof m["stop_reason"] === "string" ||
      m["stop_reason"] === null
    ) {
      entry.stop_reason = m["stop_reason"] as string | null;
    }
    if (m["usage"] !== undefined) {
      entry["usage"] = m["usage"];
    }
    adapted.push(entry);
  }
  return adapted;
}

// ---------------------------------------------------------------------------
// ReplScreen — full-screen interactive REPL
// ---------------------------------------------------------------------------

export function spinnerCadenceForBusy(busy: boolean): number | null {
  return busy ? ANIMATION_LOOP_MS : null;
}

export function ReplScreen({
  config,
  cwd,
  sessionId,
  env            = process.env,
  analytics,
  ideIntegration,
  outputStyles,
  session:        _session,
  operatorReceiptWriter,
  onExit:         _onExit,
  modelSeat,
}: ReplScreenProps): React.ReactElement {
  const { rows: terminalRows, columns: terminalCols } = useContext(TerminalSizeContext);
  // Hoisted because the homescreen, prompt, and palette below all consume the same conversation
  // column width through one render path; no component maintains a mirrored width oracle.
  const paneWidth = operatorSurfaceWidth(terminalCols);
  const mainColumnWidth = Math.max(20, terminalCols - paneWidth);

  const useVirtualScroll = shouldUseVirtualScroll(env);
  const writeTitle       = shouldWriteTerminalTitle(env);
  const [liveModelSeat, setLiveModelSeat] = useState<ModelSeatState | undefined>(modelSeat);
  useInterval(() => {
    const next = getModelSeatState();
    setLiveModelSeat((current) => current && current.phase === next.phase &&
      current.owner === next.owner && current.endpoint === next.endpoint &&
      current.vramBytes === next.vramBytes ? current : next);
  }, 250);

  // #924: the operator surface's source-provenance contract (#921) requires
  // sourceBindingVerified===true before it will render anything but "SOURCE
  // UNVERIFIED/UNBOUND" -- no producer ever set it. This independently binds
  // the claimed EMBER_PUBLIC_SOURCE_COMMIT / EMBER_CLI_BINARY_SHA256 env
  // values to the actual git HEAD + running-binary bytes; fail-closed on any
  // mismatch or unreadable evidence (verifySourceBinding never throws).
  const sourceIdentity = useMemo(() => {
    const publicCommit = env["EMBER_PUBLIC_SOURCE_COMMIT"];
    const binarySha256  = env["EMBER_CLI_BINARY_SHA256"];
    const binding = verifySourceBinding({
      claimedCommit:       publicCommit,
      claimedBinarySha256: binarySha256,
      cwd,
      binaryPath:          process.execPath,
    });
    return {
      publicCommit,
      binarySha256,
      sourceBindingVerified: binding.verified,
    };
  }, [env, cwd]);

  // Every launch request (#1475: START dispatches the SELECTED process) must enter the same
  // governed slash-command path as typed operator input. The ref is populated with the current
  // submitPrompt closure below and lets early-declared handlers remain stable without capturing
  // a stale callback.
  const submitPromptRef = useRef<(text: string, origin?: "keyboard" | "operator") => Promise<void>>(
    async () => {},
  );

  // PAUSE/RESUME/RESTART remain runtime-control intents for an already identified run and are
  // appended to the governed finetune control channel. START must not use that legacy channel:
  // no production poller consumes a start row, and doing so bypasses each command's preflight
  // and /train's single-use confirmation boundary.
  //
  // #1475: START activates the SELECTED process (SELECT PROCESS dropdown) rather than a
  // hardwired /train. The activation is built and dispatched by activateStartRef's closure —
  // assigned every render, below, once the registry state and handleCommandButton exist — so
  // this early-declared, referentially-stable handler never captures stale selection state.
  const activateStartRef = useRef<() => void>(() => {});
  const openControlDialogRef = useRef<(action: OperatorControlAction, runId?: string) => void>(() => {});
  const operatorControlChannelPath = env["EMBER_FINETUNE_CONTROL_PATH"];
  const handleOperatorControl = useCallback((action: OperatorControlAction, runId?: string) => {
    if (action === "START") {
      activateStartRef.current();
      return;
    }
    openControlDialogRef.current(action, runId);
  }, []);

  // R2b: keyboard-reachable operator controls. `paneFocused` is the single discriminator for
  // both halves of the invariant -- "operator surface focused" and "no text input active" are
  // the same fact in this app (there is exactly one thing with keyboard focus at a time), so one
  // boolean suffices rather than two that could drift apart. `focusedControlIndex` is the
  // traversal position within OPERATOR_CONTROL_ACTIONS while paneFocused is true; it is ignored
  // (and the pane renders no marker) whenever paneFocused is false.
  const [paneFocused,          setPaneFocused]          = useState(false);
  const [focusedControlIndex,  setFocusedControlIndex]  = useState(0);
  const [hoveredControl, setHoveredControl] = useState<OperatorControlAction | undefined>(undefined);
  const [activityScrollOffset, setActivityScrollOffset] = useState(0);
  const [controlDisabledReason, setControlDisabledReason] = useState<string | undefined>(undefined);
  const [controlNotice, setControlNotice] = useState<OperatorControlNotice | undefined>(undefined);
  const [controlDialog, setControlDialog] = useState<{
    action: OperatorControlAction;
    runId?: string;
    parameters: StartParameters;
    sourcePath: string;
    activation?: CommandButtonActivation;
  } | undefined>(undefined);

  // #1475: click-first SELECT PROCESS run control. The selection is the START control's arming
  // state; the open/page/hover values are pure dropdown presentation. Like the command bar, the
  // dropdown owns NO keyboard focus — selecting a process never takes the keyboard away from
  // the prompt.
  const [selectedProcessState, setSelectedProcess] = useState<string | undefined>(undefined);
  const [processMenuOpen, setProcessMenuOpen] = useState(false);
  const [processMenuPage, setProcessMenuPage] = useState(0);
  const [hoveredProcess, setHoveredProcess] = useState<string | undefined>(undefined);

  // #1370: pointer state for the registry-driven command bar. Deliberately SEPARATE from
  // paneFocused/focusedControlIndex — clicking a command button must never move keyboard focus,
  // so the bar owns no focus state at all, only a hover name and a one-line notice.
  const [hoveredCommand, setHoveredCommand] = useState<string | undefined>(undefined);
  const [commandBarNotice, setCommandBarNotice] = useState<string | undefined>(undefined);
  // Which page of command buttons is showing, bound to the layout it was chosen under. Storing
  // the signature WITH the index is what makes the reset structural: a resize or a registry
  // change produces a different signature, so the remembered index is not merely clamped onto a
  // different set of pages — it is discarded, and the bar reopens at the first page.
  const [commandBarPageState, setCommandBarPageState] =
    useState<{ signature: string; index: number }>({ signature: "", index: 0 });

  const [permMode,         setPermMode]        = useState<ReplPermissionMode>(config.permissionMode);
  const permModeRef = useRef<ReplPermissionMode>(permMode);
  permModeRef.current = permMode;
  const [taskPanelVisible, setTaskPanelVisible] = useState(false);
  const [tasks]                                 = useState<Task[]>([]);
  const [permQueue,        setPermQueue]        = useState<PermissionQueueItem[]>([]);
  const [idleReturn,       setIdleReturn]       = useState(false);
  const [idleTaskCount,    setIdleTaskCount]    = useState(0);
  const [costThreshold,    setCostThreshold]    = useState(false);
  const [promptDialog,     _setPromptDialog]    = useState(false);

  // #561/#565: the welcome/board banner is no longer a `messages[0]` entry -- it lives inside
  // the same scrolling/flex-end-anchored transcript as every other message, so once enough
  // turns or activity events landed it silently scrolled away (the operator's "banner scrolled
  // away" report). It is now an always-mounted, top-locked region (see the render tree below),
  // rendered directly from `config`/`cwd`/`boardSummary`/`dataRoot` -- `messages` starts empty.
  const [messages, setMessages] = useState<SessionMessage[]>([]);

  // #50 round-3 repair: the exact post-applyResultEvent transcript for the
  // in-flight turn, threaded through a DEDICATED React state slot rather than
  // a plain local variable assigned from inside setMessages's own updater and
  // read back synchronously right after (round-2's shape) -- React gives no
  // ordering guarantee that an updater passed to setState has actually run by
  // the time the call site's next line executes, so that read could observe
  // a stale (pre-turn) value. Setting a SECOND piece of state from within the
  // first updater is well-defined (LegacyRoot, no Strict-mode double-invoke
  // here), and the effect below only ever fires once React has committed the
  // exact value written -- never a same-tick, ordering-dependent read.
  const [completedTranscript, setCompletedTranscript] =
    useState<SessionMessage[] | null>(null);

  const mountRef  = useRef(Date.now());
  const engineRef = useRef<QueryEngine | null>(null);
  const abortRef  = useRef<AbortController | null>(null);

  // Prompt-suggestion state — dimmed ghost text rendered after cursor; Tab accepts it.
  const [currentSuggestion, setCurrentSuggestion] = useState<string | null>(null);
  // Ref to the production callModel fn, captured when the engine is first initialised.
  const callModelRef = useRef<((p: CallModelParams) => Promise<ModelResponse>) | null>(null);
  // Ref to latest messages for use inside async callbacks (avoids stale closure).
  const messagesRef  = useRef<SessionMessage[]>([]);
  // Stable per-session id for the slash-command CommandContext.
  const sessionIdRef = useRef<string>(sessionId?.trim() || crypto.randomUUID());

  // Operator input channel (ember #165 / #154) — a local named pipe the operator
  // writes prompts to alongside the keyboard. submitPromptRef always holds the
  // latest submitPrompt closure so the injector (constructed once, below, after
  // usePromptInput) never calls a stale one. One receipt-writer/JSONL file per
  // mounted session.
  const operatorReceiptsRef = useRef<OperatorReceiptWriter | null>(null);
  if (!operatorReceiptsRef.current) {
    operatorReceiptsRef.current = operatorReceiptWriter ?? createOperatorReceiptWriter();
  }

  // #413: cockpit liveness heartbeat -- written every second by the unconditional tick below.
  const livenessHeartbeatRef = useRef<LivenessHeartbeatWriter | null>(null);
  if (!livenessHeartbeatRef.current) {
    livenessHeartbeatRef.current = createLivenessHeartbeatWriter({
      version: process.env["EMBER_VERSION"] ?? "0.0.0",
      telemetryDiagnostics: getDiagnostics,
    });
  }

  // #1698: the memory-footprint and serving-topology watcher pollers below default to a
  // raw console.warn on every failed tick when no error handler is supplied -- that write
  // bypasses Ink's own render stream entirely (Ink only ever writes through the stream this
  // component is mounted with, never the process's raw stdout/stderr), so at 1s/5s poll
  // cadence a persistently-failing poller (e.g. OFFLINE, no EMBER_LAB_PIPE) bled dozens of
  // interleaved raw fragments into the terminal within minutes, overwriting arbitrary panel
  // cells. Route every poller failure through this tracker instead of a raw write.
  //
  // #1701: the original #1698/#1700 fix (services/poll-failure-dedup.ts) republished a NEW
  // activity-feed/transcript line every POLL_FAILURE_DEDUP_INTERVAL_MS window for as long as a
  // class stayed failing -- an idle OFFLINE cockpit's transcript became a monotone ~4-entries/
  // min ticker across the interleaved classes, burying real operator activity. This tracker
  // (services/poll-failure-status.ts) replaces that wiring: it publishes a TRANSITION line only
  // on first-seen / message-changed / recovered, and exposes the steady-state in-place status
  // (pollFailureStatuses, below) for the sticky status region instead. poll-failure-dedup.ts
  // itself is untouched and still valid as a standalone rate-limiting utility -- it is simply no
  // longer the right fit for a status that needs a running count/since, not a repeat window.
  const pollFailureStatusRef = useRef<PollFailureStatusTracker | null>(null);
  if (!pollFailureStatusRef.current) {
    pollFailureStatusRef.current = createPollFailureStatusTracker({
      recoveryAfterMs: POLL_FAILURE_RECOVERY_MS,
      publishTransition: (text) => { publishActivityFeedInfrastructureFailure(text); },
    });
  }
  const [pollFailureStatuses, setPollFailureStatuses] = useState<PollFailureStatusEntry[]>([]);

  // #447: cockpit self-restart event -- read the PREVIOUS session's heartbeat row (if any)
  // exactly once, before this session's own first write (the per-second tick below) overwrites
  // it. A lazy useState initializer runs on mount only, and runs AFTER the ref assignment above
  // in the same render pass, so livenessHeartbeatRef.current is already populated here.
  const [cockpitRestartEvent] = useState<{ text: string; color?: string } | null>(() => {
    const filePath = livenessHeartbeatRef.current?.filePath;
    if (!filePath) return null;
    const previousRow = readHeartbeatRow(filePath);
    const previous = previousRow
      ? { previousTs: previousRow.ts, previousPid: previousRow.pid }
      : null;
    return formatCockpitRestartEvent(previous, process.pid, Date.now());
  });

  // #413/#1330 review round 2: the writer above goes INERT (filePath === null) when repo-root
  // or external-state-root resolution fails -- previously only a console.warn, invisible from
  // inside the TUI. Same one-shot, mount-time pattern as cockpitRestartEvent, so a resolution
  // failure on THIS boot is visible on THIS boot's very first frame, not just in a log an
  // operator has to go find.
  const [heartbeatWriterInert] = useState<{ text: string; color?: string } | null>(() =>
    livenessHeartbeatRef.current?.filePath === null
      ? {
          text: "heartbeat: writer inert -- external liveness checks are blind",
          color: "red",
        }
      : null,
  );

  // #1282 C1: the native cockpit owns the surviving memory-governor poll loop.
  // Headless capture must remain side-effect free, and every live mount owns exactly
  // one supervisor which is stopped during unmount. The external receipt root is
  // resolved strictly before the first poll; failure leaves the supervisor inert.
  useEffect(() => {
    // #1455 diagnostic-only (not shipped behavior): opt-in env kill-switch so a harness can
    // force JUST this poller live without disabling headlessCaptureEnv() globally -- flipping the
    // global flag would also un-suppress activity-feed's watermark write (services/activity-feed.ts),
    // which corrupts the OPERATOR'S real next-cockpit-boot replay-suppression state, not just this
    // harness's own output. Off by default -- normal behavior unchanged unless this exact var is set.
    if (isHeadlessCapture() && process.env["EMBER_DIAGNOSTIC_FORCE_POLLERS_LIVE"] !== "1") return;
    let supervisor: ReturnType<typeof createCockpitMemoryFootprintSupervisor> | null = null;
    try {
      const repoRoot = resolveEmberRepoRoot({});
      supervisor = createCockpitMemoryFootprintSupervisor({
        repoRoot,
        receiptPath: emberStatePath(repoRoot, "memory-footprint-trips.jsonl"),
        // #1698: route every poll-cadence failure through the deduped activity feed
        // instead of the library defaults' raw console.warn (see the deduper's own
        // comment above for why a raw write here corrupts the TUI framebuffer).
        onOwnershipError: (error) => {
          pollFailureStatusRef.current?.report(
            "memory-footprint:ownership",
            `[memory-footprint] Ember Lab process identity unavailable: ${
              error instanceof Error ? error.message : String(error)
            }`,
          );
        },
        onPollError: (error) => {
          pollFailureStatusRef.current?.report(
            "memory-footprint:poll",
            `[memory-footprint] poll failed: ${error instanceof Error ? error.message : String(error)}`,
          );
        },
        warn: (message) => {
          pollFailureStatusRef.current?.report("memory-footprint:trip", message);
        },
      });
      supervisor.start();
    } catch (error) {
      pollFailureStatusRef.current?.report(
        "memory-footprint:inert",
        `[memory-footprint] supervisor is inert: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    return () => supervisor?.stop();
  }, []);

  // #1282 C2: the native cockpit owns the serving-topology cadence.
  // Every five seconds the live OS process set is reconciled against the surviving
  // serving registry. The durable external alarm is appended before this callback
  // makes the drift operator-visible, and headless capture remains side-effect free.
  useEffect(() => {
    // #1455 diagnostic-only (not shipped behavior): see the memory-footprint-supervisor
    // useEffect above for why this is a narrow forced-live switch, not a global
    // headlessCaptureEnv() flip.
    if (isHeadlessCapture() && process.env["EMBER_DIAGNOSTIC_FORCE_POLLERS_LIVE"] !== "1") return;
    let topologyService: ReturnType<typeof createLiveServingTopologyService> | null = null;
    try {
      const repoRoot = resolveEmberRepoRoot({});
      topologyService = createLiveServingTopologyService({
        repoRoot,
        alarmPath: emberStatePath(repoRoot, "serving-alarms.jsonl"),
        notifyOperator: (alarm) => {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              type: "error",
              content:
                `[serving-topology] unregistered=${alarm.unregistered_live_pids.join(",") || "none"} ` +
                `dead=${alarm.dead_registry_pids.join(",") || "none"}; alarm receipt preserved`,
            },
          ]);
        },
        // #1698: route poll-cadence failures through the deduped activity feed
        // instead of the library default's raw console.warn.
        onPollError: (error) => {
          pollFailureStatusRef.current?.report(
            "serving-topology:poll",
            `[serving-topology] poll failed: ${error instanceof Error ? error.message : String(error)}`,
          );
        },
      });
      topologyService.start();
    } catch (error) {
      pollFailureStatusRef.current?.report(
        "serving-topology:inert",
        `[serving-topology] supervisor is inert: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    return () => topologyService?.stop();
  }, []);

  const [busy,           setBusy]           = useState(false);
  const busyRef                             = useRef(false);
  const [spinnerElapsed, setSpinnerElapsed] = useState(0);
  const spinnerStartRef                     = useRef(0);

  // issue #283: an Enter pressed while busy must PREEMPT once idle, never be
  // silently dropped -- the "user always preempts" goal-mode contract. Queue
  // the text here instead of discarding it; the idle-watch effect below
  // flushes it through submitPrompt the instant busy flips false.
  const pendingSubmitRef                    = useRef<string | null>(null);

  // Live retry-attempt status (issue #197 Leg 3/4) — shown via the status
  // bar's existing effort callout, NEVER as a transcript message: a retry is
  // an in-progress, ephemeral condition, not a historical record. Cleared at
  // the start of every submit and in submitPrompt's finally, so it can never
  // outlive the request it describes (the exact zombie-state class this fix
  // targets, one layer up from the render-default bug above).
  const [retryStatus, setRetryStatus] = useState<EffortCalloutState>({ active: false });

  // #303: Board summary + data-root indicator for the welcome screen.
  // boardSummary populates the recent-activity feed; dataRoot shows which tree's data we're reading.
  const [boardSummary, setBoardSummary] = useState<BoardSummary | undefined>(undefined);
  const [dataRoot, setDataRoot] = useState<string | undefined>(undefined);
  // #413: cockpit liveness -- an UNCONDITIONAL per-second re-render, never gated on busy state.
  // A dead process (only the terminal pane surviving on a frozen last frame) freezes both the
  // welcome-screen wall clock and heartbeat file, which is exactly the detector this issue needs.
  const [livenessTick, setLivenessTick] = useState(0);
  useInterval(() => {
    setLivenessTick((tick) => tick + 1);
    livenessHeartbeatRef.current?.write();
  }, 1000);

  // #46 B9 / #898: reuse the mandatory liveness repaint as the idle-fireball clock. The previous
  // dedicated 140 ms interval forced a full layout/tree render/frame parse 7.14 times per second;
  // reduced-motion disabled only that clock, matching #898's strongest bisection delta. Animation
  // is deliberately priced down from about 7 fps to 1 fps so it adds zero animation-only commits.
  // Every existing freeze condition remains fail-closed on the fixed reduced-motion pose.
  const fireballAnimationEnabled =
    messages.length === 0
    && !busy
    && process.env["EMBER_REDUCED_MOTION"] !== "1"
    && process.env["EMBER_ASCII"] !== "1"
    && process.env["NO_COLOR"] === undefined;
  const fireballTick = fireballAnimationEnabled ? livenessTick : FIREBALL_IDLE_POSE_FRAME;

  // Animate spinner at ANIMATION_LOOP_MS cadence
  useInterval(() => {
    if (busyRef.current) {
      setSpinnerElapsed(Date.now() - spinnerStartRef.current);
    }
  }, spinnerCadenceForBusy(busy));

  // Telemetry state (polled every 500ms; deduped by memo key)
  const [telemetry, setTelemetry] = useState<TelemetryState>(() => getState());

  useEffect(() => {
    const handle = startTelemetryWatch();
    return () => handle.stop();
  }, []);

  useInterval(() => {
    const next = getState();
    setTelemetry((prev) =>
      telemetryMemoKey(prev) === telemetryMemoKey(next) ? prev : { ...next },
    );
  }, 500);

  // #485 rung 1 / #518: activity feed — real receipts-landing/outage/watchdog/board events,
  // polled every 500ms. The engine itself is event-driven (fs.watch on receipts/**) plus a
  // couple of cheap poll ticks internally; this is just the render-side pickup. #518 changed
  // WHERE these land: each new line is appended to the conversation `messages` array as a
  // `{type: "activity"}` entry (rendered as ActivityTranscriptBlock, at its temporal position in
  // the scrollback) instead of being kept in separate ticker state fed to the status bar. Lines
  // are deduped by a content key (ts+source+text), not by array index, so the engine's own ring
  // buffer (which shifts old entries once it hits its cap) can never cause a re-render of an
  // already-seen event or the silent loss of a genuinely new one.
  const activityCursorRef = useRef(0);

  useEffect(() => {
    // #1455 diagnostic-only bisection (not shipped behavior): opt-in env kill-switch so a
    // harness can isolate startActivityFeed()'s own engine (recursive receipts/** fs.watch plus its two
    // 1s-cadence intervals) from every other always-on tick source, without needing a second
    // source tree. Off by default -- normal behavior is unchanged unless this exact var is set.
    if (process.env["EMBER_DIAGNOSTIC_DISABLE_ACTIVITY_FEED"] === "1") return;
    const handle = startActivityFeed();
    return () => handle.stop();
  }, []);

  useInterval(() => {
    const next = getActivityFeedState();
    const latest = next.recentLines[next.recentLines.length - 1]?.sequence ?? 0;
    if (latest <= activityCursorRef.current) return;
    setMessages((prev) => {
      const advanced = advanceActivityTranscript(prev, activityCursorRef.current, next.recentLines);
      activityCursorRef.current = advanced.cursor;
      return advanced.messages;
    });
  }, 500);

  // #1701: sweep for watcher-poller failure classes gone silent long enough to be presumed
  // recovered (publishes their one "recovered" transition line) and re-snapshot the active set
  // for the sticky status region below. Piggybacks on the same 500ms cadence as the
  // activity-feed pickup above rather than a new timer -- this is render-side bookkeeping over
  // the tracker's own in-memory state, not a new poll source. Skipped when nothing has ever been
  // active AND nothing is active now, so an idle ONLINE session (no poller ever failed) never
  // re-renders on this tick.
  useInterval(() => {
    pollFailureStatusRef.current?.sweep();
    const next = pollFailureStatusRef.current?.getActiveStatuses() ?? [];
    if (next.length === 0 && pollFailureStatuses.length === 0) return;
    setPollFailureStatuses((prev) => {
      const unchanged =
        prev.length === next.length &&
        prev.every((entry, i) => {
          const candidate = next[i]!;
          return (
            entry.classKey === candidate.classKey &&
            entry.message === candidate.message &&
            entry.count === candidate.count &&
            entry.since === candidate.since &&
            entry.lastSeenAt === candidate.lastSeenAt
          );
        });
      return unchanged ? prev : next;
    });
  }, 500);

  // Keep messagesRef in sync with React state for use inside async callbacks.
  useEffect(() => { messagesRef.current = messages; }, [messages]);

  // #50 round-3 repair: fires prompt-suggestion generation once React has
  // actually committed `completedTranscript` (set from inside the "result"
  // event's setMessages updater in submitPrompt, below) -- a deterministic
  // post-commit effect keyed to the completed turn, never a same-tick read of
  // a value whose write-timing setState does not guarantee. Runs at most once
  // per turn: it clears the slot immediately so a later unrelated `messages`
  // change (e.g. the activity-feed poller above) can never re-trigger it.
  useEffect(() => {
    if (completedTranscript === null) return;
    const snapshot = completedTranscript;
    setCompletedTranscript(null);
    if (!callModelRef.current) return;
    void executePromptSuggestion({
      messages:   adaptSessionMessagesForSuggestion(snapshot),
      getAppState: () => ({} as AppState),
      setAppState: (updater) => {
        const next = updater({} as AppState);
        // executePromptSuggestion casts the state to `any` when writing
        // currentSuggestion; extract it safely via unknown.
        const sugg = (next as unknown as Record<string, unknown>)["currentSuggestion"];
        if (typeof sugg === "string") setCurrentSuggestion(sugg);
        else if (sugg === null)        setCurrentSuggestion(null);
      },
      forkedAgentExecutor: makeSuggestionExecutor(callModelRef.current),
    });
  }, [completedTranscript]);

  // #561/#565: boardSummary/dataRoot no longer need syncing INTO a messages[0] welcome entry --
  // the banner region (render tree below) reads this component-scope state directly.

  // as any: SessionMessage[] is a local type; buildMessageLookups expects
  // Message[] from the not-yet-built types/message-types.ts — genuine interop cast.
  const lookups = useMemo(
    () => buildMessageLookups(messages as any),  // eslint-disable-line @typescript-eslint/no-explicit-any
    [messages],
  );

  // System prompt — reassembled when config or integrations change
  const systemPrompt = assembleSystemPrompt({
    base:        config.baseSystemPrompt,
    override:    config.systemPromptOverride,
    outputStyle: outputStyles?.activeStylePrompt ?? undefined,
    ideContext:  ideIntegration?.context         ?? undefined,
  });
  const systemPromptRef       = useRef(systemPrompt);
  systemPromptRef.current      = systemPrompt;

  // Terminal title + analytics on mount / unmount
  useEffect(() => {
    if (writeTitle) {
      process.stdout.write(`\x1b]2;ember — ${config.model}\x07`);
    }
    analytics?.log(ANALYTICS_SESSION_START, {
      model:          config.model,
      permissionMode: permModeRef.current,
    });
    return () => {
      const duration = Date.now() - mountRef.current;
      analytics?.log(ANALYTICS_SESSION_END, { duration });
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // #303: Load board summary on mount. EMBER_GOALFORGE_ROOT must be set to point at the
  // live tree (not cwd-relative, to avoid reading stale data from a deployment copy).
  useEffect(() => {
    const loadBoardData = async () => {
      try {
        const root = process.env.EMBER_GOALFORGE_ROOT || cwd;
        setDataRoot(root);
        const worldState = await buildEmberWorldState({ goalforgeRoot: root });
        if (worldState) {
          const topAttention = worldState.monitor.conditions
            .filter((c) => c.detail.startsWith("RED"))
            .slice(0, 3)
            .map((c) => c.label);
          const summary: BoardSummary = {
            green:        worldState.monitor.green,
            total:        worldState.monitor.total,
            pctComplete:  worldState.monitor.pctComplete,
            topAttention,
            boardTs:      worldState.monitor.boardTs,
            // #447: folded in at construction (not a separate merge-effect) so the event is
            // present the FIRST time boardSummary becomes defined, regardless of this async
            // load's timing relative to the mount-time cockpitRestartEvent computation above.
            cockpitRestartEvent: cockpitRestartEvent ?? undefined,
            heartbeatWriterInert: heartbeatWriterInert ?? undefined,
          };
          setBoardSummary(summary);
        }
      } catch {
        // Fail open: if board load fails, render without board summary (the honest "no recent activity" state).
        // The data root indicator will still show which tree we tried to read from.
      }
    };
    void loadBoardData();
  }, [cwd]); // eslint-disable-line react-hooks/exhaustive-deps

  // #420: live boardTs refresh -- the mount-time load above reads the board receipt exactly
  // once, so a NEW receipt landing while the cockpit keeps running was never picked up (badge
  // aged against a receipt that was no longer newest). Polls the same receipts-totality dir on a
  // slow cadence and merges a fresh boardTs into boardSummary the moment one lands; the existing
  // #413 per-second liveness tick then carries it into the rendered welcome message on its own
  // next tick -- no new render timer, no remount.
  // #433 rides the SAME poll: `events` carries one formatted line per board condition transition
  // (GREEN<->RED) detected since the previous poll -- merged into boardSummary.recentTransitions
  // below, rendered by logo-homescreen.ts's recentFeedEntries.
  const { boardTs: polledBoardTs, events: boardTransitionEvents } = useBoardTsPoller(
    process.env.EMBER_GOALFORGE_ROOT || cwd,
  );
  useEffect(() => {
    if (!polledBoardTs) return;
    setBoardSummary((prev) =>
      prev && prev.boardTs !== polledBoardTs ? { ...prev, boardTs: polledBoardTs } : prev,
    );
  }, [polledBoardTs]);
  useEffect(() => {
    if (boardTransitionEvents.length === 0) return;
    setBoardSummary((prev) =>
      prev ? { ...prev, recentTransitions: boardTransitionEvents } : prev,
    );
  }, [boardTransitionEvents]);

  // #447: live-state strip -- GPU state (nvidia-smi), the newest active-run's progress-file
  // phase, and the last-receipt-landing age. Each poller is independent (its own cadence, its
  // own fail-open contract); merged into boardSummary.liveTelemetry on whichever poller's OWN
  // state actually changed (each hook only calls its setState on a genuine poll tick, so this
  // effect fires on that same cadence, never on every render -- same discipline as the
  // boardTs/events merges above).
  const receiptsRoot = path.join(process.env.EMBER_GOALFORGE_ROOT || cwd, "receipts");
  const gpuState   = useGpuStatePoller();
  // Host telemetry needs no run in flight — it binds the right panel's six resting curves.
  // VRAM/GPU route from the gpuState poller above; a second nvidia-smi reader is a defect.
  const hostTelemetry = useHostTelemetryPoller(gpuState);
  const activeRun  = useActiveRunPoller(receiptsRoot);
  const receiptLanding = useReceiptLandingPoller(receiptsRoot);
  useEffect(() => {
    const gpuLine         = formatGpuStateLine(gpuState, isActiveRunFresh(activeRun)) ?? undefined;
    const activeRunLine    = formatActiveRunLine(activeRun) ?? undefined;
    const lastReceiptLine  = formatLastReceiptLine(receiptLanding) ?? undefined;
    setBoardSummary((prev) =>
      prev
        ? { ...prev, liveTelemetry: { gpu: gpuLine, activeRun: activeRunLine, lastReceipt: lastReceiptLine } }
        : prev,
    );
  }, [gpuState, activeRun, receiptLanding]);

  // Dialog state
  const dialogState: DialogState = {
    permissionQueue: permQueue,
    idleReturn,
    costThreshold,
    promptDialog,
  };
  const activeDialog = selectActiveDialog(dialogState);

  // Stable callbacks for status-bar controls
  const handlePermCycle       = useCallback(
    () => setPermMode((m) => cycleReplPermissionMode(m)),
    [],
  );
  const handleTaskPanelToggle = useCallback(
    () => setTaskPanelVisible((v) => toggleTaskPanel(v)),
    [],
  );
  // Status-bar prop shapes
  const sbMode: "bypass" | "regular"   = permMode === "bypass" ? "bypass" : "regular";
  const permModeState: PermissionModeState = { mode: sbMode, cycle: handlePermCycle };
  const taskPanelState: TaskPanelState     = {
    visible: taskPanelVisible,
    toggle:  handleTaskPanelToggle,
    tasks,
  };

  // Live inference metrics — polled from local model server every 2s; null when unreachable.
  const modelMetrics = useModelMetricsPoller();

  // issue #239: circuit-breaker degraded banner — {active:false} whenever the
  // model endpoint is healthy (or no guarded client has been wired yet).
  const degradedBanner = useCircuitBreakerBanner();

  // issue #239 final acceptance clause: last-successful-model-roundtrip age,
  // shown regardless of circuit state — distinguishes a wedge from idle-healthy.
  const roundtripAge = useRoundtripAge();

  // issue #475: planned-outage status banner — {active:false} whenever
  // tools/ember-cli/state/planned-outage.json is absent, expired, or malformed. Explains WHY
  // the model may be unreachable (a planned watchdog-honored maintenance window) so it is
  // never confused with an actual crash.
  const outageBanner = useOutageBanner();

  // Command registry state must be declared before renderMessage reads it. Keeping the state below
  // the callback made the obvious dependency fix read a lexical binding before initialization.
  const [slashCommands, setSlashCommands] = useState<RegistryCommand[]>([]);

  // Render dispatch (memoised per lookups + viewport width)
  const renderMessage = useCallback(
    (msg: SessionMessage) =>
      renderMsgDispatch(msg, lookups as MessageLookups, terminalCols, slashCommands),
    [lookups, terminalCols, slashCommands],
  );

  // Transcript region
  const transcriptViewportRows = Math.max(1, terminalRows - 3);
  const transcript = useVirtualScroll
    ? React.createElement(VirtualMessageList, {
        messages,
        renderMessage,
        viewportRows: transcriptViewportRows,
      })
    : React.createElement(
        Box,
        { key: "all-messages", flexDirection: "column" },
        ...messages.map(renderMessage),
      );

  // Dialog overlay
  let dialogOverlay: React.ReactElement | null = null;
  if (activeDialog === "idle-return") {
    dialogOverlay = React.createElement(IdleReturnDialog, {
      key:                "idle-return",
      completedTaskCount: idleTaskCount,
      onContinue:         () => setIdleReturn(false),
    });
  } else if (activeDialog === "cost-threshold") {
    dialogOverlay = React.createElement(CostDialog, {
      key:        "cost-threshold",
      usage:      { current: 0, limit: 0 },
      onContinue: () => setCostThreshold(false),
      onStop:     () => { setCostThreshold(false); _onExit?.(); },
    });
  }

  // Prompt input hook.
  //
  // R2b P1 repair: keyboard authority is EXCLUSIVE, and the only mechanism that makes it exclusive
  // is `isActive` at registration. The pane owning its own branch is not enough — Ink delivers each
  // keypress to every active handler and a handler returning does not stop propagation, so while
  // the pane holds focus this hook must be switched OFF rather than merely out-competed.
  const [inputState, inputActions] = usePromptInput({
    keyboardActive: !paneFocused,
    permissionMode: permMode,
    onPermissionModeCycle: handlePermCycle,
  });

  // Latest input-buffer snapshot, readable from the injector's closures below
  // without re-constructing them on every keystroke.
  const inputStateRef = useRef(inputState);
  inputStateRef.current = inputState;

  // Slash-command completion dropdown (b22 item 1 / b23 ellipsis-clip fix). Commands load once
  // at mount; the dropdown itself is a pure function of the live input text + terminal width, so
  // it stays in sync with both typing (narrows the match list) and resize (b23's description
  // truncation re-derives its budget from `terminalCols` on every render).
  const [dropdownSelectedIndex, setDropdownSelIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getCommands(cwd).then((cmds) => { if (!cancelled) setSlashCommands(cmds); });
    return () => { cancelled = true; };
  }, [cwd]);

  const dropdownOpen    = shouldShowSlashDropdown(inputState.text);
  const dropdownMatches = dropdownOpen
    ? filterSlashCommands(slashCommands, slashQueryFrom(inputState.text))
    : [];

  // #1475: the SELECT PROCESS options derive from the SAME registry the slash palette lists,
  // and a selection only counts while its command still exists there — a registry change
  // (plugin unload, availability flip) disarms START instead of leaving it armed at a command
  // that can no longer dispatch.
  const processOptions = buildProcessOptions(slashCommands);
  const selectedProcess = processOptions.some((option) => option.name === selectedProcessState)
    ? selectedProcessState
    : undefined;
  // The outstanding confirm-only membrane offer for THIS session, read fresh each render from
  // the membrane's own store (commands/train.ts) — never parsed out of transcript text. It is
  // current by construction: the turn that mints or spends an offer ends in state updates that
  // re-render this screen.
  const processOffer = outstandingProcessOffer(sessionIdRef.current);
  // Single source of truth for what <Homescreen> is actually given -- used below both to render
  // it AND to size the palette against its real (not guessed) row count. Declared here (hoisted
  // above the JSX return) so both use sites reference the exact same object; the JSX render call
  // below reuses `homescreenProps` rather than re-literal-ing it, so they cannot drift apart.
  const homescreenProps: HomescreenProps = {
    state: {
      model:   config.model,
      cwd,
      version: process.env["EMBER_VERSION"] ?? "0.0.0",
      dataRoot: dataRoot ?? "",
    },
    viewportWidth: mainColumnWidth,
    // The real terminal height, so the panel budgets its own variable content instead of trusting
    // that a number someone measured once still holds. Passing it is what makes the budget reach
    // production at all — the component defaults to no truncation when it is absent, which is the
    // safe default and also the shape in which a "wired but never fed" boundary hides.
    viewportHeight: terminalRows,
    boardSummary,
    fireballTick,
    // The spine block resolves against the SAME registry that drives the slash palette, so a
    // command shown on the first screen is by construction a command the operator can type.
    spineCommands: slashCommands,
    // Change 3 of the spine-on-first-screen spec: the cockpit binds state to the canonical repo
    // root even when launched elsewhere (utils/repo-root.ts, issue #666). That is deliberate and
    // stays; being silent about it is what was wrong.
    launchDir: process.cwd(),
  };
  // While slash composition is active, the render below collapses every variable chrome row:
  // banner, spinner, stash/shimmer/queue/notification rows and status details. The surviving
  // prompt/status region is structurally four rows, so palette sizing has no mirrored layout math.
  const dropdownDisplay = computeSlashDropdownDisplay(
    dropdownMatches,
    dropdownSelectedIndex,
    slashDropdownMaxVisible(terminalRows, dropdownMatches.length),
  );

  // Back to the top row whenever the composed query text changes (narrows/widens the match
  // list) -- never fires on a pure Up/Down navigation, since those only touch
  // dropdownSelectedIndex, not inputState.text.
  useEffect(() => {
    setDropdownSelIndex(0);
  }, [inputState.text]);

  // Constructed once (usePromptInput's setText is referentially stable across
  // renders): the queue/inject semantics that give the keyboard priority over
  // operator-pipe lines. See services/operator-input.ts.
  const operatorInjectorRef = useRef<OperatorInjector | null>(null);
  if (!operatorInjectorRef.current) {
    operatorInjectorRef.current = new OperatorInjector({
      canInjectNow: () => inputStateRef.current.text.length === 0 && !busyRef.current,
      setText:      (t) => inputActions.setText(t),
      submit:       (text, origin) => {
        operatorReceiptsRef.current?.append("prompt_injected", text);
        inputActions.setText("");
        clearInputRefForSubmit(inputStateRef);
        void submitPromptRef.current(text, origin);
      },
    });
  }

  // Re-attempt draining the operator queue whenever the gate might have opened
  // (buffer emptied by submit or by backspacing to nothing; a busy turn ended).
  useEffect(() => {
    operatorInjectorRef.current?.flush();
  }, [inputState.text, busy]);

  // Goal-mode organ wiring (ember issue #211, live acceptance leg b): one
  // continuation engine + poke function per mounted REPL session.
  // queuedUserInput below is read LIVE on every poke, including the
  // self-chained re-pokes core/goal-continuation-wiring.ts fires internally
  // (see that file's header for why the chain needs to self-invoke rather
  // than rely on a single nested call) — from the exact same two sources the
  // operator-pipe/keyboard priority gate above already reads: the input
  // buffer (inputStateRef, this file, line ~651) and the operator queue
  // depth (OperatorInjector.queueLength, services/operator-input.ts:39-41).
  // Both count as queued user input per the current "Operator relationship"
  // and "Continuation loop" sections of docs/contracts/goal-mode-mechanism.md
  // ("Operator preemption via the operator pipe as well as the TUI").
  const goalContinuationEngineRef = useRef<GoalContinuationEngine | null>(null);
  if (!goalContinuationEngineRef.current) {
    goalContinuationEngineRef.current = createGoalContinuationEngine();
  }
  const readGoalContinuationEligibility = (): ContinuationEligibilitySignals => ({
    featureEnabled: isGoalContinuationFeatureEnabled(),
    // ember-cli's EnterPlanModeTool flips PermissionMode to 'plan' via
    // ToolUseContext.setAppState, but QueryEngine's AppState setter below is
    // still a no-op stub (#182). Preserve the disclosed false signal until
    // that pre-existing state-threading gap is repaired.
    planMode: false,
    turnActive: busyRef.current,
    queuedUserInput:
      inputStateRef.current.text.length > 0 ||
      (operatorInjectorRef.current?.queueLength ?? 0) > 0,
  });
  const pokeGoalContinuationRef = useRef<(() => void) | null>(null);
  if (!pokeGoalContinuationRef.current) {
    pokeGoalContinuationRef.current = createGoalContinuationPoke({
      engine: goalContinuationEngineRef.current,
      getStore: getGoalStore,
      getEligibilitySignals: readGoalContinuationEligibility,
      startTurn: async (prompt: string) => {
        await submitPromptRef.current(prompt, "operator");
      },
      getReceiptWriter: () => getGoalReceiptWriter(),
    });
  }

  // Issue #279: event-driven pokes remain primary, while this bounded re-arm
  // resurrects a continuation skipped by a transient busy/input race even if
  // no later external event arrives. Cleanup prevents a timer surviving the
  // mounted REPL session; the same feature kill switch suppresses every tick.
  useEffect(() => startGoalContinuationRearm({
    poke: () => pokeGoalContinuationRef.current?.(),
    shouldPoke: () => {
      const signals = readGoalContinuationEligibility();
      return (
        signals.featureEnabled &&
        !signals.planMode &&
        !signals.turnActive &&
        !signals.queuedUserInput &&
        getGoalStore().getGoal()?.status === "Active" &&
        !goalContinuationEngineRef.current?.isInFlight()
      );
    },
  }), []); // eslint-disable-line react-hooks/exhaustive-deps
  // Registers the module-level hooks commands/goal.ts's /goal command and the
  // continuation engine call into. Idempotent (safe to call repeatedly) —
  // registered once per mount and torn down on unmount so a stale closure
  // never survives a remount.
  useEffect(() => {
    setGoalSteeringInjectorProvider(() => ({
      canInjectNow: () => inputStateRef.current.text.length === 0 && !busyRef.current,
      inject: (prompt: string) => { void submitPromptRef.current(prompt, "operator"); },
    }));
    setGoalContinuationTrigger(() => pokeGoalContinuationRef.current?.());
    return () => {
      setGoalSteeringInjectorProvider(null);
      setGoalContinuationTrigger(null);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Named-pipe transport lifecycle — starts once at mount, torn down at unmount.
  // Fails open: a pipe error/warning is surfaced as a single transcript row and
  // never crashes or delays the CLI (ember #165 acceptance).
  useEffect(() => {
    const handle = startOperatorPipe(
      (line) => { operatorInjectorRef.current?.handleLine(line); },
      {
        onEvent: (event) => {
          if (event.kind === "pipe_connected") {
            operatorReceiptsRef.current?.append("pipe_connected");
          }
        },
        onWarning: (message) => {
          setMessages((prev) => [
            ...prev,
            { id: crypto.randomUUID(), type: "error", content: `[operator-pipe] ${message}` },
          ]);
        },
      },
    );
    return () => handle.stop();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Submits `text` exactly as Enter would — shared by the keyboard Enter-key
  // handler below and the operator-pipe injector (ember #165). `origin` tags
  // the echoed transcript row so a human watching the window can tell who
  // typed it; keyboard is the default and carries no tag.
  const submitPrompt = async (
    text:   string,
    origin: "keyboard" | "operator" = "keyboard",
  ): Promise<void> => {
    busyRef.current         = true;
    setBusy(true);
    spinnerStartRef.current = Date.now();
    setSpinnerElapsed(0);
    setRetryStatus({ active: false });

    // Echo slash commands distinctly (UserCommandMessage), ordinary input as
    // a chat message (UserTextMessage). parseSlashInput mirrors the dispatch's
    // own slash detection so the echo and the dispatch always agree.
    const slashParsed = parseSlashInput(text);
    if (slashParsed !== null) {
      const commandText = slashParsed.args
        ? `${slashParsed.name} ${slashParsed.args}`
        : slashParsed.name;
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), type: "command", content: commandText },
      ]);
    } else {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(), type: "user", content: text,
          ...(origin === "operator" ? { origin } : {}),
        },
      ]);
    }

    if (isExitCommandInput(text)) {
      if (origin === "operator") {
        operatorReceiptsRef.current?.append("command_completed", slashParsed!.name);
      }
      busyRef.current = false;
      setBusy(false);
      _onExit?.();
      return;
    }

    // Slash-command dispatch — execute a registered command instead of a model
    // turn. Returns null for ordinary input, which falls through to the engine.
    const slashResult = await tryDispatchSlashCommandSafely(text, {
      sessionId: sessionIdRef.current,
      mode:      String(permMode),
      cwd,
    });
    if (slashResult !== null) {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), type: "assistant", content: slashResult.message },
      ]);
      if (origin === "operator") {
        operatorReceiptsRef.current?.append("command_completed", slashParsed.name);
      }
      busyRef.current = false;
      setBusy(false);
      // ember #211 (found via live compiled-binary acceptance testing, not
      // unit tests): a slash command is a turn-exit path exactly like a model
      // round-trip -- /goal's own create handler pokes the continuation
      // engine synchronously DURING this dispatch, while busyRef.current is
      // still true, so that first poke always observes turn_active and
      // no-ops. This early `return` sits before the try/finally below (the
      // finally's poke is for the model-turn path only), so without this
      // line nothing would ever re-poke and a goal created via /goal would
      // stall forever with zero autonomous continuations.
      pokeGoalContinuationRef.current?.();
      return;
    }

    // Lazy-init the QueryEngine on first submission
    if (!engineRef.current) {
      try {
        const [siMod, btMod] = await Promise.all([
          import("../entrypoints/session-init.ts"),
          import("../tools/builtin-tools.ts"),
        ]);

        const deps      = siMod.getLoopDeps();
        callModelRef.current = deps.callModel;
        const engineCfg = {
          cwd,
          tools:              btMod.BUILTIN_TOOLS as unknown as Tool[],
          commands:           [] as unknown[],
          mcpClients:         {} as Record<string, unknown>,
          agents:             {} as Record<string, unknown>,
          canUseTool:         async (tool: Tool, input: unknown, behavior: PermissionBehavior) =>
            authorizeReplTool(permModeRef.current, tool, input, behavior),
          // #182: ExitPlanMode/EnterWorktree/ExitWorktree read state["cwd"] as
          // a fallback path to the resolved root; keep it consistent with the
          // same `cwd` this config already threads via ToolUseContext.cwd.
          getAppState:        () => ({ cwd } as Record<string, unknown>),
          setAppState:        async () => {},
          readFileCache:      new Map<string, unknown>(),
          // #157: size tool-result truncation off the server's real n_ctx
          // (siMod probed it during init via /props), not a guessed default.
          // #197: conversationMaxChars (same call) bounds the whole assembled
          // conversation, not just one result.
          toolResultBudget:   siMod.getToolResultBudget(),
          customSystemPrompt: systemPromptRef.current,
          userSpecifiedModel: config.model,
          // #197: live retry-attempt status → the status-bar effort callout,
          // never a transcript message. Cleared on the next assistant/user/
          // result event and in submitPrompt's finally, so it can't outlive
          // the request that produced it.
          onRetryAttempt: (info: RetryAttemptInfo) => {
            setRetryStatus({
              active: true,
              label: `⟳ retrying ${info.attempt}/${info.maxAttempts} in ${Math.ceil(info.delayMs / 1000)}s — ${info.reason}`,
            });
          },
        };
        engineRef.current = new QueryEngine(engineCfg, deps);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            id:      crypto.randomUUID(),
            type:    "error",
            content: `Engine init failed: ${err instanceof Error ? err.message : String(err)}`,
          },
        ]);
        busyRef.current = false;
        setBusy(false);
        // Same early-return-bypasses-finally reasoning as the slash-command
        // branch above: this turn is over (in error) before the try/finally
        // below is ever entered.
        pokeGoalContinuationRef.current?.();
        return;
      }
    }

    const abortCtrl  = new AbortController();
    abortRef.current = abortCtrl;

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, type: "assistant", content: "" },
    ]);

    // #50 round-3: whether a "result" event landed this turn (gates the
    // fallback dispatch below). Plain per-invocation flag, not read across
    // any React scheduling boundary -- safe.
    let sawResultEvent = false;

    try {
      for await (const ev of (engineRef.current as QueryEngine).submitMessage(text)) {
        if (abortCtrl.signal.aborted) break;

        const event = ev as QueryEvent;

        if (event.type === "assistant") {
          // A model response arrived -- any retry that was in flight has by
          // definition succeeded. Clear immediately rather than let a stale
          // "retrying" label linger until the finally block below.
          setRetryStatus({ active: false });
          const raw = event.message.content;
          const content = Array.isArray(raw)
            ? (raw as Array<{ type?: string; text?: string }>)
                .filter((b) => b.type === "text")
                .map((b) => b.text ?? "")
                .join("")
            : String(raw ?? "");
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content } : m)),
          );
        } else if (event.type === "user") {
          // #173: the engine's "user" event carries one ToolResultBlock per tool
          // invoked in the preceding assistant turn (parallel tool calls yield
          // several). Each block already has tool_use_id/content/is_error typed
          // and ready to render -- JSON.stringify-ing the whole array (the prior
          // behavior) dumped raw wire JSON into the transcript instead of routing
          // per-block through UserToolResultMessage's formatted card.
          const toolResultBlocks = event.message.toolUseResult ?? [];
          setMessages((prev) => [
            ...prev,
            ...toolResultBlocks.map((block) => ({
              id:          crypto.randomUUID(),
              type:        "tool_result",
              tool_use_id: block.tool_use_id,
              content:     block.content,
              is_error:    block.is_error === true,
            })),
          ]);
        } else if (event.type === "result") {
          // #157/#49: never discard the result event -- error/max_turns carry
          // the ONLY closing text the loop will ever produce for that turn.
          // #50 round-3: thread the SAME array applyResultEvent produces into
          // the dedicated `completedTranscript` state slot (never a local
          // variable read back synchronously right after this call -- see
          // that state's declaration above for why). Skipped when this turn
          // was aborted: the abort happened strictly before this branch could
          // run (the loop's own top-of-iteration check would have broken out
          // first), so this only guards the dispatch against a signal that
          // flips true during the awaits still pending below (compaction
          // read, operator-receipt check).
          sawResultEvent = true;
          const aborted = abortCtrl.signal.aborted;
          setMessages((prev) => {
            const next = applyResultEvent(event, prev, assistantId);
            if (!aborted) setCompletedTranscript(next);
            return next;
          });
          break;
        }
      }

      // Operator-session receipt (ember #165 acceptance): the response for an
      // operator-injected prompt has finished rendering into the transcript.
      // Only record when the message is truly complete (stop_reason is set, meaning
      // streaming/thinking is done), not on first delta (thinking preamble).
      if (origin === "operator" && !abortCtrl.signal.aborted) {
        const finalMsg = messagesRef.current.find((m) => m.id === assistantId);
        if (finalMsg && finalMsg["stop_reason"] !== undefined) {
          operatorReceiptsRef.current?.append("response_rendered", assistantId);
        }
      }

      // Surface compaction feedback: the engine sets a one-shot post-
      // compaction flag (markPostCompaction) when autocompact ran during
      // this turn. Consume it and render the completion indicator so the
      // user sees the conversation was compacted — closes the dead-feature
      // gap where the flag was set but never read and the progress
      // component was never mounted.
      const compactedElapsed = consumePostCompaction();
      if (compactedElapsed !== null) {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            type: "compaction",
            isComplete: true,
            elapsedSecs: compactedElapsed,
          },
        ]);
      }

      // #50 round-3: the primary dispatch now happens from the
      // `completedTranscript`-keyed effect above (fired once React commits
      // that state, never from a same-tick read here). This is only the
      // fallback for the one case that effect can never cover: no "result"
      // event arrived this turn at all (stream ended some other way), so
      // `completedTranscript` was never set. messagesRef.current's usual
      // one-render lag is immaterial here -- by this point in the function
      // several awaited turn-exit steps (operator receipt, compaction) have
      // already run, so any pending render/effect flush from this turn's own
      // last setMessages call has long since committed.
      if (!sawResultEvent && !abortCtrl.signal.aborted && callModelRef.current) {
        void executePromptSuggestion({
          messages:   adaptSessionMessagesForSuggestion(messagesRef.current),
          getAppState: () => ({} as AppState),
          setAppState: (updater) => {
            const next = updater({} as AppState);
            // executePromptSuggestion casts the state to `any` when writing
            // currentSuggestion; extract it safely via unknown.
            const sugg = (next as unknown as Record<string, unknown>)["currentSuggestion"];
            if (typeof sugg === "string") setCurrentSuggestion(sugg);
            else if (sugg === null)        setCurrentSuggestion(null);
          },
          forkedAgentExecutor: makeSuggestionExecutor(callModelRef.current),
        });
      }
    } finally {
      abortRef.current = null;
      busyRef.current  = false;
      setBusy(false);
      // issue #197: unconditional backstop -- every turn-exit path (success,
      // terminal error, abort, thrown exception) clears the retry callout, so
      // it can never survive past the request it described.
      setRetryStatus({ active: false });
      // ember #211: every turn-exit path also pokes the goal continuation
      // engine (the current "Continuation loop" section: "every task/turn
      // completion pokes maybe-continue-
      // if-idle"). Whenever THIS submitPrompt call was itself invoked as the
      // engine's own startTurn callback, this poke arrives while that outer
      // call's semaphore is still held and harmlessly no-ops
      // ({fired:false, reason:"already_in_flight"}) -- the chain still
      // continues correctly via the outer call's own self-re-invocation once
      // its semaphore genuinely releases (core/goal-continuation-wiring.ts).
      pokeGoalContinuationRef.current?.();
    }
  };
  submitPromptRef.current = submitPrompt;

  // issue #283: flush a queued Enter-while-busy submission the instant busy
  // flips false -- the queue is cleared BEFORE the async submitPrompt call so
  // a fresh in-flight turn (started by submitPrompt itself) never re-reads a
  // stale queued value.
  useEffect(() => {
    if (busy) return;
    const queued = pendingSubmitRef.current;
    if (queued === null) return;
    pendingSubmitRef.current = null;
    void submitPromptRef.current?.(queued, "keyboard");
  }, [busy]);

  // Main keyboard handler
  useInput((input, key) => {
    // R2b -- ORDER INVARIANT (frozen spec): whether a text input has focus is decided FIRST,
    // before any accelerator/traversal dispatch is even considered. `paneFocused` IS that
    // decision (there is exactly one focus target in this app, so "operator surface focused"
    // and "no text input active" are the same boolean) -- when true this branch owns the
    // keystroke completely and NEVER falls through to the prompt-typing code below. An
    // accelerator that also inserted itself into the prompt, or vice versa, would be exactly the
    // "lenient outcome reachable before the strict check" defect this ordering exists to forbid.
    if (paneFocused) {
      const { status, runId } = operatorControlStatus(telemetry);
      const enabledMask = OPERATOR_CONTROL_ACTIONS.map((action) =>
        isOperatorControlEnabled(action, status, telemetry, selectedProcess),
      );

      // Escape always returns focus to the prompt, from anywhere in the set.
      if (key.escape) {
        setPaneFocused(false);
        setControlDisabledReason(undefined);
        return;
      }

      // Traversal: Tab / RightArrow forward, Shift+Tab / LeftArrow backward. Disabled controls
      // are skipped (acceptance row 6); running off either end LEAVES the set back to the prompt
      // (acceptance row 1: "visits all four ... then leaves the set") -- traversal order is
      // always OPERATOR_CONTROL_ACTIONS' own canonical order, never the wrapped-row visual
      // grouping, so a narrow pane reflowing controls into multiple rows can never break it
      // (conjunction row C1).
      const forward = (key.tab && !key.shift) || key.rightArrow;
      const backward = (key.tab && key.shift) || key.leftArrow;
      if (forward || backward) {
        setControlDisabledReason(undefined);
        const next = nextOperatorFocusIndex(focusedControlIndex, forward ? 1 : -1, enabledMask);
        if (next === null) {
          setPaneFocused(false);
          return;
        }
        setFocusedControlIndex(next);
        return;
      }

      // Activation: Enter or Space fires the focused control (rows 2/3 -- identical outcome).
      if (key.return || input === " ") {
        const action = OPERATOR_CONTROL_ACTIONS[focusedControlIndex];
        if (action && enabledMask[focusedControlIndex]) {
          setControlDisabledReason(undefined);
          handleOperatorControl(action, runId);
        } else if (action) {
          setControlDisabledReason(operatorControlDisabledReason(action));
        }
        return;
      }

      // Any other key while the pane is focused is swallowed here -- it must never reach the
      // prompt-typing code below.
      return;
    }

    // Slash-command dropdown navigation takes priority over every other binding while it's open
    // (b22 item 1). Enter completes a partial command (or a command that still needs arguments),
    // but an exact argument-free registered command must fall through to the ordinary submit
    // path so its first Enter dispatches exactly once (#1369 acceptance amendment).
    if (dropdownOpen && dropdownDisplay.visible.length > 0) {
      // 2026-07-25 palette-overflow-render finding: wrap over the FULL match list
      // (dropdownMatches), not the visible-cap slice -- computeSlashDropdownDisplay now scrolls
      // its window to follow the selection, so an entry beyond the visible cap is reachable by
      // continuing to press Down instead of being permanently hidden.
      if (key.downArrow) {
        setDropdownSelIndex((i) => moveDropdownSelection(i, dropdownMatches.length, 1));
        return;
      }
      if (key.upArrow) {
        setDropdownSelIndex((i) => moveDropdownSelection(i, dropdownMatches.length, -1));
        return;
      }
      if (key.return) {
        const chosen = dropdownDisplay.visible[dropdownDisplay.selectedIndex];
        if (!chosen) return;
        const liveCommand = inputActions.getSnapshot().text.trim();
        const exactCommand = findCommand(slashQueryFrom(liveCommand), dropdownMatches);
        const isExactArgumentFreeCommand = exactCommand !== undefined && !exactCommand.argumentHint;
        if (!isExactArgumentFreeCommand) {
          inputActions.setText(completeSlashSelection(chosen));
          return;
        }
      }
    }

    // Submit on Enter
    if (!key.shift && key.tab) {
      // Accept the current ghost suggestion into the input.
      if (currentSuggestion && !busyRef.current) {
        inputActions.setText(currentSuggestion);
        setCurrentSuggestion(null);
        return;
      }
      // R2b: with no suggestion to accept, Tab moves keyboard focus onto the operator
      // controls -- entering at the first ENABLED control (never a disabled one, when at least
      // one control is enabled) so the visible focus indicator never opens on a dead control.
      // Guarded on !dropdownOpen so composing a slash command is never interrupted mid-type.
      if (!dropdownOpen) {
        const { status } = operatorControlStatus(telemetry);
        const enabledMask = OPERATOR_CONTROL_ACTIONS.map((action) =>
          isOperatorControlEnabled(action, status, telemetry, selectedProcess),
        );
        const entryIndex = nextOperatorFocusIndex(-1, 1, enabledMask);
        setFocusedControlIndex(entryIndex ?? 0);
        setPaneFocused(true);
      }
      return;
    }

    if (key.return) {
      // issue #251: read the synchronous live snapshot, not `inputState.text` -- the latter is
      // React-state-derived and reflects only the last completed render, which a same-tick
      // Enter (delivered in the same terminal write() burst as the characters before it) reads
      // as stale/empty, silently dropping the whole submission. getSnapshot() is always current.
      const live = inputActions.getSnapshot();
      if (!live.text.trim()) return;
      const text = live.text;
      inputActions.setText("");
      clearInputRefForSubmit(inputStateRef);
      clearCommandBarNotice();
      // Clear any pending suggestion when the user submits.
      setCurrentSuggestion(null);
      if (busyRef.current) {
        // issue #283: preempt, don't drop -- queue for submission the moment
        // the current turn goes idle (flushed by the useEffect above).
        pendingSubmitRef.current = text;
        return;
      }
      void submitPrompt(text, "keyboard");
      return;
    }

    // Ctrl+C: abort in-flight request, or exit
    if (key.ctrl && input === "c") {
      if (busyRef.current) {
        abortRef.current?.abort();
      } else {
        _onExit?.();
      }
      return;
    }

    // Backspace / delete
    if (key.backspace) {
      clearCommandBarNotice();
      inputActions.deleteBackward();
      return;
    }
    if (key.delete) {
      clearCommandBarNotice();
      inputActions.deleteForward();
      return;
    }

    // Regular character input — clears ghost suggestion on first keystroke.
    if (input && !key.ctrl && !key.meta && !key.alt) {
      if (currentSuggestion) setCurrentSuggestion(null);
      clearCommandBarNotice();
      inputActions.insertText(input);
    }
  });

  // ---------------------------------------------------------------------------
  // #1370 — command-button activation
  // ---------------------------------------------------------------------------

  /**
   * Turns a command-button click into exactly what typing would have done, and nothing more.
   *
   *  - `dispatch` goes through the SAME OperatorInjector the operator pipe uses, so the click
   *    inherits its keyboard-priority gate for free: with half-typed text in the composer or a
   *    turn in flight, the command is QUEUED rather than clobbering what is being typed.
   *  - `prefill` writes `/name ` into an EMPTY composer only. With text already there, the
   *    usage line is surfaced instead — a button click is never allowed to destroy typing.
   *  - `rejected` surfaces the disabled command's named reason.
   *
   * No branch touches `paneFocused` or `focusedControlIndex`: clicking a command button cannot
   * move keyboard focus, which is what keeps these buttons equivalents of the keyboard path
   * rather than a replacement for it.
   */
  const handleCommandButton = (activation: CommandButtonActivation): void => {
    if (activation.kind === "rejected") {
      setCommandBarNotice(activation.reason);
      return;
    }
    if (activation.kind === "prefill") {
      const usage = activation.hint ? `usage: ${activation.hint}` : `${activation.text.trim()} needs arguments`;
      if (inputStateRef.current.text.trim().length > 0) {
        setCommandBarNotice(usage);
        return;
      }
      inputActions.setText(activation.text);
      setCommandBarNotice(usage);
      return;
    }
    const outcome = operatorInjectorRef.current?.handleLine(activation.text);
    setCommandBarNotice(
      outcome === "queued" ? `${activation.text} queued behind the current input` : undefined,
    );
  };

  // #1475: START's activation — the selected process, through the IDENTICAL path a command
  // button click takes (handleCommandButton -> OperatorInjector -> submitPrompt -> the slash
  // dispatcher). No second dispatch path: START on train IS "/train", and START on an offered
  // train IS the "/train confirm <id>" the offer surfaced, so the membrane's own validation
  // decides exactly as it does for typed input. A rejected activation (nothing selected, or a
  // disabled command) surfaces its named reason on the controls' own reason row. Assigned every
  // render so the closure always sees the LIVE selection/offer (see activateStartRef's
  // declaration next to handleOperatorControl).
  const surfaceControlRefusal = (action: OperatorControlAction, detail: string): void => {
    const receiptPath = operatorReceiptsRef.current?.filePath ?? "operator receipt unavailable";
    operatorReceiptsRef.current?.append("control_refused", JSON.stringify({ action, detail }));
    setControlNotice((current) => updateOperatorControlNotice(current, { action, detail, receiptPath }));
  };

  const launchAuthorityRunSpecPath = env["EMBER_RUN_SPEC_PATH"] ?? (() => {
    try {
      return path.join(
        resolveEmberRepoRoot({ startDir: cwd, envRepoRoot: env["EMBER_REPO_ROOT"] }),
        "receipts", "ember-02-launch-authority", "run-spec.json",
      );
    } catch {
      // The read below remains fail-closed and surfaces the exact attempted path.
      return path.join(cwd, "receipts", "ember-02-launch-authority", "run-spec.json");
    }
  })();

  const openControlDialog = (action: OperatorControlAction, runId?: string): void => {
    const startReview = action === "START"
      ? captureStartReview(
          processOptions.find((option) => option.name === selectedProcess),
          processOffer,
          launchAuthorityRunSpecPath,
        )
      : undefined;
    if (startReview?.kind === "rejected") {
      surfaceControlRefusal(action, startReview.reason);
      return;
    }
    const runSpecPath = startReview?.runSpecPath ?? launchAuthorityRunSpecPath;
    let parsed;
    try {
      parsed = parseLaunchAuthorityParameters(fs.readFileSync(runSpecPath, "utf8"));
    } catch (error) {
      surfaceControlRefusal(action, `launch-authority run-spec unreadable: ${error instanceof Error ? error.message : String(error)}`);
      return;
    }
    if (!parsed.ok) {
      surfaceControlRefusal(action, parsed.reason);
      return;
    }
    // START names the prospective authority run, not any historical run still plotted in the
    // pane. State-changing controls must instead match the exact live run they will mutate.
    if (action !== "START" && runId !== undefined && parsed.parameters.runId !== runId) {
      surfaceControlRefusal(action, `run identity mismatch: live=${runId} authority=${parsed.parameters.runId}`);
      return;
    }
    setControlDisabledReason(undefined);
    setControlNotice(undefined);
    setControlDialog({
      action,
      runId: action === "START" ? parsed.parameters.runId : runId,
      parameters: parsed.parameters,
      sourcePath: runSpecPath,
      ...(startReview ? { activation: startReview.activation } : {}),
    });
  };
  openControlDialogRef.current = openControlDialog;

  const confirmControlDialog = async (parameters: StartParameters): Promise<void> => {
    const pending = controlDialog;
    if (!pending) return;
    operatorReceiptsRef.current?.append("control_confirmed", JSON.stringify({
      action: pending.action,
      runId: pending.runId ?? parameters.runId,
      parameters,
      runSpec: pending.sourcePath,
      ...(pending.activation ? { activation: pending.activation } : {}),
    }));
    setControlDialog(undefined);
    if (pending.action === "START") {
      if (!pending.activation) {
        surfaceControlRefusal("START", "launch review did not capture an activation");
        return;
      }
      handleCommandButton(pending.activation);
      return;
    }
    try {
      const result = await driveOperatorControl(pending.action, pending.runId, {
        channelPath: operatorControlChannelPath,
      });
      if (!result.ok) surfaceControlRefusal(pending.action, result.error ?? "control command refused");
    } catch (error) {
      surfaceControlRefusal(pending.action, error instanceof Error ? error.message : String(error));
    }
  };

  activateStartRef.current = () => {
    const selected = processOptions.find((option) => option.name === selectedProcess);
    const activation = startActivation(selected, processOffer);
    if (activation.kind === "rejected") {
      setControlDisabledReason(activation.reason);
      return;
    }
    setControlDisabledReason(undefined);
    handleCommandButton(activation);
  };

  /**
   * Drops the notice row the moment the operator acts on it. Every notice describes a command the
   * operator was ABOUT to run; once they are typing or have submitted, it describes the past, and
   * a stale usage line permanently costs a row of chrome while telling them something untrue.
   * Bails out when there is nothing to clear so ordinary typing never forces a render.
   */
  const clearCommandBarNotice = (): void => {
    setCommandBarNotice((current) => (current === undefined ? current : undefined));
  };

  // The page index the bar renders, valid only for the layout it was chosen under: a narrower
  // terminal or a changed registry repacks the pages, and a page-3 index remembered across that
  // change points at commands that are no longer there.
  // The bar now lives inside the operator surface (#1399), so its layout signature is keyed on
  // THAT pane's inner content width — the operator surface reserves its border and paddingX, four
  // columns in total. Keying on the transcript column would let a resize that changes only the
  // transcript discard a still-valid page, and worse, let a resize that changes only the pane keep
  // a stale one.
  const commandBarSignature = `${Math.max(1, paneWidth - 4)}:${commandBarMaxRows(terminalRows)}:${slashCommands
    .map((command) => command.name)
    .join(",")}`;
  const commandBarPageIndex =
    commandBarPageState.signature === commandBarSignature ? commandBarPageState.index : 0;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return React.createElement(
    Box,
    { flexDirection: "row", width: terminalCols, height: terminalRows, overflow: "hidden" },
    React.createElement(
      Box,
      { key: "main-column", flexDirection: "column", width: mainColumnWidth, minWidth: mainColumnWidth, height: terminalRows, flexShrink: 0, overflow: "hidden" },
      React.createElement(
        Box,
        { key: "banner", flexShrink: 1, minHeight: 0, overflow: "hidden" },
        React.createElement(Homescreen, homescreenProps),
      ),
      React.createElement(
        Box,
        { key: "workspace", flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" },
        React.createElement(
          Box,
          { key: "transcript", flexDirection: "column", flexGrow: 1, minWidth: 0, minHeight: 0, overflow: "hidden", justifyContent: transcriptViewportJustifyContent(useVirtualScroll, messages) },
          transcript,
        ),
      ),
      dialogOverlay,
      busy && !dropdownOpen
        ? React.createElement(SpinnerAnimationRow, {
            key:         "spinner",
            elapsedMs:   spinnerElapsed,
            startedAtMs: spinnerStartRef.current,
          })
        : null,
      dropdownOpen && slashDropdownCanRender(terminalRows, dropdownMatches.length)
        ? React.createElement(SlashDropdown, {
            key:           "slash-dropdown",
            commands:      dropdownDisplay.visible,
            selectedIndex: dropdownDisplay.selectedIndex,
            overflowCount: dropdownDisplay.overflowCount,
            width:         mainColumnWidth,
          })
        : null,
      React.createElement(PromptInput, {
        key:            "input",
        state:          inputState,
        isProcessing:   busy,
        compact:        dropdownOpen,
        showStatusLine: false,
        suggestion:     currentSuggestion ?? undefined,
        width:          mainColumnWidth,
        statusLine: React.createElement(StatusLine, {
          permissionMode: permModeState,
          taskPanel:      taskPanelState,
          telemetry,
          modelMetrics:   modelMetrics ?? undefined,
          modelSeat: liveModelSeat,
          effort:         retryStatus,
          degraded:       degradedBanner,
          outage:         outageBanner,
          pollFailures:   pollFailureStatuses,
          roundtripAge,
          compact:         dropdownOpen,
          // Legibility bar (2026-07-26): without this the bar row had no way to know it was
          // about to overflow mainColumnWidth — see status-bar.ts's fitStatusBarLine.
          width:           mainColumnWidth,
        }),
      }),
    ),
    React.createElement(OperatorSurfacePane, {
      key: "operator-surface",
      telemetry,
      host: hostTelemetry,
      activityLines: getActivityFeedState().recentLines,
      sourceIdentity,
      width: paneWidth,
      height: terminalRows,
      terminalColumns: terminalCols,
      terminalRows,
      onControl: handleOperatorControl,
      onControlOpen: openControlDialog,
      controlDialogOpen: controlDialog !== undefined,
      controlDialogAction: controlDialog?.action,
      controlDialogParameters: controlDialog?.parameters,
      controlDialogSourcePath: controlDialog?.sourcePath,
      onControlConfirm: (parameters) => { void confirmControlDialog(parameters); },
      onControlCancel: () => { setControlDialog(undefined); setControlDisabledReason(undefined); },
      focusedControlIndex: paneFocused ? focusedControlIndex : undefined,
      disabledActionReason: controlNotice?.line ?? controlDisabledReason,
      hoveredControl,
      onControlHover: setHoveredControl,
      activityScrollOffset,
      onActivityScroll: (deltaY) => setActivityScrollOffset((value) => Math.max(0, value + (deltaY < 0 ? 1 : -1))),
      // #1370's clickable equivalent of every registered slash command, rehomed by #1399 next to
      // the run controls the operator already reaches for. It is NOT suppressed while the slash
      // palette is open: the palette owns rows in the transcript column, so there is no longer a
      // row conflict, and blanking a whole block of the live-run pane every time a `/` is typed
      // would reflow the charts underneath it on every keystroke.
      commands: slashCommands,
      commandBarMaxRows: commandBarMaxRows(terminalRows),
      hoveredCommand,
      onHoverCommand: setHoveredCommand,
      onCommandActivate: handleCommandButton,
      commandPage: commandBarPageIndex,
      onCommandPageChange: (index: number) =>
        setCommandBarPageState({ signature: commandBarSignature, index }),
      commandNotice: commandBarNotice,
      // #1475: the click-first SELECT PROCESS run control. Selecting arms START and closes the
      // dialog; the stale reason row clears because the operator just did the thing it asked.
      selectedProcess,
      processMenuOpen,
      processMenuPage,
      onProcessMenuToggle: () => setProcessMenuOpen((open) => !open),
      onProcessSelect: (name: string) => {
        setSelectedProcess(name);
        setProcessMenuOpen(false);
        setProcessMenuPage(0);
        setControlDisabledReason(undefined);
      },
      onProcessMenuPageChange: setProcessMenuPage,
      processOffer,
      hoveredProcess,
      onHoverProcess: setHoveredProcess,
    }),
  );
}
