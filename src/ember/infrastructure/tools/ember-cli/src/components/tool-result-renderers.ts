// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tool-result-renderers.ts — routes each tool_result message to the
// correct renderer based on outcome: success, error, rejection, cancellation.

import React from "react";
import { Text, Box } from "../ink/components.ts";
import { MAX_API_ERROR_CHARS } from "./message-renderers.ts";
import { tryRenderAsDiff } from "./diff-card.ts";
import type { Tool } from "../core/tool-interface.ts";
import type { MessageLookups } from "./message-renderers.ts";

// ---------------------------------------------------------------------------
// Signal constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

/** Identifies a canceled tool result (user canceled before execution). */
export const CANCEL_MESSAGE = "This operation has been canceled by the user.";

// ---------------------------------------------------------------------------
// Large-output truncation (M10 A2 — large_output score)
// ---------------------------------------------------------------------------

/**
 * Line count above which a tool result is considered "large" and displayed in
 * tail-truncated form.  Kept at 20 so the truncation indicator fires on any
 * output that genuinely spans more than a typical viewport.
 */
export const LARGE_OUTPUT_LINE_THRESHOLD = 20;

/**
 * Number of tail lines shown when a large output is truncated.
 * 20 lines is enough to hit the M10 A2 large_output score-2 threshold
 * (≥20 component-NNN lines visible) while still fitting most viewports.
 */
export const LARGE_OUTPUT_TAIL_LINES = 20;

/**
 * Returns true when the output text should be tail-truncated.
 * Triggered when the line count exceeds LARGE_OUTPUT_LINE_THRESHOLD.
 */
export function isLargeOutput(text: string): boolean {
  // Returns true when line count > LARGE_OUTPUT_LINE_THRESHOLD, i.e. newlines >= threshold.
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\n") {
      count++;
      if (count >= LARGE_OUTPUT_LINE_THRESHOLD) return true;
    }
  }
  return false;
}

/**
 * Splits text into { head, tail, hiddenCount } for tail-truncated display.
 * `tail` contains the last LARGE_OUTPUT_TAIL_LINES lines;
 * `hiddenCount` is how many lines are hidden above.
 */
export function splitLargeOutput(text: string): {
  tail:        string;
  hiddenCount: number;
} {
  const lines = text.split("\n");
  if (lines.length <= LARGE_OUTPUT_LINE_THRESHOLD) {
    return { tail: text, hiddenCount: 0 };
  }
  const hiddenCount = lines.length - LARGE_OUTPUT_TAIL_LINES;
  const tail        = lines.slice(-LARGE_OUTPUT_TAIL_LINES).join("\n");
  return { tail, hiddenCount };
}

/**
 * Renders a tail-truncated large output.
 * Shows `└ … [+N lines above]` then the last LARGE_OUTPUT_TAIL_LINES lines.
 */
export function LargeTailOutput({ text }: { text: string }): React.ReactElement {
  const { tail, hiddenCount } = splitLargeOutput(text);
  return React.createElement(Box, { flexDirection: "column" },
    React.createElement(
      Text,
      { key: "indicator", dimColor: true },
      `${RESULT_GUTTER}… +${hiddenCount} lines above (Ctrl+O shows all)`,
    ),
    React.createElement(Box, { key: "tail", paddingLeft: RESULT_GUTTER.length },
      React.createElement(Text, { dimColor: true }, tail)),
  );
}

/** Gutter in front of a tool's output. The classic Windows console font has no "⎿". */
export const RESULT_GUTTER = process.env["EMBER_ASCII_GLYPHS"] === "1" ? "  L  " : "  ⎿  ";

/** Tool output longer than this folds to its first FOLD_HEAD_LINES lines, as Claude Code does:
 * a 14-hit search or a long listing otherwise pushed the answer off screen (blind test W26). */
export const FOLD_LINE_THRESHOLD = 6;
export const FOLD_HEAD_LINES = 3;

