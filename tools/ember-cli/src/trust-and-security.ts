// trust-and-security.ts — project trust dialog and managed-settings security
// dialog utilities.

import React from "react";
import { Box, Text } from "./ink/components.ts";

// ---------------------------------------------------------------------------
// Analytics event constants (AC3)
// ---------------------------------------------------------------------------

export const TRUST_DIALOG_SHOWN_EVENT  = "ember_trust_dialog_shown";
export const TRUST_DIALOG_ACCEPT_EVENT = "ember_trust_dialog_accept";

// ---------------------------------------------------------------------------
// Dangerous shell settings (AC7)
// ---------------------------------------------------------------------------

export const DANGEROUS_SHELL_SETTINGS: readonly string[] = [
  "aliases",
  "BASH_ENV",
  "ENV",
  "PROMPT_COMMAND",
  "CDPATH",
  "FPATH",
  "PS1",
  "PS2",
] as const;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProjectConfig {
  mcpServers?:  Array<Record<string, unknown>>;
  hooks?:       string[];
  bashRules?:   string[];
}

export interface ManagedSettings {
  envVars?:        Record<string, string>;
  allowedEnvVars?: Set<string>;
  shellSettings?:  Record<string, string>;
}

export interface DangerousEntry {
  name:   string;
  value:  string;
  reason: "unapproved-env-var" | "dangerous-shell-setting";
}

// ---------------------------------------------------------------------------
// AC1/AC2/AC6: shouldShowTrustDialog
// ---------------------------------------------------------------------------

export function shouldShowTrustDialog(config: ProjectConfig): boolean {
  if (config.mcpServers && config.mcpServers.length > 0) return true;
  if (config.hooks      && config.hooks.length > 0)       return true;
  if (config.bashRules  && config.bashRules.length > 0)   return true;
  return false;
}

// ---------------------------------------------------------------------------
// AC4/AC5: getTrustSavePath
// ---------------------------------------------------------------------------

export function getTrustSavePath(
  destination: "session" | "project",
  homeDir:     string,
  projectDir:  string,
): string {
  if (destination === "session") {
    return `${homeDir}/.ember/session-trust.json`;
  }
  return `${projectDir}/.ember/trust.json`;
}

// ---------------------------------------------------------------------------
// AC7/AC8: hasDangerousSettings / hasDangerousSettingsChanged
// ---------------------------------------------------------------------------

export function hasDangerousSettings(settings: ManagedSettings): boolean {
  return extractDangerousSettings(settings).length > 0;
}

export function hasDangerousSettingsChanged(
  before: ManagedSettings,
  after:  ManagedSettings,
): boolean {
  const wasDangerous = hasDangerousSettings(before);
  const isDangerous  = hasDangerousSettings(after);
  return wasDangerous !== isDangerous;
}

// ---------------------------------------------------------------------------
// AC9: extractDangerousSettings
// ---------------------------------------------------------------------------

export function extractDangerousSettings(
  settings: ManagedSettings,
): DangerousEntry[] {
  const dangerous: DangerousEntry[] = [];

  // Env vars not in allowlist
  if (settings.envVars) {
    const allowed = settings.allowedEnvVars ?? new Set<string>();
    for (const [name, value] of Object.entries(settings.envVars)) {
      if (!allowed.has(name)) {
        dangerous.push({ name, value, reason: "unapproved-env-var" });
      }
    }
  }

  // Shell settings
  if (settings.shellSettings) {
    for (const [name, value] of Object.entries(settings.shellSettings)) {
      if (DANGEROUS_SHELL_SETTINGS.includes(name)) {
        dangerous.push({ name, value, reason: "dangerous-shell-setting" });
      }
    }
  }

  return dangerous;
}

// ---------------------------------------------------------------------------
// AC10: formatListWithAnd
// ---------------------------------------------------------------------------

export function formatListWithAnd(items: string[]): string {
  if (items.length === 0) return "";
  if (items.length === 1) return items[0]!;
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  const allButLast = items.slice(0, -1).join(", ");
  return `${allButLast}, and ${items[items.length - 1]}`;
}

// ---------------------------------------------------------------------------
// formatDangerousSettingsList
// ---------------------------------------------------------------------------

export function formatDangerousSettingsList(entries: DangerousEntry[]): string {
  if (entries.length === 0) return "(none)";
  return entries.map((e) => `${e.name}=${e.value}`).join(", ");
}

// ---------------------------------------------------------------------------
// getHooksSources
// ---------------------------------------------------------------------------

export function getHooksSources(hooks: string[]): string[] {
  return [...hooks];
}

// ---------------------------------------------------------------------------
// getBashPermissionSources
// ---------------------------------------------------------------------------

export function getBashPermissionSources(rules: string[]): string[] {
  return rules.map((_, i) => `Rule ${i + 1}`);
}

// ---------------------------------------------------------------------------
// React components (structural)
// ---------------------------------------------------------------------------

export interface TrustDialogProps {
  config:    ProjectConfig;
  onAccept?: () => void;
  onReject?: () => void;
}

export function TrustDialog(props: TrustDialogProps): React.ReactElement {
  const sources: string[] = [];
  if (props.config.mcpServers?.length) sources.push("MCP servers");
  if (props.config.hooks?.length)      sources.push("hooks");

  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", padding: 1 },
    React.createElement(Text, { bold: true, color: "yellow" }, "Trust this project?"),
    React.createElement(
      Text, null,
      sources.length > 0
        ? `This project has: ${formatListWithAnd(sources)}.`
        : "No special configuration detected.",
    ),
  );
}

export interface ManagedSettingsSecurityDialogProps {
  settings:   ManagedSettings;
  onAccept?:  () => void;
  onReject?:  () => void;
}

export function ManagedSettingsSecurityDialog(
  props: ManagedSettingsSecurityDialogProps,
): React.ReactElement {
  const dangerous = extractDangerousSettings(props.settings);
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", borderColor: "red", padding: 1 },
    React.createElement(Text, { bold: true, color: "red" }, "Security warning"),
    React.createElement(
      Text, null,
      formatDangerousSettingsList(dangerous),
    ),
  );
}
