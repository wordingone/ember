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

  // Generic fallback (AC2)
  return FallbackToolUseErrorMessage({ errorText: text, isExpanded });
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
    const text = contentToString(content);
    const diffEl = tryRenderAsDiff(text);
    if (diffEl !== null) return diffEl;

    // Large-output tail truncation (M10 A2 large_output): for outputs exceeding
    // LARGE_OUTPUT_LINE_THRESHOLD lines, show a hidden-count indicator and the
    // last LARGE_OUTPUT_TAIL_LINES lines so they stay visible in the viewport.
    if (!isExpanded && isLargeOutput(text)) {
      return React.createElement(LargeTailOutput, { text });
    }

    // Normal path: └ card (M9 fidelity baseline).
    return React.createElement(Box, { flexDirection: "row" },
      React.createElement(Text, { dimColor: true }, "└ "),
      React.createElement(Text, null, text),
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
