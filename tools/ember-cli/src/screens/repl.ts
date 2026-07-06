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
  type InterruptHandler,
  type TaskPanelState,
  type Task,
  type EffortCalloutState,
} from "../components/status-bar.ts";
import {
  PromptInput,
  usePromptInput,
  parseInputMode,
} from "../components/prompt-input.ts";
import { IdleReturnDialog, CostDialog } from "../components/dialogs.ts";
import { Homescreen }                   from "../components/logo-homescreen.ts";
import { SlashDropdown }                from "../components/slash-dropdown.ts";
import {
  shouldShowSlashDropdown,
  slashQueryFrom,
  filterSlashCommands,
  moveDropdownSelection,
  completeSlashSelection,
  computeSlashDropdownDisplay,
} from "../services/slash-dropdown.ts";
import { getCommands } from "../command-registry.ts";
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
  SpinnerAnimationRow,
  ANIMATION_LOOP_MS,
}                                        from "../components/spinner.ts";
import { QueryEngine, type QueryEvent, type ResultEvent, type RetryAttemptInfo } from "../core/query-engine.ts";
import type { Tool }                    from "../core/tool-interface.ts";
import {
  getState,
  startTelemetryWatch,
  type TelemetryState,
}                                        from "../services/telemetry-watch.ts";
import { useModelMetricsPoller }         from "../services/model-metrics-poller.ts";
import { useCircuitBreakerBanner }       from "../services/circuit-breaker-banner-poller.ts";
import {
  executePromptSuggestion,
  makeSuggestionExecutor,
} from "../services/prompt-suggestion.ts";
import type { AppState } from "../state/app-state.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";
import { tryDispatchSlashCommand, parseSlashInput } from "../services/slash-dispatch.ts";
import { consumePostCompaction } from "../session-state.ts";
import { OperatorInjector } from "../services/operator-input.ts";
import { startOperatorPipe } from "../services/operator-pipe.ts";
import {
  createOperatorReceiptWriter,
  type OperatorReceiptWriter,
} from "../services/operator-receipts.ts";
import { createGoalContinuationEngine, type GoalContinuationEngine } from "../core/goal-continuation.ts";
import { getGoalStore, getGoalReceiptWriter } from "../core/goal-runtime.ts";
import {
  createGoalContinuationPoke,
  isGoalContinuationFeatureEnabled,
} from "../core/goal-continuation-wiring.ts";
import { setGoalSteeringInjectorProvider, setGoalContinuationTrigger } from "../commands/goal.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export type ReplPermissionMode = "bypass" | "interactive" | "swarm-worker";

export const REPL_PERMISSION_CYCLE: ReplPermissionMode[] = [
  "bypass",
  "interactive",
  "swarm-worker",
];

export const COMPACTION_TOKEN_THRESHOLD = 180_000;
export const COMPACTION_INDICATOR_TEXT  = "Razzle-dazzling...";
export const ANALYTICS_SESSION_START    = "ember_repl_session_start";
export const ANALYTICS_SESSION_END      = "ember_repl_session_end";

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
  env?:            NodeJS.ProcessEnv;
  analytics?:      { log: (event: string, props?: Record<string, unknown>) => void };
  ideIntegration?: { context?: string };
  outputStyles?:   { activeStylePrompt?: string };
  session?:        unknown;
  onExit?:         () => void;
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

export function shouldShowMessageActions(env: NodeJS.ProcessEnv = process.env): boolean {
  return !env["EMBER_DISABLE_MESSAGE_ACTIONS"];
}

export function cycleReplPermissionMode(current: ReplPermissionMode): ReplPermissionMode {
  const idx  = REPL_PERMISSION_CYCLE.indexOf(current);
  const next = REPL_PERMISSION_CYCLE[(idx + 1) % REPL_PERMISSION_CYCLE.length];
  return next ?? "bypass";
}

/**
 * B7 item 2 ("kill the void", operator regrade 2026-07-03): bottom-anchors (flex-end) a
 * sparse/in-session transcript's content toward the prompt, unchanged from the existing
 * behavior. B7 item 2 regrade ("welcome void dominance", 2026-07-03): a FRESH BOOT (welcome
 * panel only, no conversation entry yet) instead top-anchors (flex-start) -- this flips the
 * moment a real turn lands, and is one-way for the session: no scenario removes a landed entry.
 */