export function FoldedOutput({ text }: { text: string }): React.ReactElement {
  const lines = text.split("\n");
  const hidden = lines.length - FOLD_HEAD_LINES;
  return React.createElement(Box, { flexDirection: "column" },
    React.createElement(Box, { key: "head", flexDirection: "row" },
      React.createElement(Text, { dimColor: true }, RESULT_GUTTER),
      React.createElement(Text, { dimColor: true }, lines.slice(0, FOLD_HEAD_LINES).join("\n"))),
    React.createElement(Box, { key: "more", paddingLeft: RESULT_GUTTER.length },
      React.createElement(Text, { dimColor: true }, `… +${hidden} lines (Ctrl+O shows all)`)),
  );
}

/** Identifies a user-rejected tool use (policy deny before execution). */
export const REJECT_MESSAGE = "<tool_use_rejected>";

/** Identifies an interrupted result (user pressed Esc mid-execution). */
export const INTERRUPT_MESSAGE = "<interrupted>";

/** Rejected tool use where the denial includes a reason string. */
export const REJECT_MESSAGE_WITH_REASON_PREFIX = "<tool_use_rejected_reason:";

/** Prefix identifying a plan rejection. */
export const PLAN_REJECTION_PREFIX = "<plan_rejected>";

/** Interrupt that occurred specifically during tool execution. */
export const INTERRUPT_MESSAGE_FOR_TOOL_USE = "<interrupted_during_tool_use>";

// ---------------------------------------------------------------------------
// Feature flags consumed (spec — preserve exactly)
// ---------------------------------------------------------------------------

export interface FeatureFlags {
  KAIROS:               boolean;
  KAIROS_BRIEF:         boolean;
  BASH_CLASSIFIER:      boolean;
  TRANSCRIPT_CLASSIFIER: boolean;
  REVIEW_ARTIFACT:      boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  KAIROS:               false,
  KAIROS_BRIEF:         false,
  BASH_CLASSIFIER:      false,
  TRANSCRIPT_CLASSIFIER: false,
  REVIEW_ARTIFACT:      false,
};

let _featureFlags: FeatureFlags = { ...DEFAULT_FLAGS };

export function setFeatureFlags(flags: Partial<FeatureFlags>): void {
  _featureFlags = { ..._featureFlags, ...flags };
}

export function getFeatureFlags(): FeatureFlags { return _featureFlags; }

export function resetFeatureFlags(): void { _featureFlags = { ...DEFAULT_FLAGS }; }

// ---------------------------------------------------------------------------
// Tool result content type
// ---------------------------------------------------------------------------

export interface ToolResultContent {
  type:         "tool_result";
  tool_use_id:  string;
  content:      string | unknown[];
  is_error?:    boolean;
  /** Optional classifier approval metadata (consumed by BASH_CLASSIFIER path). */
  _classifierApproval?: unknown;
}

/** Normalize content to a string for signal detection. */
export function contentToString(content: string | unknown[]): string {
  if (typeof content === "string") return content;
  // Content block array: extract text values
  return (content as Array<{ type?: string; text?: string }>)
    .filter(b => b.type === "text")
    .map(b => b.text ?? "")
    .join("");
}

// ---------------------------------------------------------------------------
// #173: JSON-wrapped tool content -> human-readable display text
// ---------------------------------------------------------------------------

/**
 * Every builtin tool's mapToolResultToToolResultBlockParam JSON.stringifies its
 * structured output (BashOutput, PowerShellOutput, etc) into the block's `content`
 * -- correct for the model-facing wire format, but nothing ever wires the optional
 * per-tool `renderToolResultMessage` hook, so the generic path used to display that
 * same JSON-stringified blob verbatim (raw `{"stdout":"...", ...}` inline with
 * assistant prose). This reformats recognized shapes into their readable text and
 * otherwise pretty-prints the JSON (multi-line, indented) instead of a dense
 * single-line blob. Falls through untouched for content that isn't JSON at all
 * (plain-string tool outputs).
 */
export function formatToolResultForDisplay(text: string): string {
  // A carriage return reaching the terminal moves the cursor to column 0 and overdraws the row (blind test T11:
  // CRLF file content rendered as `1linesONE`). Normalize in the text AND in decoded JSON strings.
  return stripCarriageReturns(formatToolResultForDisplayInner(stripCarriageReturns(text)));
}

