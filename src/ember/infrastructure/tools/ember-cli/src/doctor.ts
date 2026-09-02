// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// doctor.ts — diagnostics screen.

import React from "react";
import { Box, Text } from "./ink/components.ts";

// ---------------------------------------------------------------------------
// Constants (AC1/AC6)
// ---------------------------------------------------------------------------

export const DOCTOR_DONE_MESSAGE = "Ember CLI diagnostics dismissed";

export const ENV_VAR_DEFAULTS: Readonly<Record<string, number>> = {
  BASH_MAX_OUTPUT_LENGTH: 8_000,
  TASK_MAX_OUTPUT_LENGTH: 16_000,
};

export const ENV_VAR_RANGE: Readonly<{ min: number; max: number }> = {
  min: 1,
  max: 1_000_000,
};

export const SECTION_ORDER: readonly string[] = [
  "title",
  "installation",
  "recommendations",
  "multiple_installations",
  "custom_warnings",
  "invalid_settings",
  "updates",
  "sandbox",
  "mcp_warnings",
  "keybinding_warnings",
  "env_vars",
  "version_locks",
  "agent_errors",
  "plugin_errors",
  "context_usage",
] as const;

// ---------------------------------------------------------------------------
// Types (AC3/AC4/AC8/AC9/AC10/AC11/AC12)
// ---------------------------------------------------------------------------

export interface InstallInfo {
  type:                 string;
  version:              string;
  packageManager:       string;
  path:                 string;
  invokedBinary:        string;
  configInstallMethod:  string;
  ripgrepStatus:        "working" | "not_working" | "unknown";
  ripgrepMode?:         "bundled" | "vendor" | "system";
}

export interface ActiveLock {
  pid:      number;
  version:  string;
  isAlive:  boolean;
}

export interface VersionLocks {
  enabled:      boolean;
  cleanedCount: number;
  activeLocks:  ActiveLock[];
}

export interface AgentParseError {
  file:  string;
  error: string;
}

export interface PluginError {
  source:  string;
  plugin:  string;
  message: string;
}

export interface KeybindingWarning {
  type:       "reserved" | "invalid_context" | "invalid_action" | string;
  message:    string;
  keystroke?: string;
  context?:   string;
  action?:    string;
}

export interface ContextUsageWarnings {
  unreachableRules: string[];
  emberMdUsage:     string[];
  agentUsage:       string[];
  mcpServerUsage:   string[];
}

export interface EnvVarWarning {
  name:    string;
  message: string;
}

export interface DoctorScreenProps {
  cwd:                   string;
  onDone:                (message: string, opts: { display: string }) => void;
  installInfo?:          InstallInfo;
  multipleInstalls?:     string[];
  env?:                  Record<string, string>;
  versionLocks?:         VersionLocks;
  agentParseErrors?:     AgentParseError[];
  pluginErrors?:         PluginError[];
  keybindingWarnings?:   KeybindingWarning[];
  contextUsageWarnings?: ContextUsageWarnings;
}

// ---------------------------------------------------------------------------
// AC6: validateBoundedIntEnvVar
// ---------------------------------------------------------------------------

export function validateBoundedIntEnvVar(
  name:         string,
  rawValue:     string | undefined,
  defaultValue: number,
): { parsed: number; warning: EnvVarWarning | null } {
  if (rawValue === undefined) {
    return { parsed: defaultValue, warning: null };
  }

  const n = Number(rawValue);
  if (!Number.isInteger(n) || isNaN(n)) {
    return {
      parsed: defaultValue,
      warning: {
        name,
        message: `${name}: "${rawValue}" is not a valid integer; using default ${defaultValue}.`,
      },
    };
  }

  if (n < ENV_VAR_RANGE.min || n > ENV_VAR_RANGE.max) {
    return {
      parsed: defaultValue,
      warning: {
        name,
        message:
          `${name}: ${n} is outside valid range [${ENV_VAR_RANGE.min}, ${ENV_VAR_RANGE.max}]; using default ${defaultValue}.`,
      },
    };
  }

  return { parsed: n, warning: null };
}

// ---------------------------------------------------------------------------
// extractEnvVarWarnings
// ---------------------------------------------------------------------------

export function extractEnvVarWarnings(
  env: Record<string, string>,
): EnvVarWarning[] {
  const warnings: EnvVarWarning[] = [];
  for (const [name, def] of Object.entries(ENV_VAR_DEFAULTS)) {
    const raw = env[name];
    if (raw !== undefined) {
      const { warning } = validateBoundedIntEnvVar(name, raw, def);
      if (warning) warnings.push(warning);
    }
  }
  return warnings;
}

