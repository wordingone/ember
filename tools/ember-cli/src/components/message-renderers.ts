// message-renderers.ts — conversation message rendering layer.
// Turns the session's JSONL stream into terminal output for every message type.

import React from "react";
import { Text, Box, RawAnsi } from "../ink/components.ts";
import type { Message, AssistantMessage, UserMessage, SystemMessage } from "../types/message-types.ts";
import { Markdown } from "./markdown-and-code.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

/** Error text truncation length before expand-on-demand control. */
export const MAX_API_ERROR_CHARS = 1000;

/** Minimum ms to show inline hints before allowing dismiss. */
export const MIN_HINT_DISPLAY_MS = 700;

/** The spinning-loader glyph for in-progress tool calls. */
export const BLACK_CIRCLE = "●";

/** Compaction in-progress placeholder. */
export const COMPACTION_IN_PROGRESS_TEXT = "Razzle-dazzling…";

/** Compaction complete prefix. */
export const COMPACTION_COMPLETE_PREFIX  = "⌁ Crunched for ";

// ---------------------------------------------------------------------------
// Error content type signals (routing keys for assistant text messages)
// ---------------------------------------------------------------------------

export type AssistantTextErrorType =
  | "prompt-too-long"
  | "credit-balance"
  | "invalid-key"
  | "org-disabled"
  | "token-revoked"
  | "API-timeout"
  | "custom-off-switch"
  | "user-abort";

/** Classify an assistant text body into an error type, or null for normal text. */
export function classifyAssistantText(text: string): AssistantTextErrorType | null {
  if (text.includes("__credit_balance__"))  return "credit-balance";
  if (text.includes("__invalid_key__"))     return "invalid-key";
  if (text.includes("__org_disabled__"))    return "org-disabled";
  if (text.includes("__token_revoked__"))   return "token-revoked";
  if (text.includes("__api_timeout__"))     return "API-timeout";
  if (text.includes("__custom_off__"))      return "custom-off-switch";
  if (text.includes("__user_abort__"))      return "user-abort";
  if (text.includes("__prompt_too_long__")) return "prompt-too-long";
  return null;
}

// ---------------------------------------------------------------------------
// Tool-use state resolution
// ---------------------------------------------------------------------------

export interface ToolUseState {
  isResolved:             boolean;
  isQueued:               boolean;
  isWaitingForPermission: boolean;
  isError:                boolean;
}

export function resolveToolUseState(toolUseId: string, lookups: MessageLookups): ToolUseState {
  return {
    isResolved:             lookups.resolvedToolUseIDs.has(toolUseId),
    isQueued:               !lookups.inProgressToolUseIDs.has(toolUseId) &&
                            !lookups.resolvedToolUseIDs.has(toolUseId) &&
                            !lookups.erroredToolUseIDs.has(toolUseId),
    isWaitingForPermission: lookups.permissionPendingToolUseIDs.has(toolUseId),
    isError:                lookups.erroredToolUseIDs.has(toolUseId),
  };
}

// ---------------------------------------------------------------------------
// buildMessageLookups (AC10)
// ---------------------------------------------------------------------------

export interface MessageLookups {
  resolvedToolUseIDs:         Set<string>;
  erroredToolUseIDs:          Set<string>;
  inProgressToolUseIDs:       Set<string>;
  permissionPendingToolUseIDs: Set<string>;
  toolResultByToolUseID:      Map<string, Message>;
  progressMessagesByToolUseID: Map<string, Message[]>;
  inProgressHookCounts:       number;
  resolvedHookCounts:         number;
}

