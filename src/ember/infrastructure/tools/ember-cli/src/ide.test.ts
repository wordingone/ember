// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for /ide: no-IDE error (AC1), VS Code open (AC2), JetBrains
// manual instruction (AC3), connection timeout (AC4), disconnect (AC5),
// worktree path (AC6).

import { describe, it, expect, beforeEach } from "bun:test";
import {
  ideCommand,
  setIdeCommandDeps,
  resetIdeCommandDeps,
  connectToIde,
  disconnectFromIde,
  formatWorkspaceFolders,
  IDE_CONNECTION_TIMEOUT_MS,
  type IdeDescriptor,
} from "./ide.ts";
import type { CommandContext } from "../types/command-types.ts";

function makeContext(extras: Record<string, unknown> = {}): CommandContext {
  return {
    sessionId: "test",
    mode: "default",
    cwd: "/projects/myapp",
    ...extras,
  } as unknown as CommandContext;
}

function makeVsCodeIde(overrides: Partial<IdeDescriptor> = {}): IdeDescriptor {
  return {
    name: "VS Code",
    type: "vscode",
    url: "http://localhost:3000",
    ...overrides,
  };
}

function makeJetBrainsIde(overrides: Partial<IdeDescriptor> = {}): IdeDescriptor {
  return {
    name: "IntelliJ IDEA",
    type: "jetbrains",
    url: "http://localhost:4000",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// AC1: /ide open with no valid IDEs → error message
// ---------------------------------------------------------------------------

describe("ideCommand — AC1", () => {
  beforeEach(() => resetIdeCommandDeps());

  it("AC1: /ide open with no valid IDEs returns error message", async () => {
    setIdeCommandDeps({
      getValidIdes: () => [],
    });
    const ctx = makeContext({ options: {} });
    const result = await ideCommand.execute("open", ctx);
    expect((result as { message: string }).message).toBe(
      "No IDEs with Ember CLI extension detected.",
    );
  });
});

// ---------------------------------------------------------------------------
// AC2: /ide open with VS Code runs `code <path>` and reports success/failure
// ---------------------------------------------------------------------------

describe("ideCommand — AC2", () => {
  beforeEach(() => resetIdeCommandDeps());

  it("AC2: VS Code ide open on success reports success", async () => {
    setIdeCommandDeps({
      getValidIdes: () => [makeVsCodeIde()],
      getWorktreePath: () => null,
      runCodeCommand: async () => ({ exitCode: 0 }),
    });
    const ctx = makeContext();
    const result = await ideCommand.execute("open", ctx);
    expect((result as { message: string }).message).toContain("Opened");
  });

  it("AC2: VS Code ide open on failure reports failure", async () => {
    setIdeCommandDeps({
      getValidIdes: () => [makeVsCodeIde()],
      getWorktreePath: () => null,
      runCodeCommand: async () => ({ exitCode: 1 }),
    });
    const ctx = makeContext();
    const result = await ideCommand.execute("open", ctx);
    expect((result as { message: string }).message).toContain("Failed");
  });

  it("AC2: Cursor IDE also uses code command", async () => {
    const cap = { path: null as string | null };
    setIdeCommandDeps({
      getValidIdes: () => [makeVsCodeIde({ type: "cursor", name: "Cursor" })],
      getWorktreePath: () => null,
      runCodeCommand: async (path) => { cap.path = path; return { exitCode: 0 }; },
    });
    await ideCommand.execute("open", makeContext());
    expect(cap.path).toBe("/projects/myapp");
  });
});

// ---------------------------------------------------------------------------
// AC3: /ide open with JetBrains IDE returns manual instruction
// ---------------------------------------------------------------------------

describe("ideCommand — AC3", () => {
  beforeEach(() => resetIdeCommandDeps());

  it("AC3: JetBrains returns manual-open instruction", async () => {
    setIdeCommandDeps({
      getValidIdes: () => [makeJetBrainsIde()],
      getWorktreePath: () => null,
    });
    const ctx = makeContext();
    const result = await ideCommand.execute("open", ctx);
    expect((result as { message: string }).message).toContain("manually");
    expect((result as { message: string }).message).toContain("/projects/myapp");
  });
});

// ---------------------------------------------------------------------------
// AC4: Connecting to an IDE waits up to 35s for connected or failed
// ---------------------------------------------------------------------------

describe("connectToIde — AC4", () => {
  beforeEach(() => resetIdeCommandDeps());

  it("AC4: resolves 'connected' message when MCP status becomes connected", async () => {
    const cap = { cb: null as ((s: "connected" | "failed" | "pending") => void) | null };
    setIdeCommandDeps({
      onChangeDynamicMcpConfig: () => {},
      watchIdeMcpStatus: (cb) => {
        cap.cb = cb;
        return () => {};
      },
      getTimeoutMs: () => 100, // fast timeout for tests
    });

    const messages: string[] = [];
    const promise = connectToIde(makeVsCodeIde(), (msg) => { if (msg) messages.push(msg); });

    // Simulate connected status
    await new Promise((r) => setTimeout(r, 10));
    cap.cb?.("connected");
    await promise;

    expect(messages).toContain("Connected to VS Code.");
  });

  it("AC4: resolves 'failed' message when MCP status becomes failed", async () => {
    const cap = { cb: null as ((s: "connected" | "failed" | "pending") => void) | null };
    setIdeCommandDeps({
      onChangeDynamicMcpConfig: () => {},
      watchIdeMcpStatus: (cb) => {
        cap.cb = cb;
        return () => {};
      },
      getTimeoutMs: () => 100,
    });

    const messages: string[] = [];
    const promise = connectToIde(makeVsCodeIde(), (msg) => { if (msg) messages.push(msg); });
    await new Promise((r) => setTimeout(r, 10));
    cap.cb?.("failed");
    await promise;

    expect(messages).toContain("Failed to connect to VS Code.");
  });

  it("AC4: times out after getTimeoutMs with a timeout message", async () => {
    setIdeCommandDeps({
      onChangeDynamicMcpConfig: () => {},
      watchIdeMcpStatus: () => () => {}, // never fires
      getTimeoutMs: () => 50, // fast timeout
    });

    const messages: string[] = [];
    await connectToIde(makeVsCodeIde(), (msg) => { if (msg) messages.push(msg); });

    expect(messages.some((m) => m.includes("timed out"))).toBe(true);
  });

  it("AC4: IDE_CONNECTION_TIMEOUT_MS is 35000ms", () => {
    expect(IDE_CONNECTION_TIMEOUT_MS).toBe(35_000);
  });
});

// ---------------------------------------------------------------------------
// AC5: Disconnect clears IDE client, removes mcp__ide__* tools
// ---------------------------------------------------------------------------

describe("disconnectFromIde — AC5", () => {
  beforeEach(() => resetIdeCommandDeps());

  it("AC5: clears server cache", async () => {
    let cacheCleared = false;
    setIdeCommandDeps({
      clearIdeServerCache: () => { cacheCleared = true; },
      removeIdeFromAppState: async () => {},
      onChangeDynamicMcpConfig: () => {},
    });
    await disconnectFromIde("VS Code", async () => {}, (msg) => { void msg; });
    expect(cacheCleared).toBe(true);
  });

  it("AC5: removes IDE from app state", async () => {
    let appStateRemoved = false;
    setIdeCommandDeps({
      clearIdeServerCache: () => {},
      removeIdeFromAppState: async () => { appStateRemoved = true; },
      onChangeDynamicMcpConfig: () => {},
    });
    await disconnectFromIde("VS Code", async () => {}, (msg) => { void msg; });
    expect(appStateRemoved).toBe(true);
  });

  it("AC5: clears dynamic MCP config (null)", async () => {
    let configCleared = false;
    setIdeCommandDeps({
      clearIdeServerCache: () => {},
      removeIdeFromAppState: async () => {},
      onChangeDynamicMcpConfig: (config) => { if (config === null) configCleared = true; },
    });
    await disconnectFromIde("VS Code", async () => {}, () => {});
    expect(configCleared).toBe(true);
  });

  it("AC5: calls onDone with 'Disconnected' message", async () => {
    setIdeCommandDeps({
      clearIdeServerCache: () => {},
      removeIdeFromAppState: async () => {},
      onChangeDynamicMcpConfig: () => {},
    });
    const messages: string[] = [];
    await disconnectFromIde("IntelliJ", async () => {}, (msg) => { if (msg) messages.push(msg); });
    expect(messages.some((m) => m.includes("Disconnected from IntelliJ"))).toBe(true);
  });

  it("AC5: 'No IDE selected' when name is undefined", async () => {
    setIdeCommandDeps({});
    const messages: string[] = [];
    await disconnectFromIde(undefined, async () => {}, (msg) => { if (msg) messages.push(msg); });
    expect(messages.some((m) => m.includes("No IDE selected"))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC6: In a worktree, /ide open uses the worktree path
// ---------------------------------------------------------------------------

describe("ideCommand — AC6", () => {
  beforeEach(() => resetIdeCommandDeps());

  it("AC6: uses worktree path when in a worktree", async () => {
    const cap = { path: null as string | null };
    setIdeCommandDeps({
      getValidIdes: () => [makeVsCodeIde()],
      getWorktreePath: () => "/projects/myapp/.ember/worktrees/feature-branch",
      runCodeCommand: async (path) => { cap.path = path; return { exitCode: 0 }; },
    });
    await ideCommand.execute("open", makeContext());
    expect(cap.path).toBe("/projects/myapp/.ember/worktrees/feature-branch");
  });

  it("AC6: uses CWD when not in a worktree (null)", async () => {
    const cap = { path: null as string | null };
    setIdeCommandDeps({
      getValidIdes: () => [makeVsCodeIde()],
      getWorktreePath: () => null,
      runCodeCommand: async (path) => { cap.path = path; return { exitCode: 0 }; },
    });
    await ideCommand.execute("open", makeContext({ cwd: "/projects/myapp" }));
    expect(cap.path).toBe("/projects/myapp");
  });
});

// ---------------------------------------------------------------------------
// formatWorkspaceFolders
// ---------------------------------------------------------------------------

describe("formatWorkspaceFolders", () => {
  it("strips CWD prefix", () => {
    const result = formatWorkspaceFolders(
      ["/projects/myapp/src", "/projects/myapp/tests"],
      "/projects/myapp",
    );
    expect(result).toBe("src, tests");
  });

  it("shows at most 2 folders then ', …'", () => {
    const result = formatWorkspaceFolders(
      ["/p/a", "/p/b", "/p/c"],
      "/p",
    );
    expect(result).toBe("a, b, …");
  });

  it("no ellipsis for exactly 2 folders", () => {
    const result = formatWorkspaceFolders(["/p/a", "/p/b"], "/p");
    expect(result).not.toContain("…");
  });
});

// ---------------------------------------------------------------------------
// Command structure
// ---------------------------------------------------------------------------

describe("ideCommand structure", () => {
  it("name is 'ide'", () => expect(ideCommand.name).toBe("ide"));
  it("type is local-jsx", () => expect(ideCommand.type).toBe("local-jsx"));
  it("is enabled", () => expect(ideCommand.isEnabled()).toBe(true));
});