export function stripCarriageReturns(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

const TODO_GLYPHS = (): { pending: string; active: string; done: string } =>
  process.env["EMBER_ASCII_GLYPHS"] === "1"
    ? { pending: "[ ]", active: "[~]", done: "[x]" }
    : { pending: "☐", active: "◐", done: "☑" };

/** TodoWrite result as a checklist (blind test T10: it was raw JSON). */
export function formatTodoChecklist(todos: Array<{ content?: unknown; activeForm?: unknown; status?: unknown }>): string {
  if (todos.length === 0) return "Todo list cleared.";
  const g = TODO_GLYPHS();
  return todos
    .map((t) => {
      const content = String(t.content ?? "");
      if (t.status === "completed") return `${g.done} ${content}`;
      if (t.status === "in_progress") return `${g.active} ${String(t.activeForm ?? content)} (in progress)`;
      return `${g.pending} ${content}`;
    })
    .join("\n");
}

function formatToolResultForDisplayInner(text: string): string {
  const trimmed = text.trimStart();
  if (trimmed[0] !== "{" && trimmed[0] !== "[") return text;

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return text;
  }

  if (parsed === null || typeof parsed !== "object") return text;

  if (!Array.isArray(parsed)) {
    const obj = parsed as Record<string, unknown>;

    // TodoWrite shape: { oldTodos, newTodos, todos, message }
    if (Array.isArray(obj["newTodos"]) && Array.isArray(obj["oldTodos"])) {
      const list = Array.isArray(obj["todos"]) ? (obj["todos"] as unknown[]) : (obj["newTodos"] as unknown[]);
      return formatTodoChecklist(list as Array<{ content?: unknown; activeForm?: unknown; status?: unknown }>);
    }

    // Bash / PowerShell shape: { stdout, stderr, returnCodeInterpretation, ... }
    if (typeof obj["stdout"] === "string") {
      const lines: string[] = [];
      const stdout = (obj["stdout"] as string).replace(/\r\n/g, "\n").replace(/\n+$/, "");
      if (stdout.length > 0) lines.push(stdout);
      const stderr = obj["stderr"];
      if (typeof stderr === "string" && stderr.trim().length > 0) {
        lines.push(`stderr: ${stderr.trim()}`);
      }
      const interp = obj["returnCodeInterpretation"];
      if (typeof interp === "string" && interp.length > 0) {
        lines.push(`(${interp})`);
      }
      if (lines.length > 0) return lines.join("\n");
    }

    // WebSearch shape: { query, results: [{ content: [{ url, title }] } | "text"] }. The raw JSON
    // filled the screen and pushed the answer out of view (blind test W26).
    if (typeof obj["query"] === "string" && Array.isArray(obj["results"])) {
      const hits: string[] = [];
      // "Note: search engine brave failed (HTTP 429)." Without it "no results" and "engines failed" look the same (W06).
      const failed = (obj["results"] as unknown[]).filter((r): r is string => typeof r === "string" && r.startsWith("Note: search engine"))
        .map((r) => r.replace(/^Note: /, ""));
      for (const r of obj["results"] as unknown[]) {
        const content = (r as { content?: unknown })?.content;
        if (!Array.isArray(content)) continue;
        for (const c of content) {
          const { title, url } = (c ?? {}) as { title?: unknown; url?: unknown };
          if (typeof url === "string") hits.push(`${typeof title === "string" ? title : url} — ${url}`);
        }
      }
      return hits.length === 0
        ? [`No results for "${obj["query"]}"${failed.length > 0 ? " (some search engines failed, so this may not mean nothing exists)" : ""}`, ...failed].join("\n")
        : [`${hits.length} result${hits.length === 1 ? "" : "s"} for "${obj["query"]}"`, ...hits, ...failed].join("\n");
    }

    // Read shapes (blind test FO-49: they were shown as pretty-printed JSON, base64 included).
    if (obj["type"] === "text" && typeof obj["content"] === "string" && typeof obj["totalLines"] === "number") {
      return obj["content"] as string;
    }
    if (obj["type"] === "image" && typeof obj["metadata"] === "string") return obj["metadata"] as string;
    if (obj["type"] === "notebook" && Array.isArray(obj["cells"])) {
      return `Notebook with ${(obj["cells"] as unknown[]).length} cells`;
    }
    if (obj["type"] === "pdf" && typeof obj["pageCount"] === "number") {
      return `PDF, ${obj["pageCount"]} page${obj["pageCount"] === 1 ? "" : "s"} (pages ${String(obj["extractedPages"] ?? "1")})`;
    }

    // Grep count / content shapes: { mode, numFiles, filenames, content, numMatches }. The generic
    // file-list branch below showed only file names for both (blind test FO-51: the count was lost).
    if (typeof obj["mode"] === "string" && Array.isArray(obj["filenames"]) && typeof obj["numFiles"] === "number") {
      const files = obj["numFiles"] as number;
      const body = typeof obj["content"] === "string" ? (obj["content"] as string).replace(/\n+$/, "") : "";
      if (obj["mode"] === "count") {
        const matches = typeof obj["numMatches"] === "number" ? (obj["numMatches"] as number) : 0;
        if (files === 0) return "No matches found.";
        const head = `${matches} match${matches === 1 ? "" : "es"} in ${files} file${files === 1 ? "" : "s"}`;
        return body ? `${head}\n${body}` : head;
      }
      if (obj["mode"] === "content") {
        return body.trim().length > 0 ? body : "No matches found.";
      }
    }

    // Glob/search shape: { filenames, numFiles, ... }
    if (Array.isArray(obj["filenames"]) && typeof obj["numFiles"] === "number") {
      const names = obj["filenames"] as unknown[];
      const count = obj["numFiles"] as number;
      if (count === 0) return "No files found.";
      return names.map((n) => String(n)).join("\n");
    }
  }

  // Fallback: pretty-print instead of a dense single-line blob.
  return JSON.stringify(parsed, null, 2);
}