export function buildMessageLookups(messages: Message[]): MessageLookups {
  const resolvedToolUseIDs         = new Set<string>();
  const erroredToolUseIDs          = new Set<string>();
  const permissionPendingToolUseIDs = new Set<string>();
  const toolResultByToolUseID      = new Map<string, Message>();
  const progressMessagesByToolUseID = new Map<string, Message[]>();
  const seenToolUseIDs             = new Set<string>();
  let inProgressHookCounts         = 0;
  let resolvedHookCounts           = 0;

  for (const msg of messages) {
    if (msg.role === "assistant") {
      const content = msg.content as Array<{ type?: string; id?: string }>;
      for (const block of content) {
        if (block.type === "tool_use" && block.id) {
          seenToolUseIDs.add(block.id);
        }
      }
    }

    if (msg.role === "user") {
      const content = msg.content as Array<{ type?: string; tool_use_id?: string; is_error?: boolean }>;
      for (const block of content) {
        if (block.type === "tool_result" && block.tool_use_id) {
          const id = block.tool_use_id;
          toolResultByToolUseID.set(id, msg);
          if (block.is_error) {
            erroredToolUseIDs.add(id);
          } else {
            resolvedToolUseIDs.add(id);
          }
        }
      }
    }

    if (msg.role === "progress") {
      const id = msg.toolUseId;
      if (!progressMessagesByToolUseID.has(id)) {
        progressMessagesByToolUseID.set(id, []);
      }
      progressMessagesByToolUseID.get(id)!.push(msg);
    }

    if (msg.role === "system") {
      if (msg.type === "stop_hook_summary") {
        resolvedHookCounts++;
      }
    }
  }

  // inProgressToolUseIDs: tool_use blocks with no matching tool_result yet (AC10)
  const inProgressToolUseIDs = new Set<string>();
  for (const id of seenToolUseIDs) {
    if (!resolvedToolUseIDs.has(id) && !erroredToolUseIDs.has(id)) {
      inProgressToolUseIDs.add(id);
    }
  }

  return {
    resolvedToolUseIDs,
    erroredToolUseIDs,
    inProgressToolUseIDs,
    permissionPendingToolUseIDs,
    toolResultByToolUseID,
    progressMessagesByToolUseID,
    inProgressHookCounts,
    resolvedHookCounts,
  };
}

// ---------------------------------------------------------------------------
// AssistantThinkingMessage (AC7: hideInTranscript suppresses render)
// ---------------------------------------------------------------------------

export interface AssistantThinkingMessageProps {
  thinking: string;
  hideInTranscript?: boolean;
  isExpanded?: boolean;
}

export function AssistantThinkingMessage(
  props: AssistantThinkingMessageProps,
): React.ReactElement | null {
  // AC7: hideInTranscript=true → render nothing
  if (props.hideInTranscript) return null;

  if (!props.thinking.trim()) {
    return React.createElement(Text, { dimColor: true, italic: true }, "Thinking…");
  }

  if (props.isExpanded) {
    return React.createElement(Box, { borderStyle: "single", flexDirection: "column" },
      React.createElement(Text, { italic: true }, "Thinking:"),
      React.createElement(Text, null, props.thinking),
    );
  }

  return React.createElement(Text, { dimColor: true, italic: true },
    `Thinking… (Ctrl+O to expand)`,
  );
}

// ---------------------------------------------------------------------------
// RedactedThinkingMessage
// ---------------------------------------------------------------------------

export function RedactedThinkingMessage(): React.ReactElement {
  return React.createElement(Text, { italic: true, dimColor: true }, "Thinking…");
}

// ---------------------------------------------------------------------------
// AssistantTextMessage (AC2, AC3, AC6)
// ---------------------------------------------------------------------------

export interface AssistantTextMessageProps {
  text: string;
  isExpanded?: boolean;
}