export function transcriptJustifyContent(messages: SessionMessage[]): "flex-start" | "flex-end" {
  const isWelcomeOnly = messages.length > 0 && messages.every((m) => m.type === "welcome");
  return isWelcomeOnly ? "flex-start" : "flex-end";
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

function _telemetryMemoKey(state: TelemetryState): string | null {
  const { lastGovernor, activeRun } = state;
  if (!lastGovernor && !activeRun) return null;
  const parts: string[] = [];
  if (lastGovernor) {
    parts.push(
      `VRAM ${lastGovernor.vramUsedGib.toFixed(1)}/${lastGovernor.vramTotalGib.toFixed(1)}`,
    );
  }
  if (activeRun) {
    const stepStr = activeRun.totalSteps != null
      ? `${activeRun.step}/${activeRun.totalSteps}`
      : String(activeRun.step);
    let runPart = `train r=${activeRun.runId} step ${stepStr}`;
    if (activeRun.loss != null) runPart += ` loss ${activeRun.loss.toFixed(2)}`;
    parts.push(runPart);
  }
  return `⚡ ${parts.join(" · ")}`;
}

// ---------------------------------------------------------------------------
// renderMsgDispatch — routes a SessionMessage to the correct renderer
// ---------------------------------------------------------------------------

export function renderMsgDispatch(
  msg:           SessionMessage,
  lookups:       MessageLookups,
  viewportWidth: number = 80,
): React.ReactElement {
  switch (msg.type) {
    case "welcome":
      return React.createElement(Homescreen, {
        key:   msg.id,
        state: {
          model:   String(msg["model"]   ?? ""),
          cwd:     String(msg["cwd"]     ?? ""),
          version: String(msg["version"] ?? "0.0.0"),
        },
        viewportWidth,
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
// ReplScreen — full-screen interactive REPL
// ---------------------------------------------------------------------------

export function ReplScreen({
  config,
  cwd,
  env            = process.env,
  analytics,
  ideIntegration,
  outputStyles,
  session:        _session,
  onExit:         _onExit,
}: ReplScreenProps): React.ReactElement {
  const { rows: terminalRows, columns: terminalCols } = useContext(TerminalSizeContext);

  const useVirtualScroll = shouldUseVirtualScroll(env);
  const writeTitle       = shouldWriteTerminalTitle(env);

  const [permMode,         setPermMode]        = useState<ReplPermissionMode>(config.permissionMode);
  const [taskPanelVisible, setTaskPanelVisible] = useState(false);
  const [tasks]                                 = useState<Task[]>([]);
  const [permQueue,        setPermQueue]        = useState<PermissionQueueItem[]>([]);
  const [idleReturn,       setIdleReturn]       = useState(false);
  const [idleTaskCount,    setIdleTaskCount]    = useState(0);
  const [costThreshold,    setCostThreshold]    = useState(false);
  const [promptDialog,     _setPromptDialog]    = useState(false);

  const [messages, setMessages] = useState<SessionMessage[]>([{
    id:      "welcome",
    type:    "welcome",
    content: `ember · ${config.model} · type a message and press Enter`,
    model:   config.model,
    cwd,
    version: process.env["EMBER_VERSION"] ?? "0.0.0",
  }]);

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
  const sessionIdRef = useRef<string>(crypto.randomUUID());

  // Operator input channel (ember #165 / #154) — a local named pipe the operator
  // writes prompts to alongside the keyboard. submitPromptRef always holds the
  // latest submitPrompt closure so the injector (constructed once, below, after
  // usePromptInput) never calls a stale one. One receipt-writer/JSONL file per
  // mounted session.
  const submitPromptRef = useRef<(text: string, origin?: "keyboard" | "operator") => Promise<void>>(
    async () => {},
  );
  const operatorReceiptsRef = useRef<OperatorReceiptWriter | null>(null);
  if (!operatorReceiptsRef.current) {
    operatorReceiptsRef.current = createOperatorReceiptWriter();
  }

  const [busy,           setBusy]           = useState(false);
  const busyRef                             = useRef(false);
  const [spinnerElapsed, setSpinnerElapsed] = useState(0);
  const spinnerStartRef                     = useRef(0);

  // Live retry-attempt status (issue #197 Leg 3/4) — shown via the status
  // bar's existing effort callout, NEVER as a transcript message: a retry is
  // an in-progress, ephemeral condition, not a historical record. Cleared at
  // the start of every submit and in submitPrompt's finally, so it can never
  // outlive the request it describes (the exact zombie-state class this fix
  // targets, one layer up from the render-default bug above).
  const [retryStatus, setRetryStatus] = useState<EffortCalloutState>({ active: false });

  // Animate spinner at ANIMATION_LOOP_MS cadence
  useInterval(() => {
    if (busyRef.current) {
      setSpinnerElapsed(Date.now() - spinnerStartRef.current);
    }
  }, ANIMATION_LOOP_MS);

  // Telemetry state (polled every 500ms; deduped by memo key)
  const [telemetry, setTelemetry] = useState<TelemetryState>(() => getState());

  useEffect(() => {
    const handle = startTelemetryWatch();
    return () => handle.stop();
  }, []);

  useInterval(() => {
    const next = getState();
    setTelemetry((prev) =>
      _telemetryMemoKey(prev) === _telemetryMemoKey(next) ? prev : { ...next },
    );
  }, 500);

  // Keep messagesRef in sync with React state for use inside async callbacks.
  useEffect(() => { messagesRef.current = messages; }, [messages]);

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
      permissionMode: config.permissionMode,
    });
    return () => {
      const duration = Date.now() - mountRef.current;
      analytics?.log(ANALYTICS_SESSION_END, { duration });
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
  const handleInterrupt        = useCallback(() => {}, []);
  const handleTaskPanelToggle = useCallback(
    () => setTaskPanelVisible((v) => toggleTaskPanel(v)),
    [],
  );

  // Editor open shortcut (wired to future /edit handler)
  useInput((_input, key) => {
    if (key.ctrl && _input === "e") { /* editor open: handled by main */ }
  });

  // Status-bar prop shapes
  const sbMode: "bypass" | "regular"   = permMode === "bypass" ? "bypass" : "regular";
  const permModeState: PermissionModeState = { mode: sbMode, cycle: handlePermCycle };
  const interruptHandler: InterruptHandler = { interrupt: handleInterrupt };
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

  // Render dispatch (memoised per lookups + viewport width)
  const renderMessage = useCallback(
    (msg: SessionMessage) =>
      renderMsgDispatch(msg, lookups as MessageLookups, terminalCols),
    [lookups, terminalCols],
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

  // Prompt input hook
  const [inputState, inputActions] = usePromptInput();

  // Latest input-buffer snapshot, readable from the injector's closures below
  // without re-constructing them on every keystroke.
  const inputStateRef = useRef(inputState);
  inputStateRef.current = inputState;

  // Slash-command completion dropdown (b22 item 1 / b23 ellipsis-clip fix). Commands load once
  // at mount; the dropdown itself is a pure function of the live input text + terminal width, so
  // it stays in sync with both typing (narrows the match list) and resize (b23's description
  // truncation re-derives its budget from `terminalCols` on every render).
  const [slashCommands, setSlashCommands]           = useState<RegistryCommand[]>([]);
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
  const dropdownDisplay = computeSlashDropdownDisplay(dropdownMatches, dropdownSelectedIndex);

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
  // Both count as queued user input per docs/goal-mode-mechanism.md §7 delta 3
  // ("Operator preemption via the operator pipe as well as the TUI").
  const goalContinuationEngineRef = useRef<GoalContinuationEngine | null>(null);
  if (!goalContinuationEngineRef.current) {
    goalContinuationEngineRef.current = createGoalContinuationEngine();
  }
  const pokeGoalContinuationRef = useRef<(() => void) | null>(null);
  if (!pokeGoalContinuationRef.current) {
    pokeGoalContinuationRef.current = createGoalContinuationPoke({
      engine:   goalContinuationEngineRef.current,
      getStore: getGoalStore,
      getEligibilitySignals: () => ({
        featureEnabled: isGoalContinuationFeatureEnabled(),
        // ember-cli's EnterPlanModeTool flips PermissionMode to 'plan' via
        // ToolUseContext.setAppState (tools/plan-mode-tools.ts) — but
        // engineCfg.setAppState below (see the QueryEngine construction
        // further down this file) is still a no-op stub (#182's cwd-only
        // AppState), so that flip is never threaded back into this
        // component's reactive state today. Pre-existing gap, not
        // introduced here; disclosed rather than papered over with a fake
        // signal — see this PR's body for the follow-up.
        planMode: false,
        turnActive: busyRef.current,
        queuedUserInput:
          inputStateRef.current.text.length > 0 ||
          (operatorInjectorRef.current?.queueLength ?? 0) > 0,
      }),
      startTurn: async (prompt: string) => {
        await submitPromptRef.current(prompt, "operator");
      },
      getReceiptWriter: () => getGoalReceiptWriter(),
    });
  }

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

    // Slash-command dispatch — execute a registered command instead of a model
    // turn. Returns null for ordinary input, which falls through to the engine.
    const slashResult = await tryDispatchSlashCommand(text, {
      sessionId: sessionIdRef.current,
      mode:      String(permMode),
      cwd,
    });
    if (slashResult !== null) {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), type: "assistant", content: slashResult.message },
      ]);
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
          canUseTool:         async () => true,
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
          setMessages((prev) => applyResultEvent(event, prev, assistantId));
          break;
        }
      }

      // Operator-session receipt (ember #165 acceptance): the response for an
      // operator-injected prompt has finished rendering into the transcript.
      if (origin === "operator" && !abortCtrl.signal.aborted) {
        operatorReceiptsRef.current?.append("response_rendered", assistantId);
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

      // Fire prompt-suggestion generation after each completed turn.
      if (!abortCtrl.signal.aborted && callModelRef.current) {
        void executePromptSuggestion({
          messages:   messagesRef.current as any, // eslint-disable-line @typescript-eslint/no-explicit-any
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
      // engine (spec §3: "every task/turn completion pokes maybe-continue-
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

  // Main keyboard handler
  useInput((input, key) => {
    // Slash-command dropdown navigation takes priority over every other binding while it's open
    // (b22 item 1) -- Enter completes the highlighted command into the input instead of falling
    // through to message-submit below.
    if (dropdownOpen && dropdownDisplay.visible.length > 0) {
      if (key.downArrow) {
        setDropdownSelIndex((i) => moveDropdownSelection(i, dropdownDisplay.visible.length, 1));
        return;
      }
      if (key.upArrow) {
        setDropdownSelIndex((i) => moveDropdownSelection(i, dropdownDisplay.visible.length, -1));
        return;
      }
      if (key.return) {
        const chosen = dropdownDisplay.visible[dropdownDisplay.selectedIndex];
        if (chosen) inputActions.setText(completeSlashSelection(chosen));
        return;
      }
    }

    // Submit on Enter
    if (!key.shift && key.tab) {
      // Accept the current ghost suggestion into the input.
      if (currentSuggestion && !busyRef.current) {
        inputActions.setText(currentSuggestion);
        setCurrentSuggestion(null);
      }
      return;
    }

    if (key.return) {
      if (busyRef.current || !inputState.text.trim()) return;
      const text = inputState.text;
      inputActions.setText("");
      // Clear any pending suggestion when the user submits.
      setCurrentSuggestion(null);
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
      inputActions.deleteBackward();
      return;
    }
    if (key.delete) {
      inputActions.deleteForward();
      return;
    }

    // Regular character input — clears ghost suggestion on first keystroke.
    if (input && !key.ctrl && !key.meta && !key.alt) {
      if (currentSuggestion) setCurrentSuggestion(null);
      inputActions.insertText(input);
    }
  });

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return React.createElement(
    Box,
    { flexDirection: "column", height: terminalRows },

    // Transcript
    React.createElement(
      Box,
      { key: "transcript", flexDirection: "column", flexGrow: transcriptFlexGrow(messages), overflow: "hidden", justifyContent: transcriptJustifyContent(messages) },
      transcript,
    ),

    // Dialog overlay (idle-return, cost-threshold, …)
    dialogOverlay,

    // Spinner while processing
    busy
      ? React.createElement(SpinnerAnimationRow, {
          key:         "spinner",
          elapsedMs:   spinnerElapsed,
          startedAtMs: spinnerStartRef.current,
        })
      : null,

    // Slash-command completion dropdown (b22 item 1) — sits directly above the input line while
    // composing a command name; b23: each row's description ellipsis-truncates to the live
    // terminal width instead of hard-clipping mid-word.
    dropdownOpen && dropdownDisplay.visible.length > 0
      ? React.createElement(SlashDropdown, {
          key:           "slash-dropdown",
          commands:      dropdownDisplay.visible,
          selectedIndex: dropdownDisplay.selectedIndex,
          overflowCount: dropdownDisplay.overflowCount,
          width:         terminalCols,
        })
      : null,

    // Text input (suggestion = dimmed ghost text after cursor; Tab accepts it)
    React.createElement(PromptInput, {
      key:            "input",
      state:          inputState,
      isProcessing:   busy,
      showStatusLine: false,
      suggestion:     currentSuggestion ?? undefined,
    }),

    // Status bar — modelMetrics is null when the model server is unreachable (meter hidden).
    // effort: issue #197's live retry-attempt indicator (transient; never a
    // transcript message — see retryStatus state and its clear sites above).
    React.createElement(StatusLine, {
      key:            "status",
      permissionMode: permModeState,
      interrupt:      interruptHandler,
      taskPanel:      taskPanelState,
      modelMetrics:   modelMetrics ?? undefined,
      effort:         retryStatus,
      degraded:       degradedBanner,
    }),
  );
}
