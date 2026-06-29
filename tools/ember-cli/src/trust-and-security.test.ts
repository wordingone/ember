// trust-and-security tests — one named test per AC.
import { describe, test, expect } from "bun:test";
import {
  // Pure utilities
  shouldShowTrustDialog,
  formatListWithAnd,
  extractDangerousSettings,
  hasDangerousSettings,
  hasDangerousSettingsChanged,
  formatDangerousSettingsList,
  getTrustSavePath,
  getHooksSources,
  getBashPermissionSources,
  DANGEROUS_SHELL_SETTINGS,
  TRUST_DIALOG_SHOWN_EVENT,
  TRUST_DIALOG_ACCEPT_EVENT,
  // Components (structural)
  TrustDialog,
  ManagedSettingsSecurityDialog,
} from "./trust-and-security.ts";

// ---------------------------------------------------------------------------
// AC1: TrustDialog is shown when a project has any MCP servers configured
// ---------------------------------------------------------------------------
describe("AC1 — shouldShowTrustDialog MCP servers", () => {
  test("AC1a: project with MCP servers → show dialog", () => {
    expect(
      shouldShowTrustDialog({ mcpServers: [{ name: "test-server" }] }),
    ).toBe(true);
  });

  test("AC1b: project with empty MCP server list → do not show", () => {
    expect(shouldShowTrustDialog({ mcpServers: [] })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC2: TrustDialog is shown when a project has hooks configured
// ---------------------------------------------------------------------------
describe("AC2 — shouldShowTrustDialog hooks", () => {
  test("AC2a: project with hooks → show dialog", () => {
    expect(shouldShowTrustDialog({ hooks: ["PreToolUse"] })).toBe(true);
  });

  test("AC2b: project with empty hooks array → do not show", () => {
    expect(shouldShowTrustDialog({ hooks: [] })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: TrustDialog fires tengu_trust_dialog_shown and tengu_trust_dialog_accept
// ---------------------------------------------------------------------------
describe("AC3 — analytics event constants", () => {
  test("AC3a: tengu_trust_dialog_shown constant is the correct string", () => {
    expect(TRUST_DIALOG_SHOWN_EVENT).toBe("ember_trust_dialog_shown");
  });

  test("AC3b: tengu_trust_dialog_accept constant is the correct string", () => {
    expect(TRUST_DIALOG_ACCEPT_EVENT).toBe("ember_trust_dialog_accept");
  });

  test("AC3c: TrustDialog is exported as a function", () => {
    expect(typeof TrustDialog).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// AC4: Accepting for "session" saves to the home-directory session global file
// ---------------------------------------------------------------------------
describe("AC4 — getTrustSavePath session", () => {
  test("AC4: session destination resolves to home dir path, not project dir", () => {
    const path = getTrustSavePath("session", "/home/user", "/projects/myapp");
    // session → home-directory session global file (under ~/.ember/, not project)
    expect(path).toContain("/home/user");
    expect(path).not.toContain("/projects/myapp"); // must NOT be in the project dir
  });
});

// ---------------------------------------------------------------------------
// AC5: Accepting for "project" saves to the project's .ember/ config
// ---------------------------------------------------------------------------
describe("AC5 — getTrustSavePath project", () => {
  test("AC5: project destination resolves to .ember/ path", () => {
    const path = getTrustSavePath("project", "/home/user", "/projects/myapp");
    expect(path).toContain("/projects/myapp");
    expect(path).toContain(".ember");
  });
});

// ---------------------------------------------------------------------------
// AC6: No accept (Esc) → session does not proceed
// ---------------------------------------------------------------------------
describe("AC6 — TrustDialog empty config does not show", () => {
  test("AC6: empty config → shouldShowTrustDialog is false", () => {
    // When false, TrustDialog is not rendered and session proceeds without it
    expect(shouldShowTrustDialog({})).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC7: hasDangerousSettings returns false for safe settings
// ---------------------------------------------------------------------------
describe("AC7 — hasDangerousSettings safe settings", () => {
  test("AC7a: empty managed settings → false", () => {
    expect(hasDangerousSettings({})).toBe(false);
  });

  test("AC7b: settings with only allowed env vars → false", () => {
    expect(
      hasDangerousSettings({
        envVars: { PATH: "/usr/bin", HOME: "/home/user" },
        allowedEnvVars: new Set(["PATH", "HOME"]),
      }),
    ).toBe(false);
  });

  test("AC7c: settings with a DANGEROUS_SHELL_SETTINGS entry → true", () => {
    expect(
      hasDangerousSettings({
        shellSettings: { aliases: "ls='rm -rf'" },
      }),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC8: hasDangerousSettingsChanged returns true when dangerous setting added
// ---------------------------------------------------------------------------
describe("AC8 — hasDangerousSettingsChanged", () => {
  test("AC8a: adding an aliases setting changes from safe to dangerous", () => {
    const before = {};
    const after = { shellSettings: { aliases: "ls='echo hacked'" } };
    expect(hasDangerousSettingsChanged(before, after)).toBe(true);
  });

  test("AC8b: no change between two identical empty settings → false", () => {
    expect(hasDangerousSettingsChanged({}, {})).toBe(false);
  });

  test("AC8c: removing a dangerous setting changes from dangerous to safe", () => {
    const before = { shellSettings: { BASH_ENV: "/evil.sh" } };
    const after = {};
    expect(hasDangerousSettingsChanged(before, after)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC9: ManagedSettingsSecurityDialog covers env vars not in permitted allowlist
// ---------------------------------------------------------------------------
describe("AC9 — extractDangerousSettings env vars", () => {
  test("AC9a: env var NOT in allowlist → flagged as unapproved-env-var", () => {
    const dangerous = extractDangerousSettings({
      envVars: { SECRET_TOKEN: "abc123" },
      allowedEnvVars: new Set(["PATH"]),
    });
    const names = dangerous.map(d => d.name);
    expect(names).toContain("SECRET_TOKEN");
    const entry = dangerous.find(d => d.name === "SECRET_TOKEN");
    expect(entry?.reason).toBe("unapproved-env-var");
  });

  test("AC9b: env var IN allowlist → not flagged", () => {
    const dangerous = extractDangerousSettings({
      envVars: { PATH: "/usr/bin" },
      allowedEnvVars: new Set(["PATH"]),
    });
    const names = dangerous.map(d => d.name);
    expect(names).not.toContain("PATH");
  });

  test("AC9c: env var with empty allowlist → flagged", () => {
    const dangerous = extractDangerousSettings({
      envVars: { FOO: "bar" },
      allowedEnvVars: new Set(),
    });
    expect(dangerous.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC10: formatListWithAnd produces "MCP servers and hooks"
// ---------------------------------------------------------------------------
describe("AC10 — formatListWithAnd", () => {
  test("AC10a: ['MCP servers', 'hooks'] → 'MCP servers and hooks'", () => {
    expect(formatListWithAnd(["MCP servers", "hooks"])).toBe("MCP servers and hooks");
  });

  test("AC10b: single item returns the item", () => {
    expect(formatListWithAnd(["MCP servers"])).toBe("MCP servers");
  });

  test("AC10c: empty array returns empty string", () => {
    expect(formatListWithAnd([])).toBe("");
  });

  test("AC10d: three items uses Oxford comma", () => {
    const result = formatListWithAnd(["a", "b", "c"]);
    expect(result).toBe("a, b, and c");
  });

  test("AC10e: two items — no comma, just 'and'", () => {
    const result = formatListWithAnd(["hooks", "MCP servers"]);
    expect(result).toBe("hooks and MCP servers");
  });
});

// ---------------------------------------------------------------------------
// Additional utility coverage
// ---------------------------------------------------------------------------
describe("DANGEROUS_SHELL_SETTINGS", () => {
  test("constant is a non-empty array", () => {
    expect(Array.isArray(DANGEROUS_SHELL_SETTINGS)).toBe(true);
    expect(DANGEROUS_SHELL_SETTINGS.length).toBeGreaterThan(0);
  });

  test("'aliases' is in the dangerous list", () => {
    expect(DANGEROUS_SHELL_SETTINGS).toContain("aliases");
  });
});

describe("formatDangerousSettingsList", () => {
  test("empty list → '(none)'", () => {
    expect(formatDangerousSettingsList([])).toBe("(none)");
  });

  test("non-empty list includes setting names", () => {
    const result = formatDangerousSettingsList([
      { name: "aliases", value: "ls=rm", reason: "dangerous-shell-setting" },
    ]);
    expect(result).toContain("aliases");
  });
});

describe("getHooksSources", () => {
  test("returns hook names", () => {
    const sources = getHooksSources(["PreToolUse", "PostToolUse"]);
    expect(sources).toEqual(["PreToolUse", "PostToolUse"]);
  });
});

describe("getBashPermissionSources", () => {
  test("returns indexed labels for rules", () => {
    const sources = getBashPermissionSources(["rule1", "rule2"]);
    expect(sources).toHaveLength(2);
  });
});

describe("structural exports", () => {
  test("ManagedSettingsSecurityDialog is exported as a function", () => {
    expect(typeof ManagedSettingsSecurityDialog).toBe("function");
  });
});