export function AssistantTextMessage(props: AssistantTextMessageProps): React.ReactElement | null {
  const { text, isExpanded = false } = props;

  // AC2: empty trimmed content → render nothing
  if (!text.trim()) return null;

  const errorType = classifyAssistantText(text);

  // AC3: credit-balance routes to specialized renderer
  if (errorType === "credit-balance") {
    return React.createElement(Box, { borderStyle: "single", borderColor: "yellow" },
      React.createElement(Text, { color: "yellow" },
        "Payment required. Please add credits to continue.",
      ),
    );
  }

  if (errorType === "invalid-key") {
    return React.createElement(Text, { color: "red" }, "API key is invalid.");
  }
  if (errorType === "org-disabled") {
    return React.createElement(Text, { color: "red" }, "Organization access disabled.");
  }
  if (errorType === "token-revoked") {
    return React.createElement(Text, { color: "red" }, "Session token revoked.");
  }
  if (errorType === "API-timeout") {
    return React.createElement(Text, { color: "yellow" }, "API request timed out.");
  }
  if (errorType === "prompt-too-long") {
    return React.createElement(Text, { color: "yellow" }, "Context limit reached.");
  }
  if (errorType === "custom-off-switch") {
    return React.createElement(Text, { dimColor: true }, text);
  }
  if (errorType === "user-abort") {
    return React.createElement(Text, { dimColor: true }, "Interrupted by user.");
  }

  // AC6: error text > MAX_API_ERROR_CHARS → truncate with expand control
  if (text.length > MAX_API_ERROR_CHARS && !isExpanded) {
    const truncated = text.slice(0, MAX_API_ERROR_CHARS);
    return React.createElement(Box, { flexDirection: "column" },
      React.createElement(Text, null, truncated),
      React.createElement(Text, { dimColor: true }, "… (Ctrl+O to expand)"),
    );
  }

  // Normal text — route through Markdown for bold/code/heading rendering (M9 wiring).
  // BLACK_CIRCLE prefix matches the ● message-block indicator.
  // Issue #581: text carrying an embedded raw ANSI escape sequence (e.g. renderMonitorPanel()'s
  // colored /cockpit panel output) must never be walked character-by-character through
  // Markdown's plain Text leaf -- the rendering pipeline's text branch treats each byte of the
  // escape sequence as its own printable cell, splitting the ESC byte from its digits and
  // leaking them as literal garbage. HighlightedCode already solved this exact problem for
  // highlighted code blocks by routing through RawAnsi (markdown-and-code.ts); apply the same
  // fix here so any ANSI-bearing message survives the display path intact.
  const hasRawAnsi = text.includes("\x1b");
  return React.createElement(Box, { flexDirection: "row" },
    React.createElement(Text, { dimColor: true }, BLACK_CIRCLE + " "),
    hasRawAnsi
      ? React.createElement(RawAnsi, null, text)
      : React.createElement(Markdown, { content: text }),
  );
}

// ---------------------------------------------------------------------------
// AssistantToolUseMessage (AC4, AC5)
// ---------------------------------------------------------------------------

export interface AssistantToolUseMessageProps {
  toolUseId:   string;
  toolName:    string;
  toolFacingName?: string;
  lookups:     MessageLookups;
  isExpanded?: boolean;
  /** Optional background color key from tool definition. */
  backgroundColor?: string;
}

export function AssistantToolUseMessage(props: AssistantToolUseMessageProps): React.ReactElement {
  const { toolUseId, toolFacingName, lookups } = props;
  const state = resolveToolUseState(toolUseId, lookups);
  const displayName = toolFacingName ?? props.toolName;

  // AC4: isWaitingForPermission → show tool name + permission-pending indicator
  if (state.isWaitingForPermission) {
    return React.createElement(Box, { flexDirection: "row" },
      React.createElement(Text, { bold: true }, displayName),
      React.createElement(Text, { color: "yellow" }, " [waiting for permission]"),
    );
  }

  // AC5: isResolved → show outcome summary, not the loader glyph
  if (state.isResolved) {
    return React.createElement(Box, { flexDirection: "row" },
      React.createElement(Text, { color: "green" }, "✓ "),
      React.createElement(Text, null, displayName),
    );
  }

  if (state.isError) {
    return React.createElement(Box, { flexDirection: "row" },
      React.createElement(Text, { color: "red" }, "✗ "),
      React.createElement(Text, null, displayName),
    );
  }

  if (state.isQueued) {
    return React.createElement(Box, { flexDirection: "row" },
      React.createElement(Text, { dimColor: true }, "○ "),
      React.createElement(Text, { dimColor: true }, displayName),
    );
  }

  // Default / in-progress: BLACK_CIRCLE + indicator
  return React.createElement(Box, { flexDirection: "row" },
    React.createElement(Text, null, BLACK_CIRCLE + " "),
    React.createElement(Text, null, displayName),
  );
}

