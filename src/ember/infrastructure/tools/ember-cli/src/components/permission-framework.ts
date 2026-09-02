// components/permission-framework.ts — permission dialog routing, key handling,
// risk colors, multiple-choice toggles, rule reachability checks.

import React from "react";
import { Box, Text } from "../ink/components.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PermissionDestination =
  | "session"
  | "localSettings"
  | "ember-folder"
  | "global-ember-folder";

export type PermissionBehavior = "allow" | "deny";

export interface PermissionRule {
  pattern:     string;
  behavior:    PermissionBehavior;
  destination: PermissionDestination;
}

export type PermissionView =
  | "FileEditPermissionRequest"
  | "BashPermissionRequest"
  | "AskUserQuestionPermissionRequest"
  | "FallbackPermissionRequest";

export type RiskLevel = "error" | "warning" | "success" | "info";

export type PreviewAnswerState = "missing-required" | "complete" | "optional";

// ---------------------------------------------------------------------------
// AC1/AC2: View routing
// ---------------------------------------------------------------------------

const TOOL_VIEW_MAP: Record<string, PermissionView> = {
  FileEditTool:             "FileEditPermissionRequest",
  BashTool:                 "BashPermissionRequest",
  AskUserQuestionTool:      "AskUserQuestionPermissionRequest",
};

export function resolvePermissionView(toolName: string): PermissionView {
  return TOOL_VIEW_MAP[toolName] ?? "FallbackPermissionRequest";
}

// ---------------------------------------------------------------------------
// AC3: Global key handler
// ---------------------------------------------------------------------------

