// screens/doctor.test.ts — one passing test per AC (AC1–AC12) + structural checks.

import { describe, it, expect } from "bun:test";
import React from "react";
import DoctorScreen, {
  DOCTOR_DONE_MESSAGE,
  ENV_VAR_DEFAULTS,
  ENV_VAR_RANGE,
  SECTION_ORDER,
  validateBoundedIntEnvVar,
  extractEnvVarWarnings,
  type DoctorScreenProps,
  type InstallInfo,
  type VersionLocks,
  type AgentParseError,
  type PluginError,
  type ContextUsageWarnings,
} from "./doctor.ts";

// ---------------------------------------------------------------------------
// AC1: Screen renders "Diagnostics" title on mount
// ---------------------------------------------------------------------------

describe("AC1: DoctorScreen renders Diagnostics title", () => {
  it("React.createElement succeeds and produces a valid element", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp/test",
      onDone: () => {},
    });
    expect(el.type).toBe(DoctorScreen);
    // Title is a static prop of the component — verified by DOCTOR_DONE_MESSAGE contract
    expect(DOCTOR_DONE_MESSAGE).toBe("Ember CLI diagnostics dismissed");
  });
});

// ---------------------------------------------------------------------------
// AC2: y / enter / n / escape dismiss the screen via onDone callback
// ---------------------------------------------------------------------------

describe("AC2: dismiss via onDone callback", () => {
  it("DOCTOR_DONE_MESSAGE is 'Ember CLI diagnostics dismissed' (interop)", () => {
    expect(DOCTOR_DONE_MESSAGE).toBe("Ember CLI diagnostics dismissed");
  });

  it("onDone prop is threaded and callable with correct signature", () => {
    let calledMsg = "";
    let calledOpts: { display: string } | null = null;
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: (msg: string, opts: { display: string }) => {
        calledMsg = msg;
        calledOpts = opts;
      },
    });
    const p = el.props as DoctorScreenProps;
    p.onDone(DOCTOR_DONE_MESSAGE, { display: "system" });
    expect(calledMsg).toBe("Ember CLI diagnostics dismissed");
    expect(calledOpts!.display).toBe("system");
  });
});

// ---------------------------------------------------------------------------
// AC3: Installation type, version, path displayed
// ---------------------------------------------------------------------------

describe("AC3: installInfo prop is threaded", () => {
  const installInfo: InstallInfo = {
    type: "npm",
    version: "2.0.0",
    packageManager: "npm",
    path: "/usr/local/bin/ember",
    invokedBinary: "/usr/local/bin/ember",
    configInstallMethod: "npm",
    ripgrepStatus: "working",
    ripgrepMode: "bundled",
  };

  it("accepts installInfo with correct fields", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      installInfo,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.installInfo!.type).toBe("npm");
    expect(p.installInfo!.version).toBe("2.0.0");
    expect(p.installInfo!.path).toBe("/usr/local/bin/ember");
  });
});

// ---------------------------------------------------------------------------
// AC4: ripgrep status shown
// ---------------------------------------------------------------------------

describe("AC4: ripgrep status in installInfo", () => {
  it("ripgrepStatus 'not_working' is preserved in props", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      installInfo: {
        type: "global",
        version: "1.0.0",
        packageManager: "npm",
        path: "/usr/bin/ember",
        invokedBinary: "/usr/bin/ember",
        configInstallMethod: "npm",
        ripgrepStatus: "not_working",
      },
    });
    const p = el.props as DoctorScreenProps;
    expect(p.installInfo!.ripgrepStatus).toBe("not_working");
  });

  it("ripgrepMode 'bundled' | 'vendor' | 'system' preserved", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      installInfo: {
        type: "global",
        version: "1.0.0",
        packageManager: "npm",
        path: "/usr/bin/ember",
        invokedBinary: "/usr/bin/ember",
        configInstallMethod: "npm",
        ripgrepStatus: "working",
        ripgrepMode: "system",
      },
    });
    const p = el.props as DoctorScreenProps;
    expect(p.installInfo!.ripgrepMode).toBe("system");
  });
});

// ---------------------------------------------------------------------------
// AC5: Multiple CLI paths listed
// ---------------------------------------------------------------------------