// ---------------------------------------------------------------------------
// UserTextMessage (AC1 helper)
// ---------------------------------------------------------------------------

export interface UserTextMessageProps {
  text:       string;
  timestamp?: string;
  brief?:     boolean;
  /** ember #165: prompts injected via the operator named-pipe channel carry
   *  this so the transcript visibly distinguishes them from keyboard input. */
  origin?:    "keyboard" | "operator";
}

export function UserTextMessage({ text, timestamp, brief = false, origin }: UserTextMessageProps): React.ReactElement {
  const header = React.createElement(Box, { flexDirection: "row" },
    React.createElement(Text, { bold: true }, "You"),
    origin === "operator" ? React.createElement(Text, { color: "cyan" }, " [operator]") : null,
    timestamp ? React.createElement(Text, { dimColor: true }, ` ${timestamp}`) : null,
  );

  if (brief) {
    return React.createElement(Box, { flexDirection: "row" },
      header,
      React.createElement(Text, null, ` ${text}`),
    );
  }

  return React.createElement(Box, { flexDirection: "column" },
    header,
    React.createElement(Text, null, text),
  );
}

// ---------------------------------------------------------------------------
// UserCommandMessage
// ---------------------------------------------------------------------------

export function UserCommandMessage({ command }: { command: string }): React.ReactElement {
  return React.createElement(Text, { dimColor: true }, `/ ${command}`);
}

// ---------------------------------------------------------------------------
// UserTeammateMessage (AC11)
// ---------------------------------------------------------------------------

export interface TeammateProtocol {
  type: "task_assignment" | "plan_approval_request" | "plan_approval_response" |
        "shutdown_request" | "shutdown_rejected" | string;
  summary?: string;
  [key: string]: unknown;
}

export interface UserTeammateMessageProps {
  teammateName:  string;
  teammateColor: string;
  content:       string;
  isExpanded?:   boolean;
}

export function parseTeammateContent(content: string): TeammateProtocol | null {
  try {
    const parsed = JSON.parse(content) as unknown;
    if (typeof parsed === "object" && parsed !== null && "type" in parsed) {
      return parsed as TeammateProtocol;
    }
  } catch {
    // not structured JSON
  }
  return null;
}

export function UserTeammateMessage(props: UserTeammateMessageProps): React.ReactElement {
  const { teammateName, teammateColor, content, isExpanded = false } = props;
  const protocol = parseTeammateContent(content);

  // AC11: header shows teammate name in their color
  const header = React.createElement(Box, { flexDirection: "row" },
    React.createElement(Text, { color: teammateColor, bold: true }, teammateName),
    protocol?.type
      ? React.createElement(Text, { dimColor: true }, ` · ${protocol.type}`)
      : null,
  );

  if (protocol?.type === "task_assignment") {
    // AC11: collapsible summary; chevron (›) expands to full content
    const summary = protocol.summary ?? "(no summary)";
    return React.createElement(Box, { flexDirection: "column" },
      header,
      React.createElement(Box, { flexDirection: "row" },
        React.createElement(Text, { dimColor: true }, isExpanded ? "‹ " : "› "),
        React.createElement(Text, null, isExpanded ? content : summary),
      ),
    );
  }

  return React.createElement(Box, { flexDirection: "column" },
    header,
    React.createElement(Text, null, isExpanded ? content : (protocol?.summary ?? content)),
  );
}

// ---------------------------------------------------------------------------
// AttachmentMessage (AC12)
// ---------------------------------------------------------------------------

/** Attachment types that are silently filtered. */
export const FILTERED_ATTACHMENT_TYPES = new Set([
  "idle_notification",
  "teammate_terminated",
]);

export interface AttachmentMessageProps {
  attachment: { type?: string; content?: string; error?: string; [key: string]: unknown };
  teammateName?:  string;
  teammateColor?: string;
}