// ---------------------------------------------------------------------------
// DoctorScreen (default export + named)
// ---------------------------------------------------------------------------

export function DoctorScreen(props: DoctorScreenProps): React.ReactElement {
  const {
    installInfo,
    multipleInstalls,
    versionLocks,
    agentParseErrors,
    pluginErrors,
    keybindingWarnings,
    contextUsageWarnings,
    env,
  } = props;

  const envWarnings = env ? extractEnvVarWarnings(env) : [];

  return React.createElement(
    Box, { flexDirection: "column", padding: 1 },

    // Title section
    React.createElement(Text, { key: "title", bold: true, color: "cyan" },
      "Ember CLI — Diagnostics",
    ),

    // Installation section
    installInfo
      ? React.createElement(
          Box, { key: "install", flexDirection: "column" },
          React.createElement(Text, { bold: true }, "Installation"),
          React.createElement(Text, null, `Type: ${installInfo.type}`),
          React.createElement(Text, null, `Version: ${installInfo.version}`),
          React.createElement(Text, null, `Path: ${installInfo.path}`),
          React.createElement(Text, null, `ripgrep: ${installInfo.ripgrepStatus}`),
        )
      : null,

    // Multiple installs
    multipleInstalls && multipleInstalls.length > 1
      ? React.createElement(
          Box, { key: "multi", flexDirection: "column" },
          React.createElement(Text, { bold: true, color: "yellow" }, "Multiple installations found"),
          ...multipleInstalls.map((p) =>
            React.createElement(Text, { key: p }, p),
          ),
        )
      : null,

    // Env var warnings
    envWarnings.length > 0
      ? React.createElement(
          Box, { key: "env", flexDirection: "column" },
          React.createElement(Text, { bold: true, color: "yellow" }, "Environment variable warnings"),
          ...envWarnings.map((w) =>
            React.createElement(Text, { key: w.name, color: "yellow" }, w.message),
          ),
        )
      : null,

    // Version locks
    versionLocks?.enabled
      ? React.createElement(
          Box, { key: "locks", flexDirection: "column" },
          React.createElement(Text, { bold: true }, "Version locks"),
          React.createElement(Text, null, `Cleaned: ${versionLocks.cleanedCount}`),
          ...versionLocks.activeLocks.map((l) =>
            React.createElement(
              Text, { key: String(l.pid) },
              `PID ${l.pid} v${l.version} (${l.isAlive ? "alive" : "dead"})`,
            ),
          ),
        )
      : null,

    // Agent parse errors
    agentParseErrors && agentParseErrors.length > 0
      ? React.createElement(
          Box, { key: "agent-errors", flexDirection: "column" },
          React.createElement(Text, { bold: true, color: "red" }, "Agent parse errors"),
          ...agentParseErrors.map((e) =>
            React.createElement(
              Box, { key: e.file, flexDirection: "column" },
              React.createElement(Text, { color: "red" }, e.file),
              React.createElement(Text, { dimColor: true }, e.error),
            ),
          ),
        )
      : null,

    // Plugin errors
    pluginErrors && pluginErrors.length > 0
      ? React.createElement(
          Box, { key: "plugin-errors", flexDirection: "column" },
          React.createElement(Text, { bold: true, color: "red" }, "Plugin errors"),
          ...pluginErrors.map((e) =>
            React.createElement(
              Box, { key: `${e.source}:${e.plugin}`, flexDirection: "column" },
              React.createElement(Text, { color: "red" }, `${e.source}/${e.plugin}`),
              React.createElement(Text, { dimColor: true }, e.message),
            ),
          ),
        )
      : null,

    // Keybinding warnings
    keybindingWarnings && keybindingWarnings.length > 0
      ? React.createElement(
          Box, { key: "kb-warnings", flexDirection: "column" },
          React.createElement(Text, { bold: true, color: "yellow" }, "Keybinding warnings"),
          ...keybindingWarnings.map((w, i) =>
            React.createElement(Text, { key: String(i), color: "yellow" }, w.message),
          ),
        )
      : null,

    // Context usage warnings
    contextUsageWarnings
      ? React.createElement(
          Box, { key: "ctx-usage", flexDirection: "column" },
          React.createElement(Text, { bold: true }, "Context usage"),
          ...contextUsageWarnings.unreachableRules.map((r) =>
            React.createElement(Text, { key: r, color: "yellow" }, `Unreachable: ${r}`),
          ),
        )
      : null,

    // Dismiss hint
    React.createElement(
      Text, { key: "hint", dimColor: true },
      "Press y, Enter, n, or Esc to dismiss",
    ),
  );
}

export default DoctorScreen;