export function handlePermissionGlobalKey(
  key:      string,
  onReject: () => void,
): boolean {
  if (key === "q") {
    onReject();
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// AC4: Fallback options (exactly 3)
// ---------------------------------------------------------------------------

export const FALLBACK_OPTIONS: readonly string[] = [
  "Yes (allow once)",
  "No (reject)",
  "Yes, don't ask again",
] as const;

// ---------------------------------------------------------------------------
// AC5: Question header format
// ---------------------------------------------------------------------------

export function formatQuestionHeader(index: number, total: number): string {
  return `Question ${index + 1} of ${total}`;
}

// ---------------------------------------------------------------------------
// AC7: Multiple-choice toggle (immutable — returns new Set)
// ---------------------------------------------------------------------------

export function multipleChoiceToggle(
  selected: Set<string>,
  item:     string,
): Set<string> {
  const next = new Set(selected);
  if (next.has(item)) {
    next.delete(item);
  } else {
    next.add(item);
  }
  return next;
}

// ---------------------------------------------------------------------------
// AC8: Preview answer color
// ---------------------------------------------------------------------------

export function previewAnswerColor(
  state: PreviewAnswerState,
): string | undefined {
  switch (state) {
    case "missing-required": return "yellow";
    case "complete":         return "green";
    case "optional":         return undefined;
  }
}

// ---------------------------------------------------------------------------
// AC9: Rule reachability
// ---------------------------------------------------------------------------

function patternMatches(existing: string, candidate: string): boolean {
  if (existing === candidate) return true;
  if (existing === "*")       return true;
  // Simple glob: "BashTool:*" matches "BashTool:ls"
  if (existing.endsWith(":*")) {
    const prefix = existing.slice(0, -1); // "BashTool:"
    if (candidate.startsWith(prefix)) return true;
  }
  if (existing.endsWith("*")) {
    const prefix = existing.slice(0, -1);
    if (candidate.startsWith(prefix)) return true;
  }
  return false;
}

export function isRuleUnreachable(
  candidate:     string,
  existingRules: PermissionRule[],
): boolean {
  for (const rule of existingRules) {
    if (patternMatches(rule.pattern, candidate)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// AC10: Denials tab key handler
// ---------------------------------------------------------------------------

export function handleDenialsKey(
  key:       string,
  focusedId: string | undefined,
  onRetry:   (id: string) => void,
): boolean {
  if (key === "r" && focusedId !== undefined) {
    onRetry(focusedId);
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// AC12: Risk level color
// ---------------------------------------------------------------------------

export function riskLevelColor(level: RiskLevel): string {
  switch (level) {
    case "error":   return "red";
    case "warning": return "yellow";
    case "success": return "green";
    case "info":    return "cyan";
  }
}

// ---------------------------------------------------------------------------
// AC14: Workspace tab key handler
// ---------------------------------------------------------------------------

export function handleWorkspaceKey(
  key:        string,
  _modifiers: Record<string, boolean>,
  focusedDir: string | undefined,
  onAdd:      () => void,
  onRemove:   (dir: string) => void,
  onExit:     () => void,
): boolean {
  if (key === "a") { onAdd(); return true; }
  if (key === "d" && focusedDir !== undefined) { onRemove(focusedDir); return true; }
  if (key === "q") { onExit(); return true; }
  return false;
}

// ---------------------------------------------------------------------------
// permissionRuleExplanation
// ---------------------------------------------------------------------------

export interface RuleExplanation {
  hint: string;
}

export function permissionRuleExplanation(
  matchType: "allow-always" | "no-rule" | "allow-session" | "deny" | string,
): RuleExplanation {
  switch (matchType) {
    case "allow-always": return { hint: "Always allowed" };
    case "no-rule":      return { hint: "No rule" };
    case "allow-session": return { hint: "Allowed for session" };
    case "deny":          return { hint: "Denied" };
    default:              return { hint: matchType };
  }
}

// ---------------------------------------------------------------------------
// describePermissionRule
// ---------------------------------------------------------------------------

export function describePermissionRule(toolName: string, pattern: string): string {
  if (pattern === "*") {
    return `Allow all operations for ${toolName}`;
  }
  return `Allow ${toolName}: ${pattern}`;
}

// ---------------------------------------------------------------------------
// React components (structural — referenced by tests via typeof checks)
// ---------------------------------------------------------------------------

export interface PermissionExplanationProps {
  isLoading?: boolean;
  riskLevel?: RiskLevel;
  text?:      string;
}

export function PermissionExplanation(
  props: PermissionExplanationProps,
): React.ReactElement {
  if (props.isLoading) {
    return React.createElement(Text, { dimColor: true }, "Loading…");
  }
  const color = props.riskLevel ? riskLevelColor(props.riskLevel) : undefined;
  return React.createElement(
    Box, { flexDirection: "column" },
    React.createElement(Text, { color }, props.text ?? ""),
  );
}

export interface FallbackPermissionRequestProps {
  toolName?:  string;
  onAllow?:   () => void;
  onReject?:  () => void;
  onPersist?: () => void;
}

export function FallbackPermissionRequest(
  props: FallbackPermissionRequestProps,
): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, `Allow ${props.toolName ?? "tool"}?`),
    ...FALLBACK_OPTIONS.map((opt, i) =>
      React.createElement(Text, { key: String(i) }, opt),
    ),
  );
}

export interface FileEditPermissionRequestProps {
  filePath:  string;
  onAllow?:  () => void;
  onReject?: () => void;
}

export function FileEditPermissionRequest(
  props: FileEditPermissionRequestProps,
): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, `Edit file: ${props.filePath}`),
  );
}

export interface BashPermissionRequestProps {
  command:   string;
  onAllow?:  () => void;
  onReject?: () => void;
}

export function BashPermissionRequest(
  props: BashPermissionRequestProps,
): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, `Run: ${props.command}`),
  );
}

export interface AskUserQuestionPermissionRequestProps {
  questions:    string[];
  questionIndex: number;
  onSubmit?:    () => void;
  onReject?:    () => void;
}

export function AskUserQuestionPermissionRequest(
  props: AskUserQuestionPermissionRequestProps,
): React.ReactElement {
  const header = formatQuestionHeader(
    props.questionIndex,
    props.questions.length,
  );
  const minWidth = Math.max(40, 80);
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", minWidth, padding: 1 },
    React.createElement(Text, { bold: true }, header),
    React.createElement(
      Text, null,
      props.questions[props.questionIndex] ?? "",
    ),
  );
}

export interface PermissionUpdateProps {
  type:        "addRules";
  rules:       string[];
  behavior:    PermissionBehavior;
  destination: PermissionDestination;
}