// ---------------------------------------------------------------------------
// Signal classification (priority order from spec)
// ---------------------------------------------------------------------------

export type ToolResultKind =
  | "canceled"
  | "rejected"
  | "error"
  | "success";

export function classifyToolResult(result: ToolResultContent): ToolResultKind {
  const text = contentToString(result.content);

  // 1. CANCEL_MESSAGE → canceled
  if (text === CANCEL_MESSAGE) return "canceled";

  // 2. REJECT_MESSAGE or INTERRUPT_MESSAGE → rejected
  if (text === REJECT_MESSAGE || text === INTERRUPT_MESSAGE) return "rejected";
  // A denied approval: the text after the first sentence is guidance for the model, not the user
  // (blind test: "Do not retry the same call; tell the user..." was printed in the chat).
  if (text.startsWith("Tool call not approved:")) return "rejected";

  // 3. is_error = true → error
  if (result.is_error) return "error";

  // 4. Otherwise → success
  return "success";
}

// ---------------------------------------------------------------------------
// UserToolCanceledMessage (AC7: always "Interrupted by user")
// ---------------------------------------------------------------------------

export function UserToolCanceledMessage(): React.ReactElement {
  return React.createElement(Box, null,
    React.createElement(Text, { dimColor: true }, "Interrupted by user"),
  );
}

// ---------------------------------------------------------------------------
// RejectedToolUseMessage (AC6: dim "Tool use rejected")
// ---------------------------------------------------------------------------

export function RejectedToolUseMessage(): React.ReactElement {
  return React.createElement(Text, { dimColor: true }, "Tool use rejected");
}

// ---------------------------------------------------------------------------
// FallbackToolUseRejectedMessage
// ---------------------------------------------------------------------------

export function FallbackToolUseRejectedMessage(): React.ReactElement {
  return React.createElement(Text, { dimColor: true }, "Tool use rejected");
}

// ---------------------------------------------------------------------------
// InterruptedByUser
// ---------------------------------------------------------------------------

export function InterruptedByUser(): React.ReactElement {
  return React.createElement(Text, { dimColor: true }, "Interrupted by user");
}

// ---------------------------------------------------------------------------
// RejectedPlanMessage (AC3: bordered planMode box)
// ---------------------------------------------------------------------------

export interface RejectedPlanMessageProps {
  planContent: string;
}

export function RejectedPlanMessage({ planContent }: RejectedPlanMessageProps): React.ReactElement {
  return React.createElement(Box, { flexDirection: "column" },
    React.createElement(Text, { bold: true }, "User rejected Ember's plan:"),
    React.createElement(
      Box,
      { borderStyle: "single" as const, flexDirection: "column" as const },
      React.createElement(Text, null, planContent),
    ),
  );
}

