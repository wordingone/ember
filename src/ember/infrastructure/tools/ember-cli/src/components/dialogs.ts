// dialogs.ts — modal dialog components: idle-return and cost-threshold.
// Bundle: components/dialogs.ts (line 321646)

import React from "react";
import { Box, Text } from "../ink/components.ts";
import { useInput } from "../ink/hooks.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UsageLimits {
  current: number;
  limit:   number;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function computeUsagePercent(usage: UsageLimits): number {
  if (usage.limit <= 0) return 0;
  return Math.round((usage.current / usage.limit) * 1000) / 10;
}

// ---------------------------------------------------------------------------
// IdleReturnDialog — shown after returning to a session with completed tasks
// ---------------------------------------------------------------------------

export interface IdleReturnDialogProps {
  completedTaskCount: number;
  onContinue:         () => void;
}

export function IdleReturnDialog({
  completedTaskCount,
  onContinue,
}: IdleReturnDialogProps): React.ReactElement {
  useInput((_i, key) => {
    if (key.return || key.escape) onContinue();
  });

  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { key: "msg" },
      `${completedTaskCount} background task(s) completed while away.`),
    React.createElement(Text, { key: "hint", dimColor: true },
      "Press Enter to continue."),
  );
}

// ---------------------------------------------------------------------------
// CostDialog — shown when session cost approaches the configured budget
// ---------------------------------------------------------------------------

export interface CostDialogProps {
  usage:      UsageLimits;
  onContinue: () => void;
  onStop:     () => void;
}

export function CostDialog({
  usage,
  onContinue,
  onStop,
}: CostDialogProps): React.ReactElement {
  const pct = computeUsagePercent(usage);

  useInput((input) => {
    if (input === "c") { onContinue(); return; }
    if (input === "s") { onStop();     return; }
  });

  return React.createElement(
    Box,
    { flexDirection: "column", borderStyle: "single", borderColor: "yellow", padding: 1 },
    React.createElement(Text, { key: "title", bold: true, color: "yellow" }, "Usage limit warning"),
    React.createElement(Text, { key: "pct" }, `Current usage: ${pct}% of session budget`),
    React.createElement(
      Box, { key: "opts", flexDirection: "row", gap: 2, marginTop: 1 },
      React.createElement(Text, { key: "c" }, "(c)ontinue"),
      React.createElement(Text, { key: "s" }, "(s)top"),
    ),
  );
}
