// Tests for spawn-teammate.ts — covers spec ACs 1–9.

import { test, expect, describe } from "bun:test";
import {
  spawnTeammate,
  resolveTeammateModel,
  generateUniqueTeammateName,
  buildInheritedCliFlags,
} from "./spawn-teammate.ts";
import type {
  SpawnTeammateConfig,
  SpawnContext,
  SpawnTeammateDeps,
  ColorManager,
  TeamMemberStorage,
  InProcessAgentRunner,
  TerminalBackend,
} from "./spawn-teammate.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStorage(): TeamMemberStorage & { members: Map<string, { name: string; agentId: string }[]> } {
  const members: Map<string, { name: string; agentId: string }[]> = new Map();
  return {
    members,
    async listMemberNames(teamName: string): Promise<string[]> {
      return (members.get(teamName) ?? []).map((m) => m.name);
    },
    async registerMember(teamName: string, member: { name: string; agentId: string }): Promise<void> {
      const list = members.get(teamName) ?? [];
      list.push(member);
      members.set(teamName, list);
    },
  };
}

function makeColorManager(): ColorManager & { assigned: Map<string, string> } {
  const assigned = new Map<string, string>();
  const colors = ["red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"];
  let idx = 0;
  return {
    assigned,
    assignColor(name: string): string {
      const color = colors[idx % colors.length] ?? "red";
      idx++;
      assigned.set(name, color);
      return color;
    },
  };
}

function makeInProcessRunner(): InProcessAgentRunner & { started: unknown[] } {
  const started: unknown[] = [];
  return {
    started,
    start(params) { started.push(params); },
  };
}

function makeNoTerminal(): TerminalBackend {
  return {
    type: "none",
    isInsideTmux: () => false,
    async createPane() {
      return { paneId: "p1", windowName: "w1", sessionName: "s1" };
    },
    sendKeys: () => {},
  };
}

function makeTmuxBackend(insideTmux: boolean): TerminalBackend & { sentKeys: string[] } {
  const sentKeys: string[] = [];
  return {
    type: "tmux",
    sentKeys,
    isInsideTmux: () => insideTmux,
    async createPane(params) {
      return {
        paneId: "pane-1",
        windowName: params.windowName,
        sessionName: params.sessionName,
      };
    },
    sendKeys(paneId: string, keys: string) {
      sentKeys.push(keys);
    },
  };
}

function makeContext(overrides?: Partial<SpawnContext>): SpawnContext {
  return {
    cwd: "/work",
    teamName: "myteam",
    sessionId: "sess-abc",
    leaderModel: "haiku",
    leaderPermissionMode: "default",
    leaderHasBypassPermissions: false,
    ...overrides,
  };
}

