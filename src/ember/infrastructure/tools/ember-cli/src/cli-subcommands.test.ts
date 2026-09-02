// Tests for cli-subcommands.ts — AC1–AC10

import { describe, it, expect, beforeEach, afterEach, mock } from "bun:test";
import {
  authLogin,
  authStatus,
  update,
  agents,
  autoModeDefaults,
  autoModeConfig,
  autoModeCritique,
  pluginValidate,
  install,
  ps,
  logsSession,
  attachSession,
  killSession,
  antLog,
  type SubcommandDeps,
  type AgentDefinition,
} from "./cli-subcommands.ts";

// ---------------------------------------------------------------------------
// Helpers — mock process.exit and capture stdout/stderr
// ---------------------------------------------------------------------------

type ExitError = Error & { code: number };

function mockProcessExit(): { restore: () => void; captured: () => number | null } {
  let captured: number | null = null;
  const orig = process.exit;
  (process as unknown as { exit: (code?: number) => never }).exit = ((code?: number) => {
    captured = code ?? 0;
    throw Object.assign(new Error(`process.exit(${code ?? 0})`), { code: code ?? 0 }) as ExitError;
  }) as typeof process.exit;
  return {
    restore: () => { (process as unknown as { exit: typeof orig }).exit = orig; },
    captured: () => captured,
  };
}

function captureStdout(): { restore: () => void; output: () => string } {
  let out = "";
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((s: string) => { out += s; return true; }) as typeof process.stdout.write;
  return {
    restore: () => { process.stdout.write = orig; },
    output: () => out,
  };
}

function captureStderr(): { restore: () => void; output: () => string } {
  let out = "";
  const orig = process.stderr.write.bind(process.stderr);
  process.stderr.write = ((s: string) => { out += s; return true; }) as typeof process.stderr.write;
  return {
    restore: () => { process.stderr.write = orig; },
    output: () => out,
  };
}

async function runCli(fn: () => Promise<never>): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const exitMock = mockProcessExit();
  const stdoutCap = captureStdout();
  const stderrCap = captureStderr();
  let exitCode = 0;
  try {
    await fn();
  } catch (e) {
    if (e instanceof Error && "code" in e) {
      exitCode = (e as ExitError).code;
    }
  } finally {
    exitMock.restore();
    stdoutCap.restore();
    stderrCap.restore();
  }
  return {
    exitCode: exitMock.captured() ?? exitCode,
    stdout: stdoutCap.output(),
    stderr: stderrCap.output(),
  };
}

// ---------------------------------------------------------------------------
// AC1: auth login --console + --cloudauth → error
// ---------------------------------------------------------------------------