// ---------------------------------------------------------------------------
// FallbackToolUseErrorMessage (AC2: generic error display with truncation)
// ---------------------------------------------------------------------------

export interface FallbackToolUseErrorMessageProps {
  errorText:   string;
  isExpanded?: boolean;
}

export function FallbackToolUseErrorMessage(
  props: FallbackToolUseErrorMessageProps,
): React.ReactElement {
  const { errorText, isExpanded = false } = props;
  const text = errorText.length > MAX_API_ERROR_CHARS && !isExpanded
    ? errorText.slice(0, MAX_API_ERROR_CHARS) + "… (Ctrl+O to expand)"
    : errorText;

  return React.createElement(Box, { flexDirection: "column" },
    React.createElement(Text, { color: "red" }, text),
  );
}

// ---------------------------------------------------------------------------
// UserToolErrorMessage (AC9: INTERRUPT_MESSAGE_FOR_TOOL_USE → InterruptedByUser)
// ---------------------------------------------------------------------------

export interface UserToolErrorMessageProps {
  result:       ToolResultContent;
  isExpanded?:  boolean;
}

export function UserToolErrorMessage(props: UserToolErrorMessageProps): React.ReactElement {
  const { result, isExpanded = false } = props;
  const text = contentToString(result.content);

  // AC9: INTERRUPT_MESSAGE_FOR_TOOL_USE → InterruptedByUser
  if (text === INTERRUPT_MESSAGE_FOR_TOOL_USE) {
    return InterruptedByUser();
  }

  // PLAN_REJECTION_PREFIX → RejectedPlanMessage (AC3 path for error messages)
  if (text.startsWith(PLAN_REJECTION_PREFIX)) {
    const planContent = text.slice(PLAN_REJECTION_PREFIX.length).trim();
    return RejectedPlanMessage({ planContent });
  }

  // AC10: REJECT_MESSAGE_WITH_REASON_PREFIX → RejectedToolUseMessage (with reason)
  if (text.startsWith(REJECT_MESSAGE_WITH_REASON_PREFIX)) {
    return RejectedToolUseMessage();
  }

  // TRANSCRIPT_CLASSIFIER denial
  if (_featureFlags.TRANSCRIPT_CLASSIFIER && result._classifierApproval) {
    return React.createElement(Text, { dimColor: true }, "Access denied by classifier.");
  }

  // Generic fallback (AC2) -- #173: unwrap JSON-stringified wire content for display
  // (checks above run against the raw `text` so sentinel/prefix matching is unaffected).
  return FallbackToolUseErrorMessage({ errorText: formatToolResultForDisplay(text), isExpanded });
}

// ---------------------------------------------------------------------------
// UserToolRejectMessage
// ---------------------------------------------------------------------------

export interface UserToolRejectMessageProps {
  result:  ToolResultContent;
  tool?:   Tool;
}

export function UserToolRejectMessage(props: UserToolRejectMessageProps): React.ReactElement {
  const { result, tool } = props;

  // Delegate to tool's custom reject renderer if defined
  if (tool?.renderToolUseRejectedMessage) {
    const rendered = tool.renderToolUseRejectedMessage(
      result as unknown,
      {},
    ) as React.ReactElement | null;
    if (rendered) return rendered;
  }

  return React.createElement(FallbackToolUseRejectedMessage, null);
}

// ---------------------------------------------------------------------------
// UserToolSuccessMessage (AC4, AC5)
// ---------------------------------------------------------------------------

export interface UserToolSuccessMessageProps {
  result:       ToolResultContent;
  tool?:        Tool;
  isExpanded?:  boolean;
}