export function AttachmentMessage(props: AttachmentMessageProps): React.ReactElement | null {
  const { attachment } = props;
  const type = attachment.type ?? "";

  // AC12: do not render idle_notification or teammate_terminated
  if (FILTERED_ATTACHMENT_TYPES.has(type)) return null;

  if (type === "task_assignment") {
    return React.createElement(Box, { borderStyle: "single" },
      React.createElement(Text, null, attachment.content ?? "(task assignment)"),
    );
  }

  if (attachment.error) {
    return React.createElement(Box, { borderStyle: "single", borderColor: "red" },
      React.createElement(Text, { color: "red" }, attachment.error),
    );
  }

  return React.createElement(Box, null,
    React.createElement(Text, null, attachment.content ?? ""),
  );
}

// ---------------------------------------------------------------------------
// SystemAPIErrorMessage
// ---------------------------------------------------------------------------

export interface SystemAPIErrorMessageProps {
  errorText:     string;
  retryCount:    number;
  nextRetryMs?:  number;
  isExpanded?:   boolean;
}

/**
 * Renders a TERMINAL API error: the query engine has already stopped
 * retrying (query-engine.ts's callModelWithRetry either exhausted its
 * bounded attempts or hit a deterministic 4xx that skips retry entirely) by
 * the time repl.ts's applyResultEvent ever creates the "error" message this
 * component renders. Issue #197: this used to early-return null whenever
 * retryCount<=3 (AC9, written for an earlier design where the SAME message
 * updated in place across live retry attempts and was deliberately hidden
 * until the count got "persistent enough"). Nothing in the current code
 * calls this component more than once per message, so with repl.ts's
 * retryCount default corrected from 4 to 0 (the zombie-"Retrying…" fix),
 * that threshold started hiding EVERY deterministic-4xx terminal error
 * outright (retryCount is legitimately 0 whenever no retry ever ran) --
 * a strictly worse regression than the stale-text bug it replaced. A
 * terminal error message must always render: it is the only record of what
 * went wrong. The retryCount is still surfaced, but honestly -- as a
 * completed attempt count, never as an in-progress "Retrying…" claim (that
 * live state now belongs to the status bar's effort callout in repl.ts,
 * cleared the instant the turn ends).
 */
export function SystemAPIErrorMessage(props: SystemAPIErrorMessageProps): React.ReactElement | null {
  const { errorText, retryCount, isExpanded = false } = props;

  const text = errorText.length > MAX_API_ERROR_CHARS && !isExpanded
    ? errorText.slice(0, MAX_API_ERROR_CHARS) + "… (Ctrl+O to expand)"
    : errorText;

  const attemptsLabel = retryCount > 0
    ? `Gave up after ${retryCount} retry attempt${retryCount === 1 ? "" : "s"}.`
    : null;

  const children = [React.createElement(Text, { key: "text", color: "red" }, text)];
  if (attemptsLabel) {
    children.push(React.createElement(Text, { key: "attempts", dimColor: true }, attemptsLabel));
  }

  return React.createElement(
    Box,
    { flexDirection: "column", borderStyle: "single", borderColor: "red" },
    ...children,
  );
}

// ---------------------------------------------------------------------------
// CompactBoundaryMessage (AC8)
// ---------------------------------------------------------------------------

export const COMPACT_BOUNDARY_TEXT = "Conversation compacted (Ctrl+O for history)";

export function CompactBoundaryMessage(): React.ReactElement {
  return React.createElement(Text, { dimColor: true }, COMPACT_BOUNDARY_TEXT);
}

// ---------------------------------------------------------------------------
// CompactionProgressMessage (AC13)
// ---------------------------------------------------------------------------

export interface CompactionProgressMessageProps {
  isComplete:  boolean;
  elapsedSecs?: number;
}

export function CompactionProgressMessage(
  props: CompactionProgressMessageProps,
): React.ReactElement {
  if (props.isComplete) {
    // AC13: "⌁ Crunched for Xs"
    return React.createElement(Text, null,
      `${COMPACTION_COMPLETE_PREFIX}${props.elapsedSecs ?? 0}s`,
    );
  }
  // AC13: during compaction: "Razzle-dazzling…"
  return React.createElement(Text, null, COMPACTION_IN_PROGRESS_TEXT);
}

// ---------------------------------------------------------------------------
// HookProgressMessage
// ---------------------------------------------------------------------------