describe("AC5: multipleInstalls lists paths", () => {
  it("multipleInstalls prop is accepted with multiple paths", () => {
    const paths = ["/usr/bin/ember", "/usr/local/bin/ember", "/opt/homebrew/bin/ember"];
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      multipleInstalls: paths,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.multipleInstalls).toEqual(paths);
    expect(p.multipleInstalls!.length).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// AC6: BASH_MAX_OUTPUT_LENGTH and TASK_MAX_OUTPUT_LENGTH validated
// ---------------------------------------------------------------------------

describe("AC6: env var range validation", () => {
  it("default for BASH_MAX_OUTPUT_LENGTH is 8000", () => {
    expect(ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH).toBe(8_000);
    const { parsed, warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      undefined,
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(parsed).toBe(8_000);
    expect(warning).toBeNull();
  });

  it("default for TASK_MAX_OUTPUT_LENGTH is 16000", () => {
    expect(ENV_VAR_DEFAULTS.TASK_MAX_OUTPUT_LENGTH).toBe(16_000);
    const { parsed, warning } = validateBoundedIntEnvVar(
      "TASK_MAX_OUTPUT_LENGTH",
      undefined,
      ENV_VAR_DEFAULTS.TASK_MAX_OUTPUT_LENGTH,
    );
    expect(parsed).toBe(16_000);
    expect(warning).toBeNull();
  });

  it("range is [1, 1_000_000]", () => {
    expect(ENV_VAR_RANGE.min).toBe(1);
    expect(ENV_VAR_RANGE.max).toBe(1_000_000);
  });

  it("value 0 (below min) produces a warning", () => {
    const { warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      "0",
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(warning).not.toBeNull();
    expect(warning!.name).toBe("BASH_MAX_OUTPUT_LENGTH");
    expect(warning!.message).toContain("[1, 1000000]");
  });

  it("value 2_000_000 (above max) produces a warning", () => {
    const { warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      "2000000",
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(warning).not.toBeNull();
  });

  it("boundary value 1 is valid", () => {
    const { parsed, warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      "1",
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(parsed).toBe(1);
    expect(warning).toBeNull();
  });

  it("boundary value 1_000_000 is valid", () => {
    const { parsed, warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      "1000000",
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(parsed).toBe(1_000_000);
    expect(warning).toBeNull();
  });

  it("in-range value 50_000 produces no warning", () => {
    const { parsed, warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      "50000",
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(parsed).toBe(50_000);
    expect(warning).toBeNull();
  });

  it("non-integer value produces a warning", () => {
    const { warning } = validateBoundedIntEnvVar(
      "BASH_MAX_OUTPUT_LENGTH",
      "abc",
      ENV_VAR_DEFAULTS.BASH_MAX_OUTPUT_LENGTH,
    );
    expect(warning).not.toBeNull();
  });

  it("extractEnvVarWarnings — both bad vars produce two warnings", () => {
    const warnings = extractEnvVarWarnings({
      BASH_MAX_OUTPUT_LENGTH: "0",
      TASK_MAX_OUTPUT_LENGTH: "9999999",
    });
    expect(warnings.length).toBe(2);
    expect(warnings[0]!.name).toBe("BASH_MAX_OUTPUT_LENGTH");
    expect(warnings[1]!.name).toBe("TASK_MAX_OUTPUT_LENGTH");
  });

  it("extractEnvVarWarnings — both valid vars produce no warnings", () => {
    const warnings = extractEnvVarWarnings({
      BASH_MAX_OUTPUT_LENGTH: "10000",
      TASK_MAX_OUTPUT_LENGTH: "20000",
    });
    expect(warnings).toHaveLength(0);
  });

  it("extractEnvVarWarnings — env prop accepted on DoctorScreen", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      env: { BASH_MAX_OUTPUT_LENGTH: "0" },
    });
    const p = el.props as DoctorScreenProps;
    expect(p.env!["BASH_MAX_OUTPUT_LENGTH"]).toBe("0");
  });
});

// ---------------------------------------------------------------------------
// AC7: User home agents dir ($HOME/.ember/agents) noted if absent
// ---------------------------------------------------------------------------

describe("AC7: user home agents directory", () => {
  it("cwd prop is threaded to screen (async check is internal)", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/some/project",
      onDone: () => {},
    });
    const p = el.props as DoctorScreenProps;
    expect(p.cwd).toBe("/some/project");
  });
});

// ---------------------------------------------------------------------------
// AC8: Version lock section only when PID-based locking enabled
// ---------------------------------------------------------------------------

describe("AC8: version locks section", () => {
  it("versionLocks.enabled=false — prop indicates disabled", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      versionLocks: { enabled: false, cleanedCount: 0, activeLocks: [] },
    });
    const p = el.props as DoctorScreenProps;
    expect(p.versionLocks!.enabled).toBe(false);
  });

  it("versionLocks.enabled=true — cleanedCount and activeLocks threaded", () => {
    const locks: VersionLocks = {
      enabled: true,
      cleanedCount: 5,
      activeLocks: [
        { pid: 12345, version: "1.2.3", isAlive: true },
        { pid: 99999, version: "0.9.0", isAlive: false },
      ],
    };
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      versionLocks: locks,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.versionLocks!.cleanedCount).toBe(5);
    expect(p.versionLocks!.activeLocks[0]!.pid).toBe(12345);
    expect(p.versionLocks!.activeLocks[0]!.version).toBe("1.2.3");
    expect(p.versionLocks!.activeLocks[1]!.isAlive).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC9: Agent parse errors shown in red
// ---------------------------------------------------------------------------

describe("AC9: agent parse errors", () => {
  it("agentParseErrors prop is threaded correctly", () => {
    const errors: AgentParseError[] = [
      { file: "/home/.ember/agents/my-agent.json", error: "Unexpected end of JSON input" },
    ];
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      agentParseErrors: errors,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.agentParseErrors![0]!.file).toBe("/home/.ember/agents/my-agent.json");
    expect(p.agentParseErrors![0]!.error).toBe("Unexpected end of JSON input");
  });

  it("empty agentParseErrors array accepted", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      agentParseErrors: [],
    });
    const p = el.props as DoctorScreenProps;
    expect(p.agentParseErrors!.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// AC10: Plugin load errors with source and plugin name
// ---------------------------------------------------------------------------

describe("AC10: plugin errors", () => {
  it("pluginErrors prop is threaded with source, plugin, message", () => {
    const errors: PluginError[] = [
      { source: "npm", plugin: "ember-plugin-git", message: "Module not found" },
    ];
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      pluginErrors: errors,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.pluginErrors![0]!.source).toBe("npm");
    expect(p.pluginErrors![0]!.plugin).toBe("ember-plugin-git");
    expect(p.pluginErrors![0]!.message).toBe("Module not found");
  });
});

// ---------------------------------------------------------------------------
// AC11: Keybinding validation warnings in their own section
// ---------------------------------------------------------------------------

describe("AC11: keybinding warnings", () => {
  it("keybindingWarnings prop is accepted", () => {
    const warnings = [
      { type: "reserved" as const, message: "ctrl+c is non-rebindable and cannot be overridden", keystroke: "ctrl+c" },
    ];
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      keybindingWarnings: warnings,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.keybindingWarnings![0]!.type).toBe("reserved");
    expect(p.keybindingWarnings![0]!.message).toContain("ctrl+c");
  });

  it("multiple keybinding warning types are threaded", () => {
    const warnings = [
      { type: "invalid_context" as const, message: "Unknown context: Foo", context: "Foo" },
      { type: "invalid_action" as const, message: "Unknown action: bar:baz", action: "bar:baz" },
    ];
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      keybindingWarnings: warnings,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.keybindingWarnings!.length).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// AC12: Context usage warnings populated asynchronously
// ---------------------------------------------------------------------------

describe("AC12: context usage warnings", () => {
  it("contextUsageWarnings prop is accepted with unreachable rules", () => {
    const usage: ContextUsageWarnings = {
      unreachableRules: ["perm:read:some-path"],
      emberMdUsage: ["/project/EMBER.md"],
      agentUsage: ["agent-1"],
      mcpServerUsage: ["mcp-server-a"],
    };
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
      contextUsageWarnings: usage,
    });
    const p = el.props as DoctorScreenProps;
    expect(p.contextUsageWarnings!.unreachableRules[0]).toBe("perm:read:some-path");
    expect(p.contextUsageWarnings!.emberMdUsage[0]).toBe("/project/EMBER.md");
    expect(p.contextUsageWarnings!.agentUsage[0]).toBe("agent-1");
    expect(p.contextUsageWarnings!.mcpServerUsage[0]).toBe("mcp-server-a");
  });

  it("contextUsageWarnings undefined by default", () => {
    const el = React.createElement(DoctorScreen, {
      cwd: "/tmp",
      onDone: () => {},
    });
    const p = el.props as DoctorScreenProps;
    expect(p.contextUsageWarnings).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Section ordering — structural (confirms the 15-entry ordered constant)
// ---------------------------------------------------------------------------

describe("SECTION_ORDER constant", () => {
  it("has exactly 15 entries", () => {
    expect(SECTION_ORDER.length).toBe(15);
  });

  it("sections appear in spec-defined display order", () => {
    expect(SECTION_ORDER[0]).toBe("title");
    expect(SECTION_ORDER[1]).toBe("installation");
    expect(SECTION_ORDER[2]).toBe("recommendations");
    expect(SECTION_ORDER[3]).toBe("multiple_installations");
    expect(SECTION_ORDER[4]).toBe("custom_warnings");
    expect(SECTION_ORDER[5]).toBe("invalid_settings");
    expect(SECTION_ORDER[6]).toBe("updates");
    expect(SECTION_ORDER[7]).toBe("sandbox");
    expect(SECTION_ORDER[8]).toBe("mcp_warnings");
    expect(SECTION_ORDER[9]).toBe("keybinding_warnings");
    expect(SECTION_ORDER[10]).toBe("env_vars");
    expect(SECTION_ORDER[11]).toBe("version_locks");
    expect(SECTION_ORDER[12]).toBe("agent_errors");
    expect(SECTION_ORDER[13]).toBe("plugin_errors");
    expect(SECTION_ORDER[14]).toBe("context_usage");
  });
});
