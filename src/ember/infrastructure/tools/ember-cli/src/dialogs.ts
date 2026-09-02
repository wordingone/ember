// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// dialogs.ts — root-level dialog module.
// Extends and re-exports components/dialogs.ts with additional exports needed
// by the root-level test (ExitDialog, SearchDialog, HistoryDialog, etc.).

export { computeUsagePercent, CostDialog } from "./components/dialogs.ts";

/** Shape for cost/usage tracking — { current: number; limit: number }. */
export interface UsageCounter { current: number; limit: number; }

import React from "react";
import { Box, Text } from "./ink/components.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const AUTO_DISMISS_MS = 30_000;

// ---------------------------------------------------------------------------
// Types (exported for test import)
// ---------------------------------------------------------------------------

export interface TaskRegistry {
  pendingCount: number;
}

export interface Message {
  id:   string;
  text: string;
}

export interface SessionEntry {
  id:      string;
  date:    string;
  cwd:     string;
  snippet: string;
}

export interface SessionStore {
  list: () => SessionEntry[];
  open: (id: string) => void;
}

// ---------------------------------------------------------------------------
// AC1: hasPendingTasks
// ---------------------------------------------------------------------------

export function hasPendingTasks(tasks: TaskRegistry | undefined): boolean {
  if (!tasks) return false;
  return tasks.pendingCount > 0;
}

// ---------------------------------------------------------------------------
// AC4: fuzzyMatch
// ---------------------------------------------------------------------------

export function fuzzyMatch(query: string, messages: Message[]): Message[] {
  if (!query) return messages;
  const q = query.toLowerCase();

  return messages.filter((m) => {
    const text = m.text.toLowerCase();
    // Check subsequence match
    let qi = 0;
    for (let i = 0; i < text.length && qi < q.length; i++) {
      if (text[i] === q[qi]) qi++;
    }
    return qi === q.length;
  });
}

// ---------------------------------------------------------------------------
// AC7: isIdeConnectionAutoDismiss
// ---------------------------------------------------------------------------

export function isIdeConnectionAutoDismiss(
  status: "connected" | "disconnected" | string,
): boolean {
  return status === "connected";
}

// ---------------------------------------------------------------------------
// AC9: onboardingSupportsBack
// ---------------------------------------------------------------------------

export function onboardingSupportsBack(): boolean {
  return false;
}

// ---------------------------------------------------------------------------
// AC8: SnapshotUpdateDialog (renders null per spec)
// ---------------------------------------------------------------------------

export function SnapshotUpdateDialog(): React.ReactElement | null {
  return null;
}

// ---------------------------------------------------------------------------
// AC1: ExitDialog
// ---------------------------------------------------------------------------

export interface ExitDialogProps {
  tasks?:   TaskRegistry;
  onYes:    () => void;
  onNo:     () => void;
  onWait:   () => void;
}

export function ExitDialog(props: ExitDialogProps): React.ReactElement {
  const pending = hasPendingTasks(props.tasks);
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(
      Text, { bold: true },
      pending ? `Warning: ${props.tasks!.pendingCount} task(s) still running.` : "Exit?",
    ),
    React.createElement(
      Box, { flexDirection: "row", gap: 2, marginTop: 1 },
      React.createElement(Text, { key: "y" }, "(y)es"),
      React.createElement(Text, { key: "n" }, "(n)o"),
      React.createElement(Text, { key: "w" }, "(w)ait"),
    ),
  );
}

// ---------------------------------------------------------------------------
// AC3: InvalidConfigDialog
// ---------------------------------------------------------------------------

export interface InvalidConfigError {
  filePath: string;
  message:  string;
}

export interface InvalidConfigDialogProps {
  error:                  InvalidConfigError;
  onEdit:                 () => void;
  onContinueWithDefaults: () => void;
}

export function InvalidConfigDialog(
  props: InvalidConfigDialogProps,
): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", borderColor: "red", padding: 1 },
    React.createElement(Text, { bold: true, color: "red" }, "Invalid config"),
    React.createElement(Text, null, props.error.filePath),
    React.createElement(Text, { dimColor: true }, props.error.message),
  );
}

// ---------------------------------------------------------------------------
// AC4: SearchDialog
// ---------------------------------------------------------------------------

export interface SearchDialogProps {
  messages?:   Message[];
  onSelect?:   (msg: Message) => void;
  onDismiss?:  () => void;
}

export function SearchDialog(props: SearchDialogProps): React.ReactElement {
  const messages = props.messages ?? [];
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, "Search"),
    ...messages.map((m) =>
      React.createElement(Text, { key: m.id }, m.text),
    ),
  );
}

// ---------------------------------------------------------------------------
// AC6: HistoryDialog
// ---------------------------------------------------------------------------

export interface HistoryDialogProps {
  store:      SessionStore;
  onDismiss?: () => void;
}

export function HistoryDialog(props: HistoryDialogProps): React.ReactElement {
  const entries = props.store.list();
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, "Session history"),
    ...entries.map((e) =>
      React.createElement(Text, { key: e.id }, `${e.date} — ${e.snippet}`),
    ),
  );
}

// ---------------------------------------------------------------------------
// AC7: IdeStatusIndicator
// ---------------------------------------------------------------------------

export interface IdeStatusIndicatorProps {
  status:     "connected" | "disconnected" | string;
  onDismiss?: () => void;
}

export function IdeStatusIndicator(
  props: IdeStatusIndicatorProps,
): React.ReactElement {
  const color = props.status === "connected" ? "green" : "red";
  return React.createElement(
    Box, { flexDirection: "row" },
    React.createElement(Text, { color }, `IDE: ${props.status}`),
  );
}

// ---------------------------------------------------------------------------
// AC9: OnboardingFlow
// ---------------------------------------------------------------------------

export interface OnboardingPanel {
  title:   string;
  content: string;
}

export interface OnboardingFlowProps {
  type:     "Onboarding" | "IdeOnboarding" | "EmberInChromeOnboarding" | string;
  panels:   OnboardingPanel[];
  onDone:   () => void;
}

export function OnboardingFlow(props: OnboardingFlowProps): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true }, props.type),
    ...props.panels.map((p, i) =>
      React.createElement(
        Box, { key: String(i), flexDirection: "column" },
        React.createElement(Text, { bold: true }, p.title),
        React.createElement(Text, null, p.content),
      ),
    ),
  );
}