export interface HookProgressMessageProps {
  hookCount:    number;
  hookNames:    string[];
  isTranscript: boolean;
}

export function HookProgressMessage(props: HookProgressMessageProps): React.ReactElement {
  const { hookCount, hookNames, isTranscript } = props;
  const eventName = hookNames.join(", ");
  const label     = `Running ${hookCount} hook${hookCount !== 1 ? "s" : ""}: ${eventName}`;

  if (isTranscript) {
    return React.createElement(Text, { dimColor: true }, label);
  }

  // Live mode: animated ellipsis
  return React.createElement(Text, null, `${label}…`);
}

// ---------------------------------------------------------------------------
// MessageRow — layout wrapper
// ---------------------------------------------------------------------------

export interface MessageRowProps {
  children: React.ReactNode;
  timestamp?: string;
}

export function MessageRow({ children, timestamp }: MessageRowProps): React.ReactElement {
  return React.createElement(Box, { flexDirection: "row", paddingLeft: 2 },
    React.createElement(Box, { flexDirection: "column", flexGrow: 1 },
      children,
    ),
    timestamp
      ? React.createElement(Text, { dimColor: true }, timestamp)
      : null,
  );
}

// ---------------------------------------------------------------------------
// SystemInfoMessage (session metadata)
// ---------------------------------------------------------------------------

export interface SystemInfoMessageProps {
  turnNumber?:  number;
  modelName?:   string;
  inputTokens?: number;
  outputTokens?: number;
  cacheWriteTokens?: number;
  cacheReadTokens?: number;
  isFirst?: boolean;
}

export function SystemInfoMessage(props: SystemInfoMessageProps): React.ReactElement {
  const parts: React.ReactElement[] = [];

  if (props.isFirst) {
    parts.push(React.createElement(Text, { key: "start", dimColor: true }, "─── Conversation started ───"));
  }
  if (props.turnNumber !== undefined) {
    parts.push(React.createElement(Text, { key: "turn", dimColor: true }, `Turn ${props.turnNumber}`));
  }
  if (props.modelName) {
    parts.push(React.createElement(Text, { key: "model", dimColor: true }, `Model: ${props.modelName}`));
  }
  if (props.inputTokens !== undefined) {
    parts.push(React.createElement(Text, { key: "tokens", dimColor: true },
      `Tokens: ${props.inputTokens} in / ${props.outputTokens ?? 0} out` +
      (props.cacheWriteTokens ? ` / ${props.cacheWriteTokens} cache-write` : "") +
      (props.cacheReadTokens  ? ` / ${props.cacheReadTokens} cache-read`  : ""),
    ));
  }

  return React.createElement(Box, { flexDirection: "column" }, ...parts);
}

// ---------------------------------------------------------------------------
// AC1 helper: assert assistant turn produces thinking-first ordering
// ---------------------------------------------------------------------------

export interface RenderedTurn {
  kind: "thinking" | "text" | "tool_use";
  content: string;
}

/**
 * Extract rendered turn order from an AssistantMessage.
 * Spec: thinking block always first, then text/tool_use (AC1).
 */
export function extractTurnOrder(msg: AssistantMessage): RenderedTurn[] {
  const content = msg.content as Array<{ type?: string; thinking?: string; text?: string; name?: string }>;
  const turns: RenderedTurn[] = [];

  // Collect thinking blocks first (stop_reason = null)
  for (const block of content) {
    if (block.type === "thinking") {
      turns.push({ kind: "thinking", content: block.thinking ?? "" });
    }
  }
  // Then text / tool_use
  for (const block of content) {
    if (block.type === "text") {
      turns.push({ kind: "text", content: block.text ?? "" });
    } else if (block.type === "tool_use") {
      turns.push({ kind: "tool_use", content: block.name ?? "" });
    }
  }
  return turns;
}

// ---------------------------------------------------------------------------
// AC14: slash commands are TUI-level, no message entry
// ---------------------------------------------------------------------------

/**
 * Returns true if a slash command input should be processed TUI-level.
 * These MUST NOT produce user or assistant JSONL entries.
 */
export function isSlashCommand(input: string): boolean {
  return input.trimStart().startsWith("/");
}