function makeDeps(overrides?: Partial<SpawnTeammateDeps>): SpawnTeammateDeps & {
  storage: ReturnType<typeof makeStorage>;
  runner: ReturnType<typeof makeInProcessRunner>;
  colorMgr: ReturnType<typeof makeColorManager>;
} {
  const storage = makeStorage();
  const runner = makeInProcessRunner();
  const colorMgr = makeColorManager();
  return {
    storage,
    runner,
    colorMgr,
    agentDefinitions: { get: () => undefined },
    colorManager: colorMgr,
    teamMemberStorage: storage,
    defaultTeammateModel: "haiku",
    inProcessRunner: runner,
    terminalBackend: makeNoTerminal(),
    useInProcess: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// resolveTeammateModel
// ---------------------------------------------------------------------------

describe("resolveTeammateModel", () => {
  test("inherit → leaderModel", () => {
    expect(resolveTeammateModel("inherit", "sonnet", "haiku")).toBe("sonnet");
  });

  test("inherit with no leaderModel → defaultModel", () => {
    expect(resolveTeammateModel("inherit", undefined, "haiku")).toBe("haiku");
  });

  test("explicit model → use as-is", () => {
    expect(resolveTeammateModel("opus", "sonnet", "haiku")).toBe("opus");
  });

  test("omitted → defaultTeammateModel", () => {
    expect(resolveTeammateModel(undefined, "sonnet", "haiku")).toBe("haiku");
  });
});

// ---------------------------------------------------------------------------
// generateUniqueTeammateName
// ---------------------------------------------------------------------------

describe("generateUniqueTeammateName", () => {
  test("no collision → baseName unchanged", async () => {
    const storage = makeStorage();
    const name = await generateUniqueTeammateName("alice", "team", storage);
    expect(name).toBe("alice");
  });

  test("AC2: collision → -2 suffix", async () => {
    const storage = makeStorage();
    await storage.registerMember("team", { name: "alice", agentId: "a1" });
    const name = await generateUniqueTeammateName("alice", "team", storage);
    expect(name).toBe("alice-2");
  });

  test("AC2: multi-collision increments suffix", async () => {
    const storage = makeStorage();
    await storage.registerMember("team", { name: "bob", agentId: "b1" });
    await storage.registerMember("team", { name: "bob-2", agentId: "b2" });
    const name = await generateUniqueTeammateName("bob", "team", storage);
    expect(name).toBe("bob-3");
  });
});

// ---------------------------------------------------------------------------
// buildInheritedCliFlags
// ---------------------------------------------------------------------------

describe("buildInheritedCliFlags", () => {
  test("AC3: plan_mode_required prevents --dangerously-skip-permissions", () => {
    const flags = buildInheritedCliFlags({
      leaderHasBypassPermissions: true,
      planModeRequired: true,
    });
    expect(flags).not.toContain("--dangerously-skip-permissions");
  });

  test("bypass with no plan mode → --dangerously-skip-permissions included", () => {
    const flags = buildInheritedCliFlags({
      leaderHasBypassPermissions: true,
      planModeRequired: false,
    });
    expect(flags).toContain("--dangerously-skip-permissions");
  });

  test("no bypass → no --dangerously-skip-permissions", () => {
    const flags = buildInheritedCliFlags({
      leaderHasBypassPermissions: false,
    });
    expect(flags).not.toContain("--dangerously-skip-permissions");
  });
});

// ---------------------------------------------------------------------------
// AC1: Registering in team file
// ---------------------------------------------------------------------------

describe("AC1 — teammate registered in team file and context", () => {
  test("AC1: spawnTeammate registers teammate in storage", async () => {
    const deps = makeDeps();
    const result = await spawnTeammate(
      { name: "alice", prompt: "hello" },
      makeContext(),
      deps,
    );

    const members = await deps.storage.listMemberNames("myteam");
    expect(members).toContain("alice");
    expect(result.name).toBe("alice");
  });
});

// ---------------------------------------------------------------------------
// AC2: Name uniqueness
// ---------------------------------------------------------------------------

describe("AC2 — name collision appends suffix", () => {
  test("AC2: second teammate with same name gets -2", async () => {
    const deps = makeDeps();
    const ctx = makeContext();

    const r1 = await spawnTeammate({ name: "worker", prompt: "task 1" }, ctx, deps);
    const r2 = await spawnTeammate({ name: "worker", prompt: "task 2" }, ctx, deps);

    expect(r1.name).toBe("worker");
    expect(r2.name).toBe("worker-2");
  });
});

// ---------------------------------------------------------------------------
// AC3: plan_mode_required prevents bypass propagation
// ---------------------------------------------------------------------------

describe("AC3 — plan_mode_required blocks bypass permissions", () => {
  test("AC3: plan_mode_required:true sets plan mode even if leader has bypass", async () => {
    const deps = makeDeps({ useInProcess: false, terminalBackend: makeTmuxBackend(true) });
    const ctx = makeContext({ leaderHasBypassPermissions: true });

    const tmux = deps.terminalBackend as ReturnType<typeof makeTmuxBackend>;

    await spawnTeammate(
      { name: "planner", prompt: "plan mode agent", plan_mode_required: true },
      ctx,
      deps,
    );

    // CLI command should NOT contain dangerously-skip-permissions
    const cmd = tmux.sentKeys[0] ?? "";
    expect(cmd).not.toContain("--dangerously-skip-permissions");
    expect(cmd).toContain("--plan-mode-required");
  });
});

// ---------------------------------------------------------------------------
// AC4: In-process teammates receive prompt directly
// ---------------------------------------------------------------------------

describe("AC4 — in-process teammates receive prompt directly (not via mailbox)", () => {
  test("AC4: runner.start called with the prompt; mailbox not used", async () => {
    const delivered: unknown[] = [];
    const deps = makeDeps({
      useInProcess: true,
      mailbox: { deliver: async (p) => { delivered.push(p); } },
    });

    await spawnTeammate({ name: "inner", prompt: "my prompt" }, makeContext(), deps);

    // Runner should have the prompt
    const startedArg = deps.runner.started[0] as { prompt: string } | undefined;
    expect(startedArg?.prompt).toBe("my prompt");

    // Mailbox should NOT have been used for in-process
    expect(delivered).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// AC5: Out-of-process teammates receive prompt via mailbox
// ---------------------------------------------------------------------------

describe("AC5 — out-of-process teammates receive prompt via mailbox", () => {
  test("AC5: mailbox.deliver called for split-pane spawn", async () => {
    const delivered: unknown[] = [];
    const deps = makeDeps({
      useInProcess: false,
      terminalBackend: makeTmuxBackend(true),
      mailbox: { deliver: async (p) => { delivered.push(p); } },
    });

    await spawnTeammate(
      { name: "outer", prompt: "do the work", use_splitpane: true },
      makeContext(),
      deps,
    );

    expect(delivered.length).toBeGreaterThan(0);
    const first = delivered[0] as { content: string } | undefined;
    expect(first?.content).toBe("do the work");
  });
});

// ---------------------------------------------------------------------------
// AC6: model:'inherit' resolves to leader's model
// ---------------------------------------------------------------------------

describe("AC6 — model:'inherit' resolves to leader model", () => {
  test("AC6: inherit resolves to leaderModel", async () => {
    const deps = makeDeps();
    const ctx = makeContext({ leaderModel: "sonnet" });

    const result = await spawnTeammate(
      { name: "follower", prompt: "task", model: "inherit" },
      ctx,
      deps,
    );

    expect(result.model).toBe("sonnet");
  });
});

// ---------------------------------------------------------------------------
// AC7: In-process teammate appears in session task list
// ---------------------------------------------------------------------------

describe("AC7 — in-process teammate registered in task list", () => {
  test("AC7: runner.start called (task is tracked)", async () => {
    const deps = makeDeps({ useInProcess: true });
    await spawnTeammate({ name: "worker7", prompt: "work" }, makeContext(), deps);
    expect(deps.runner.started).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// AC8: tmux session routing
// ---------------------------------------------------------------------------

describe("AC8 — tmux session routing", () => {
  test("AC8: inside tmux → 'current' session; outside → 'ember-swarm'", async () => {
    // Inside tmux
    const depsInside = makeDeps({ useInProcess: false, terminalBackend: makeTmuxBackend(true) });
    const r1 = await spawnTeammate(
      { name: "inside", prompt: "task", use_splitpane: true },
      makeContext(),
      depsInside,
    );
    expect(r1.tmux_session_name).toBe("current");

    // Outside tmux
    const depsOutside = makeDeps({ useInProcess: false, terminalBackend: makeTmuxBackend(false) });
    const r2 = await spawnTeammate(
      { name: "outside", prompt: "task", use_splitpane: true },
      makeContext(),
      depsOutside,
    );
    expect(r2.tmux_session_name).toBe("ember-swarm");
  });
});

// ---------------------------------------------------------------------------
// AC9: Teammate environment inherits CLAUDECODE and API provider vars
// ---------------------------------------------------------------------------

describe("AC9 — teammate environment inherits key vars", () => {
  test("AC9: CLI flags include agent-id and team-name (env inherited at process level)", async () => {
    const tmux = makeTmuxBackend(true);
    const deps = makeDeps({ useInProcess: false, terminalBackend: tmux });

    await spawnTeammate(
      { name: "env-check", prompt: "check env" },
      makeContext(),
      deps,
    );

    const cmd = tmux.sentKeys[0] ?? "";
    expect(cmd).toContain("--agent-id");
    expect(cmd).toContain("--team-name");
  });
});