describe("auth login", () => {
  let savedEnv: Record<string, string | undefined>;

  beforeEach(() => {
    savedEnv = {
      EMBER_OAUTH_REFRESH_TOKEN: process.env["EMBER_OAUTH_REFRESH_TOKEN"],
      EMBER_OAUTH_SCOPES: process.env["EMBER_OAUTH_SCOPES"],
    };
    delete process.env["EMBER_OAUTH_REFRESH_TOKEN"];
    delete process.env["EMBER_OAUTH_SCOPES"];
  });

  afterEach(() => {
    for (const [k, v] of Object.entries(savedEnv)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  });

  it("AC1: --console and --cloudauth together → exit 1 with error", async () => {
    const { exitCode, stderr } = await runCli(() =>
      authLogin({ console: true, cloudauth: true }),
    );
    expect(exitCode).toBe(1);
    expect(stderr).toContain("--console");
    expect(stderr).toContain("--cloudauth");
  });

  it("AC1: --console alone → proceeds without mutual-exclusion error", async () => {
    const deps: SubcommandDeps = {
      startBrowserOAuth: async () => ({ access_token: "tok", token_type: "bearer" }),
      installOAuthTokens: async () => {},
    };
    const { exitCode } = await runCli(() => authLogin({ console: true }, deps));
    expect(exitCode).toBe(0);
  });

  // AC2: EMBER_OAUTH_REFRESH_TOKEN fast path
  it("AC2: EMBER_OAUTH_REFRESH_TOKEN set → skips browser flow", async () => {
    process.env["EMBER_OAUTH_REFRESH_TOKEN"] = "my-refresh";
    process.env["EMBER_OAUTH_SCOPES"] = "scope1,scope2";

    let browserCalled = false;
    let exchangeCalled = false;

    const deps: SubcommandDeps = {
      exchangeRefreshToken: async (token, scopes) => {
        exchangeCalled = true;
        expect(token).toBe("my-refresh");
        expect(scopes).toContain("scope1");
        return { access_token: "new-tok", token_type: "bearer" };
      },
      startBrowserOAuth: async () => {
        browserCalled = true;
        return { access_token: "browser-tok", token_type: "bearer" };
      },
      installOAuthTokens: async () => {},
    };

    const { exitCode } = await runCli(() => authLogin({}, deps));
    expect(exitCode).toBe(0);
    expect(exchangeCalled).toBe(true);
    expect(browserCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: auth status --json
// ---------------------------------------------------------------------------

describe("auth status", () => {
  it("AC3: --json outputs JSON with uuid, email, authMethod", async () => {
    const deps: SubcommandDeps = {
      getAuthStatus: async () => ({
        uuid: "user-abc-123",
        email: "test@example.com",
        displayName: "Test User",
        authMethod: "cloud",
      }),
    };

    const { exitCode, stdout } = await runCli(() =>
      authStatus({ json: true }, deps),
    );

    expect(exitCode).toBe(0);
    const parsed = JSON.parse(stdout.trim());
    expect(parsed.uuid).toBe("user-abc-123");
    expect(parsed.email).toBe("test@example.com");
    expect(parsed.authMethod).toBe("cloud");
  });

  it("AC3: --json with no auth outputs {authMethod: 'none'}", async () => {
    const deps: SubcommandDeps = {
      getAuthStatus: async () => null,
    };

    const { exitCode, stdout } = await runCli(() =>
      authStatus({ json: true }, deps),
    );

    expect(exitCode).toBe(0);
    const parsed = JSON.parse(stdout.trim());
    expect(parsed.authMethod).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// AC4: update on package-manager installation
// ---------------------------------------------------------------------------

describe("update", () => {
  it("AC4: package-manager install → prints update command, no self-install attempt", async () => {
    let nativeUpdateCalled = false;

    const deps: SubcommandDeps = {
      detectInstallationType: async () => "package-manager",
      detectPackageManager: () => ({ command: "brew", args: ["upgrade", "ember-cli"] }),
      runNativeUpdate: async () => {
        nativeUpdateCalled = true;
        return null;
      },
    };

    const { exitCode, stdout } = await runCli(() => update(deps));

    expect(exitCode).toBe(0);
    expect(stdout).toContain("brew");
    expect(nativeUpdateCalled).toBe(false);
  });

  it("AC4: winget variant prints winget upgrade command", async () => {
    const deps: SubcommandDeps = {
      detectInstallationType: async () => "package-manager",
      detectPackageManager: () => ({
        command: "winget",
        args: ["upgrade", "--id", "Ember.CLI"],
      }),
      runNativeUpdate: async () => null,
    };

    const { stdout } = await runCli(() => update(deps));
    expect(stdout).toContain("winget");
  });
});

// ---------------------------------------------------------------------------
// AC5: agents — no configured agents
// ---------------------------------------------------------------------------

describe("agents", () => {
  it("AC5: no agents → prints 'No agents found', exits 0", async () => {
    const deps: SubcommandDeps = {
      loadAgents: async () => [],
    };

    const { exitCode, stdout } = await runCli(() => agents(deps));
    expect(exitCode).toBe(0);
    expect(stdout).toContain("No agents found");
  });

  it("lists active agents grouped by source", async () => {
    const defs: AgentDefinition[] = [
      { name: "code-agent", type: "code", source: "system", active: true },
      { name: "search-agent", type: "search", source: "user", active: true },
      { name: "inactive-agent", type: "other", source: "system", active: false },
    ];

    const deps: SubcommandDeps = { loadAgents: async () => defs };
    const { exitCode, stdout } = await runCli(() => agents(deps));

    expect(exitCode).toBe(0);
    expect(stdout).toContain("code-agent");
    expect(stdout).toContain("search-agent");
    expect(stdout).not.toContain("inactive-agent");
    expect(stdout).toContain("Total: 2");
  });
});

// ---------------------------------------------------------------------------
// AC6: auto-mode config REPLACE semantics
// ---------------------------------------------------------------------------

describe("auto-mode config", () => {
  it("AC6: user allow section replaces defaults entirely (REPLACE, not MERGE)", async () => {
    const deps: SubcommandDeps = {
      getDefaultAutoModeRules: () => ({
        allow: ["default-rule-1", "default-rule-2"],
        soft_deny: ["deny-default"],
        environment: {},
      }),
      getUserAutoModeRules: () => ({
        allow: ["user-only-rule"],
      }),
    };

    const { exitCode, stdout } = await runCli(() => autoModeConfig(deps));
    expect(exitCode).toBe(0);

    const parsed = JSON.parse(stdout.trim());
    expect(parsed.allow).toEqual(["user-only-rule"]);
    expect(parsed.allow).not.toContain("default-rule-1");
    // soft_deny falls through to defaults (user didn't set it)
    expect(parsed.soft_deny).toContain("deny-default");
  });

  it("auto-mode defaults dumps built-in rules", async () => {
    const deps: SubcommandDeps = {
      getDefaultAutoModeRules: () => ({
        allow: ["built-in"],
        soft_deny: [],
        environment: {},
      }),
    };

    const { stdout } = await runCli(() => autoModeDefaults(deps));
    const parsed = JSON.parse(stdout.trim());
    expect(parsed.allow).toContain("built-in");
  });
});

// ---------------------------------------------------------------------------
// AC7: plugin validate
// ---------------------------------------------------------------------------

describe("plugin validate", () => {
  it("AC7: valid manifest → exits 0", async () => {
    const deps: SubcommandDeps = {
      validatePluginManifest: async () => ({ errors: [], warnings: [] }),
    };

    const { exitCode } = await runCli(() => pluginValidate("/path/to/manifest.json", {}, deps));
    expect(exitCode).toBe(0);
  });

  it("AC7: invalid manifest → exits 1 with error details", async () => {
    const deps: SubcommandDeps = {
      validatePluginManifest: async () => ({
        errors: ["Missing 'name' field"],
        warnings: [],
      }),
    };

    const { exitCode, stderr } = await runCli(() =>
      pluginValidate("/path/to/manifest.json", {}, deps),
    );
    expect(exitCode).toBe(1);
    expect(stderr).toContain("Missing 'name'");
  });
});

// ---------------------------------------------------------------------------
// AC8: background session stubs throw "not supported"
// ---------------------------------------------------------------------------

describe("background session stubs", () => {
  it("AC8: ps() exits non-zero with 'not supported'", async () => {
    const { exitCode, stderr } = await runCli(async () => ps());
    expect(exitCode).not.toBe(0);
    expect(stderr).toContain("not supported");
  });

  it("AC8: logs() exits non-zero with 'not supported'", async () => {
    const { exitCode, stderr } = await runCli(async () => logsSession("sess-1"));
    expect(exitCode).not.toBe(0);
    expect(stderr).toContain("not supported");
  });

  it("AC8: attach() exits non-zero with 'not supported'", async () => {
    const { exitCode, stderr } = await runCli(async () => attachSession("sess-1"));
    expect(exitCode).not.toBe(0);
    expect(stderr).toContain("not supported");
  });

  it("AC8: kill() exits non-zero with 'not supported'", async () => {
    const { exitCode, stderr } = await runCli(async () => killSession("sess-1"));
    expect(exitCode).not.toBe(0);
    expect(stderr).toContain("not supported");
  });

  it("AC8: ant-internal antLog() exits non-zero with 'not supported'", async () => {
    const { exitCode, stderr } = await runCli(async () => antLog("1"));
    expect(exitCode).not.toBe(0);
    expect(stderr).toContain("not supported");
  });
});

// ---------------------------------------------------------------------------
// AC9: auto-mode critique with no custom rules
// ---------------------------------------------------------------------------

describe("auto-mode critique", () => {
  it("AC9: no custom rules → prints message without calling model", async () => {
    let critiqueCalled = false;

    const deps: SubcommandDeps = {
      getUserAutoModeRules: () => ({}),
      getDefaultAutoModeRules: () => ({ allow: [], soft_deny: [], environment: {} }),
      critiquRules: async () => {
        critiqueCalled = true;
        return "critique text";
      },
    };

    const { exitCode, stdout } = await runCli(() => autoModeCritique({}, deps));
    expect(exitCode).toBe(0);
    expect(stdout).toContain("No custom rules");
    expect(critiqueCalled).toBe(false);
  });

  it("AC9: with custom rules → invokes model", async () => {
    let critiqueCalled = false;

    const deps: SubcommandDeps = {
      getUserAutoModeRules: () => ({ allow: ["my-custom-rule"] }),
      getDefaultAutoModeRules: () => ({ allow: ["default"], soft_deny: [], environment: {} }),
      critiquRules: async () => {
        critiqueCalled = true;
        return "Your rules look good, but consider adding X.";
      },
    };

    const { exitCode, stdout } = await runCli(() => autoModeCritique({}, deps));
    expect(exitCode).toBe(0);
    expect(critiqueCalled).toBe(true);
    expect(stdout).toContain("Your rules");
  });
});

// ---------------------------------------------------------------------------
// AC10: install invokes native installer
// ---------------------------------------------------------------------------

describe("install", () => {
  it("AC10: install() calls runNativeInstaller and exits 0 on success", async () => {
    let installerCalled = false;
    let calledTarget: string | undefined;
    let calledForce: boolean | undefined;

    const deps: SubcommandDeps = {
      runNativeInstaller: async (target, force) => {
        installerCalled = true;
        calledTarget = target;
        calledForce = force;
      },
    };

    const { exitCode } = await runCli(() => install("~/bin", { force: true }, deps));
    expect(exitCode).toBe(0);
    expect(installerCalled).toBe(true);
    expect(calledTarget).toBe("~/bin");
    expect(calledForce).toBe(true);
  });

  it("AC10: install() exits 1 on installer failure", async () => {
    const deps: SubcommandDeps = {
      runNativeInstaller: async () => {
        throw new Error("permission denied");
      },
    };

    const { exitCode, stderr } = await runCli(() => install(undefined, {}, deps));
    expect(exitCode).toBe(1);
    expect(stderr).toContain("permission denied");
  });
});