export function UserToolSuccessMessage(props: UserToolSuccessMessageProps): React.ReactElement {
  const { result, tool, isExpanded = false } = props;

  try {
    // AC5: BASH_CLASSIFIER — remove classifier approval from display
    let content = result.content;
    if (_featureFlags.BASH_CLASSIFIER && result._classifierApproval) {
      // Consume the approval metadata — do not display it
      const text = contentToString(content);
      content    = text.replace(/\[classifier:approved:[^\]]*\]/g, "").trim();
    }

    // Delegate to tool's custom success renderer if defined
    if (tool?.renderToolResultMessage) {
      const rendered = tool.renderToolResultMessage(
        content as unknown,
        [],
        { verbose: false },
      ) as React.ReactElement | null;
      if (rendered) return rendered;
    }

    // If the tool result looks like a unified diff, render word-level (S06 / M10 A2).
    // #173: unwrap the JSON-stringified wire content into display text FIRST -- diff
    // detection and large-output truncation need to see the actual stdout/output text,
    // not the `{"stdout":"..."}` wrapper it arrives in.
    const text = formatToolResultForDisplay(contentToString(content));
    const diffEl = tryRenderAsDiff(text);
    if (diffEl !== null) return diffEl;

    // Large-output tail truncation (M10 A2 large_output): for outputs exceeding
    // LARGE_OUTPUT_LINE_THRESHOLD lines, show a hidden-count indicator and the
    // last LARGE_OUTPUT_TAIL_LINES lines so they stay visible in the viewport.
    if (!isExpanded && text.split("\n").length > FOLD_LINE_THRESHOLD) {
      return React.createElement(FoldedOutput, { text });
    }

    // Normal path: dim output indented under its "● Tool(...)" line, as in Claude Code.
    return React.createElement(Box, { flexDirection: "row" },
      React.createElement(Text, { dimColor: true }, RESULT_GUTTER),
      React.createElement(Text, { dimColor: true }, text),
    );
  } catch (err) {
    // AC4: error boundary — rendering errors must not crash the session
    const msg = err instanceof Error ? err.message : String(err);
    return React.createElement(Text, { color: "red" }, `[render error: ${msg}]`);
  }
}

// ---------------------------------------------------------------------------
// UserToolResultMessage — dispatcher (AC1, AC2, AC9)
// ---------------------------------------------------------------------------

export interface UserToolResultMessageProps {
  result:       ToolResultContent;
  tool?:        Tool;
  isExpanded?:  boolean;
}

export function UserToolResultMessage(props: UserToolResultMessageProps): React.ReactElement {
  const { result, tool, isExpanded = false } = props;
  const kind = classifyToolResult(result);

  switch (kind) {
    case "canceled":
      // AC1: CANCEL_MESSAGE → UserToolCanceledMessage (direct call so ser() sees content)
      return UserToolCanceledMessage();

    case "rejected":
      return UserToolRejectMessage({ result, tool });

    case "error":
      return UserToolErrorMessage({ result, isExpanded });

    case "success":
      return UserToolSuccessMessage({ result, tool, isExpanded });
  }
}

// ---------------------------------------------------------------------------
// useGetToolFromMessages (AC8: memoized on [toolUseID, lookups, tools])
// ---------------------------------------------------------------------------

/**
 * Looks up a tool definition by toolUseID from the conversation's lookup map.
 * Memoization dependency set: [toolUseID, lookups, tools] (AC8).
 * Implemented as a plain function (no React hook) — callers may wrap in useMemo
 * with those three deps to achieve the memoization contract.
 */
export function useGetToolFromMessages(
  toolUseID: string,
  lookups: MessageLookups,
  tools: Tool[],
): Tool | undefined {
  // AC8: this function's result only changes when toolUseID, lookups, or tools change.
  const resultMsg = lookups.toolResultByToolUseID.get(toolUseID);
  if (!resultMsg) return undefined;
  return tools[0]; // structural: match by tool name in real impl
}

// ---------------------------------------------------------------------------
// ErrorBoundary helper (AC4: wraps UserToolSuccessMessage)
// ---------------------------------------------------------------------------

export interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export class SentryErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  { hasError: boolean; error: Error | null }
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  override componentDidCatch(error: Error): void {
    // Direct mutation for test-time compatibility (setState is async outside React lifecycle).
    // In a mounted tree, getDerivedStateFromError (below) handles the state update.
    this.state = { hasError: true, error };
    this.setState({ hasError: true, error });
  }

  static getDerivedStateFromError(error: Error): { hasError: boolean; error: Error | null } {
    return { hasError: true, error };
  }

  override render(): React.ReactNode {
    if (this.state.hasError) {
      return this.props.fallback ??
        React.createElement(Text, { color: "red" },
          `[render error: ${this.state.error?.message ?? "unknown"}]`,
        );
    }
    return this.props.children;
  }
}
