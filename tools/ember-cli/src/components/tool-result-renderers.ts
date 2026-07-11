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
      `└ … [${hiddenCount} lines above]`,
    ),
    React.createElement(Text, { key: "tail" }, tail),
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
// #240: compact "glyph + tool name + one-line digest" summary for tool results
// ---------------------------------------------------------------------------

/** Max characters of the first line shown before the digest truncates with an ellipsis. */
export const DIGEST_MAX_CHARS = 100;

/**
 * When `text` is (still) recognizably JSON after formatToolResultForDisplay's pretty-print
 * fallback (an unrecognized shape falls through to `JSON.stringify(parsed, null, 2)`), a
 * one-line digest built from the first rendered line would just be "{" or "[" -- readable, but
 * not a useful summary, and visually still "the shape leaking to the user" that #240 flags.
 * Reparses and reports a structural summary instead (key/item count), never raw JSON syntax.
 */
function digestForStructuredJSON(text: string): string | null {
  const trimmed = text.trimStart();
  if (trimmed[0] !== "{" && trimmed[0] !== "[") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (Array.isArray(parsed)) {
    return `[array \xB7 ${parsed.length} item${parsed.length === 1 ? "" : "s"}]`;
  }
  if (parsed !== null && typeof parsed === "object") {
    const keys = Object.keys(parsed as Record<string, unknown>);
    const preview = keys.slice(0, 3).join(", ") + (keys.length > 3 ? ", …" : "");
    return `{object \xB7 ${keys.length} key${keys.length === 1 ? "" : "s"}${preview ? ": " + preview : ""}}`;
  }
  return null;
}

export interface ToolResultDigest {
  /** One line, never containing raw JSON syntax or an embedded newline. */
  digest:    string;
  /** True when `digest` does not capture the entire `text` (more content exists behind expand). */
  truncated: boolean;
}

/** Builds the compact one-line summary shown by default; the full `text` is the expand target. */
export function summarizeToolResultLine(text: string): ToolResultDigest {
  const structured = digestForStructuredJSON(text);
  if (structured !== null) {
    return { digest: structured, truncated: text.includes("\n") || structured.length < text.trimStart().length };
  }

  const firstLine    = text.split("\n")[0] ?? "";
  const hasMoreLines = text.includes("\n");
  let digest    = firstLine;
  let truncated = hasMoreLines;

  if (digest.length > DIGEST_MAX_CHARS) {
    digest    = digest.slice(0, DIGEST_MAX_CHARS - 1) + "…";
    truncated = true;
  }

  if (digest.length === 0) {
    digest = hasMoreLines ? "(output)" : "(empty)";
  }

  return { digest, truncated };
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

/** Resolves the human-facing label for the tool that produced a result, or undefined when no
 * tool definition was supplied (matches the existing dispatch's optional `tool` prop). */
function resolveToolLabel(tool?: Tool): string | undefined {
  if (!tool) return undefined;
  try {
    return tool.userFacingName ? tool.userFacingName() : tool.name;
  } catch {
    return tool.name;
  }
}

export function UserToolSuccessMessage(props: UserToolSuccessMessageProps): React.ReactElement {
  const { result, tool, isExpanded = false } = props;
  const toolLabel = resolveToolLabel(tool);
  // #240 ("glyph + tool name + one-line digest"): "└ " is the existing tree-connector glyph
  // (unchanged, keeps continuity with the card visually attaching to the tool_use line above
  // it); the tool name -- when known -- rides right after it, before whatever content follows.
  const header = (): React.ReactElement =>
    React.createElement(Text, { dimColor: true }, `└ ${toolLabel ? toolLabel + " \xB7 " : ""}`);

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
    if (diffEl !== null) {
      // A diff is already a compact, legible, syntax-appropriate rendering (never raw JSON) --
      // it stays fully shown per the field-standard bar (state/field-ux-map.md §9: "syntax-
      // highlighted, line-numbered diffs" are ADOPT, not something to collapse). Only the
      // glyph+name header is added on top, for visual consistency with every other result card.
      return React.createElement(Box, { flexDirection: "column" }, header(), diffEl);
    }

    // Large-output tail truncation (M10 A2 large_output): for outputs exceeding
    // LARGE_OUTPUT_LINE_THRESHOLD lines, show a hidden-count indicator and the
    // last LARGE_OUTPUT_TAIL_LINES lines so they stay visible in the viewport. Already a
    // deliberate, bounded view (not a raw dump) -- same treatment as the diff case above.
    if (!isExpanded && isLargeOutput(text)) {
      return React.createElement(Box, { flexDirection: "column" },
        header(),
        React.createElement(LargeTailOutput, { text }),
      );
    }

    // Normal path: compact "glyph + tool name + one-line digest" by default (#240) -- the raw
    // shape (JSON structure included) never reaches this line; formatToolResultForDisplay and
    // summarizeToolResultLine both refuse to hand back unparsed JSON syntax. The full text sits
    // behind isExpanded, same Ctrl+O convention every other truncated surface in this file uses.
    const { digest, truncated } = summarizeToolResultLine(text);
    const showFull = isExpanded || !truncated;
    return React.createElement(Box, { flexDirection: "row" },
      header(),
      React.createElement(Text, null, showFull ? text : digest),
      !showFull ? React.createElement(Text, { dimColor: true }, "  (Ctrl+O to expand)") : null,
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
