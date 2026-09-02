// settings-dialog.ts — settings dialog with tabbed navigation.

import React from "react";
import { Box, Text } from "./ink/components.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const BAR_WIDTH          = 50;
export const CONDENSED_THRESHOLD = 62;

// ---------------------------------------------------------------------------
// Types (exported for test import)
// ---------------------------------------------------------------------------

export type SettingsTab = "Status" | "Config" | "Usage" | "Gates";

export const SETTINGS_TABS: SettingsTab[] = ["Status", "Config", "Usage", "Gates"];

export interface McpServerStatus {
  name:   string;
  status: "connected" | "error" | "pending" | "disconnected";
}

export interface SessionMeta {
  version:         string;
  sessionId:       string;
  cwd:             string;
  account:         string;
  apiProvider:     string;
  model:           string;
  ide?:            string;
  mcpServers:      McpServerStatus[];
  sandboxMode:     string;
  settingsSources: string[];
}

export interface UsageData {
  tokensBudget?:   number;
  tokensUsed?:     number;
  costBudget?:     number;
  costUsed?:       number;
}

// ---------------------------------------------------------------------------
// AC2/AC6: Tab cycling
// ---------------------------------------------------------------------------

export function cycleTabLeft(current: SettingsTab): SettingsTab {
  const idx = SETTINGS_TABS.indexOf(current);
  const prev = (idx - 1 + SETTINGS_TABS.length) % SETTINGS_TABS.length;
  return SETTINGS_TABS[prev]!;
}

export function cycleTabRight(current: SettingsTab): SettingsTab {
  const idx  = SETTINGS_TABS.indexOf(current);
  const next = (idx + 1) % SETTINGS_TABS.length;
  return SETTINGS_TABS[next]!;
}

// ---------------------------------------------------------------------------
// AC4: Condensed layout detection
// ---------------------------------------------------------------------------

export function isCondensedLayout(columns: number): boolean {
  return columns < CONDENSED_THRESHOLD;
}

// ---------------------------------------------------------------------------
// AC4/AC5: renderLimitBar
// ---------------------------------------------------------------------------

export function renderLimitBar(ratio: number, columns: number): string {
  const clamped = Math.max(0, Math.min(1, ratio));
  const width   = isCondensedLayout(columns) ? Math.round((columns / 80) * BAR_WIDTH) : BAR_WIDTH;
  const filled  = Math.round(clamped * width);
  const empty   = width - filled;
  return "█".repeat(filled) + "░".repeat(empty);
}

// ---------------------------------------------------------------------------
// AC8: StatusTab
// ---------------------------------------------------------------------------

export interface StatusTabProps {
  meta: SessionMeta;
}

export function StatusTab(props: StatusTabProps): React.ReactElement {
  const { meta } = props;
  return React.createElement(
    Box, { flexDirection: "column" },
    React.createElement(Text, { bold: true }, `Ember ${meta.version}`),
    React.createElement(Text, null, `Session: ${meta.sessionId}`),
    React.createElement(Text, null, `Model: ${meta.model}`),
    React.createElement(Text, null, `Provider: ${meta.apiProvider}`),
    React.createElement(Text, null, `CWD: ${meta.cwd}`),
    React.createElement(Text, null, `Sandbox: ${meta.sandboxMode}`),
    ...meta.mcpServers.map((s) =>
      React.createElement(
        Text, { key: s.name },
        `MCP: ${s.name} [${s.status}]`,
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// UsageTab
// ---------------------------------------------------------------------------

export interface UsageTabProps {
  usage?: UsageData;
  columns?: number;
}

export function UsageTab(props: UsageTabProps): React.ReactElement {
  const { usage = {}, columns = 80 } = props;
  const ratio  = (usage.tokensUsed ?? 0) / Math.max(1, usage.tokensBudget ?? 1);
  const bar    = renderLimitBar(ratio, columns);
  return React.createElement(
    Box, { flexDirection: "column" },
    React.createElement(Text, { bold: true }, "Usage"),
    React.createElement(Text, null, bar),
  );
}

// ---------------------------------------------------------------------------
// LimitBar component
// ---------------------------------------------------------------------------

export interface LimitBarProps {
  ratio:    number;
  columns?: number;
}

export function LimitBar(props: LimitBarProps): React.ReactElement {
  const bar = renderLimitBar(props.ratio, props.columns ?? 80);
  return React.createElement(Text, null, bar);
}

// ---------------------------------------------------------------------------
// SettingsDialog
// ---------------------------------------------------------------------------

export interface SettingsDialogProps {
  initialTab?:      SettingsTab;
  meta?:            SessionMeta;
  usage?:           UsageData;
  columns?:         number;
  onDismiss?:       () => void;
  onRefreshMeta?:   () => void;
  onRefreshUsage?:  () => void;
}

export function SettingsDialog(props: SettingsDialogProps): React.ReactElement {
  const {
    initialTab     = "Status",
    meta,
    usage,
    columns        = 80,
    onDismiss:     _onDismiss,
    onRefreshMeta: _onRefreshMeta,
    onRefreshUsage: _onRefreshUsage,
  } = props;

  const tabRow = React.createElement(
    Box, { flexDirection: "row", gap: 2 },
    ...SETTINGS_TABS.map((tab) =>
      React.createElement(
        Text, { key: tab, bold: tab === initialTab, underline: tab === initialTab },
        tab,
      ),
    ),
  );

  let content: React.ReactElement;
  switch (initialTab) {
    case "Status":
      content = meta
        ? React.createElement(StatusTab, { meta })
        : React.createElement(Text, { dimColor: true }, "Loading…");
      break;
    case "Usage":
      content = React.createElement(UsageTab, { usage, columns });
      break;
    default:
      content = React.createElement(Text, { dimColor: true }, `${initialTab} tab`);
  }

  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    tabRow,
    content,
  );
}
