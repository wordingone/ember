// Tests for command-registry.ts — one describe block per AC.
//
// All external dependencies are injected via setCommandRegistryDeps so that
// actual command definitions, plugins, and MCP state (deferred to later layers)
// are never required. Fakes supply the minimum RegistryCommand shape needed to
// exercise each acceptance criterion.

import { describe, it, expect, beforeEach } from "bun:test";
import {
  getCommands,
  filterCommandsForRemoteMode,
  isBridgeSafeCommand,
  getSkillToolCommands,
  getSlashCommandToolSkills,
  getMcpSkillCommands,
  findCommand,
  getCommand,
  hasCommand,
  formatDescriptionWithSource,
  clearCommandMemoizationCaches,
  clearCommandsCache,
  setCommandRegistryDeps,
  resetCommandRegistryForTests,
  meetsAvailabilityRequirement,
  REMOTE_SAFE_COMMANDS,
  BRIDGE_SAFE_COMMANDS,
  type RegistryCommand,
} from "./command-registry.ts";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/** Minimal RegistryCommand factory — only name + description are required in
 *  practice; all registry-specific fields are optional. */
function makeCmd(
  overrides: Partial<RegistryCommand> & { name: string; description: string },
): RegistryCommand {
  return {
    isEnabled: () => true,
    execute: async () => {},
    ...overrides,
  } as RegistryCommand;
}

/** Reset deps + caches before every test to prevent cross-test contamination. */
beforeEach(() => {
  resetCommandRegistryForTests();
});

// ---------------------------------------------------------------------------
// AC1: getCommands(cwd) called twice with same cwd returns the same array
//      without re-loading (second call is from cache).
// ---------------------------------------------------------------------------

describe("AC1 — memoization by cwd", () => {
  it("returns the same array instance on second call with the same cwd", async () => {
    let loadCount = 0;
    setCommandRegistryDeps({
      getBuiltinCommands: () => {
        loadCount++;
        return [makeCmd({ name: "help", description: "Show help" })];
      },
    });

    const r1 = await getCommands("/proj");
    const r2 = await getCommands("/proj");

    expect(r1).toBe(r2); // same reference — loaded only once
    expect(loadCount).toBe(1);
  });

  it("loads independently for different cwd values", async () => {
    let callArgs: string[] = [];
    setCommandRegistryDeps({
      getBuiltinCommands: () => [],
      getSkillDirCommands: async (cwd) => {
        callArgs.push(cwd);
        return [makeCmd({ name: `skill-${cwd.slice(-1)}`, description: "A skill" })];
      },
    });

    const rA = await getCommands("/a");
    const rB = await getCommands("/b");

    expect(callArgs).toEqual(["/a", "/b"]);
    expect(rA).not.toBe(rB);
    expect(rA[0]?.name).toBe("skill-a");
    expect(rB[0]?.name).toBe("skill-b");
  });
});

// ---------------------------------------------------------------------------
// AC2: getCommands(cwd) after clearCommandsCache() re-loads all sources.
// ---------------------------------------------------------------------------

describe("AC2 — clearCommandsCache triggers re-load", () => {
  it("re-loads command sources after clearCommandsCache()", async () => {
    let loadCount = 0;
    setCommandRegistryDeps({
      getBuiltinCommands: () => {
        loadCount++;
        return [makeCmd({ name: "help", description: "Help" })];
      },
    });

    await getCommands("/proj");
    clearCommandsCache();
    await getCommands("/proj");

    expect(loadCount).toBe(2);
  });

  it("clearCommandMemoizationCaches does NOT re-load plugin commands", async () => {
    let pluginLoadCount = 0;
    setCommandRegistryDeps({
      getPluginCommands: async () => {
        pluginLoadCount++;
        return [makeCmd({ name: "plugin-cmd", description: "Plugin", pluginName: "myplugin" })];
      },
    });

    await getCommands("/proj");
    clearCommandMemoizationCaches(); // memo only — plugin cache preserved
    await getCommands("/proj");

    // plugin loaded once (cached across memo-clears)
    expect(pluginLoadCount).toBe(1);
  });

  it("clearCommandsCache DOES re-load plugin commands", async () => {
    let pluginLoadCount = 0;
    setCommandRegistryDeps({
      getPluginCommands: async () => {
        pluginLoadCount++;
        return [makeCmd({ name: "plugin-cmd", description: "Plugin", pluginName: "myplugin" })];
      },
    });

    await getCommands("/proj");
    clearCommandsCache(); // full clear — plugin cache dropped
    await getCommands("/proj");

    expect(pluginLoadCount).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// AC3: availability: ['cloud'] — absent when NOT a cloud subscriber.
// ---------------------------------------------------------------------------

describe("AC3 — availability filter: cloud absent when not subscriber", () => {
  it("excludes the command when isCloudSubscriber returns false (default)", async () => {
    // no isCloudSubscriber dep set → defaults to false
    setCommandRegistryDeps({
      getBuiltinCommands: () => [
        makeCmd({ name: "premium", description: "Premium", availability: ["cloud"] }),
        makeCmd({ name: "free", description: "Free" }),
      ],
    });

    const cmds = await getCommands("/proj");
    const names = cmds.map((c) => c.name);

    expect(names).not.toContain("premium");
    expect(names).toContain("free");
  });
});

// ---------------------------------------------------------------------------
// AC4: availability: ['cloud'] — present when IS a cloud subscriber.
// ---------------------------------------------------------------------------

describe("AC4 — availability filter: cloud present when subscriber", () => {
  it("includes the command when isCloudSubscriber returns true", async () => {
    setCommandRegistryDeps({
      isCloudSubscriber: () => true,
      getBuiltinCommands: () => [
        makeCmd({ name: "premium", description: "Premium", availability: ["cloud"] }),
      ],
    });

    const cmds = await getCommands("/proj");
    const names = cmds.map((c) => c.name);

    expect(names).toContain("premium");
  });
});

// ---------------------------------------------------------------------------
// AC5: filterCommandsForRemoteMode returns only REMOTE_SAFE_COMMANDS names.
// ---------------------------------------------------------------------------

describe("AC5 — filterCommandsForRemoteMode", () => {
  it("keeps only commands whose name is in REMOTE_SAFE_COMMANDS", () => {
    const input: RegistryCommand[] = [
      makeCmd({ name: "help", description: "Help" }),   // in list
      makeCmd({ name: "clear", description: "Clear" }), // in list
      makeCmd({ name: "dangerous", description: "Nope" }), // NOT in list
    ];

    const result = filterCommandsForRemoteMode(input);
    const names = result.map((c) => c.name);

    expect(names).toContain("help");
    expect(names).toContain("clear");
    expect(names).not.toContain("dangerous");
  });

  it("REMOTE_SAFE_COMMANDS contains the exact spec-listed names", () => {
    expect(REMOTE_SAFE_COMMANDS).toContain("session");
    expect(REMOTE_SAFE_COMMANDS).toContain("exit");
    expect(REMOTE_SAFE_COMMANDS).toContain("clear");
    expect(REMOTE_SAFE_COMMANDS).toContain("help");
    expect(REMOTE_SAFE_COMMANDS).toContain("theme");
    expect(REMOTE_SAFE_COMMANDS).toContain("color");
    expect(REMOTE_SAFE_COMMANDS).toContain("vim");
    expect(REMOTE_SAFE_COMMANDS).toContain("cost");
    expect(REMOTE_SAFE_COMMANDS).toContain("usage");
    expect(REMOTE_SAFE_COMMANDS).toContain("copy");
    expect(REMOTE_SAFE_COMMANDS).toContain("btw");
    expect(REMOTE_SAFE_COMMANDS).toContain("feedback");
    expect(REMOTE_SAFE_COMMANDS).toContain("plan");
    expect(REMOTE_SAFE_COMMANDS).toContain("keybindings");
    expect(REMOTE_SAFE_COMMANDS).toContain("statusline");
    expect(REMOTE_SAFE_COMMANDS).toContain("stickers");
    expect(REMOTE_SAFE_COMMANDS).toContain("mobile");
    expect(REMOTE_SAFE_COMMANDS).toHaveLength(17);
  });
});

// ---------------------------------------------------------------------------
// AC6: isBridgeSafeCommand returns true for type='prompt'.
// ---------------------------------------------------------------------------

describe("AC6 — isBridgeSafeCommand: prompt type is safe", () => {
  it("returns true for type='prompt' even when name is not in BRIDGE_SAFE_COMMANDS", () => {
    const cmd = makeCmd({ name: "my-skill", description: "A skill", type: "prompt" });
    expect(isBridgeSafeCommand(cmd)).toBe(true);
  });

  it("returns true for a prompt command whose name also happens to be in BRIDGE_SAFE_COMMANDS", () => {
    const cmd = makeCmd({ name: "compact", description: "Compact", type: "prompt" });
    expect(isBridgeSafeCommand(cmd)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC7: isBridgeSafeCommand returns false for type='local-jsx'.
// ---------------------------------------------------------------------------

describe("AC7 — isBridgeSafeCommand: local-jsx type is unsafe", () => {
  it("returns false for type='local-jsx' regardless of name", () => {
    const cmd = makeCmd({ name: "clear", description: "Clear", type: "local-jsx" });
    // 'clear' is in BRIDGE_SAFE_COMMANDS but type='local-jsx' overrides to false
    expect(isBridgeSafeCommand(cmd)).toBe(false);
  });

  it("returns false for any local-jsx command not in the bridge list", () => {
    const cmd = makeCmd({ name: "fancy-ui", description: "Fancy", type: "local-jsx" });
    expect(isBridgeSafeCommand(cmd)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC8: A dynamic skill whose name matches a built-in is dropped; the built-in
//      is retained.
// ---------------------------------------------------------------------------

describe("AC8 — dynamic skill dedup: built-in wins over dynamic with same name", () => {
  it("drops a dynamic skill when a built-in with the same name already exists", async () => {
    const builtin = makeCmd({ name: "help", description: "Built-in help" });
    const dynamic = makeCmd({ name: "help", description: "Dynamic help", isDynamic: true });

    setCommandRegistryDeps({
      getBuiltinCommands: () => [builtin],
      getDynamicSkillCommands: async () => [dynamic],
    });

    const cmds = await getCommands("/proj");
    const helpCmds = cmds.filter((c) => c.name === "help");

    expect(helpCmds).toHaveLength(1);
    // The retained one is the built-in (description differs)
    expect(helpCmds[0]?.description).toBe("Built-in help");
  });

  it("includes a dynamic skill when its name is not in any other source", async () => {
    setCommandRegistryDeps({
      getBuiltinCommands: () => [makeCmd({ name: "help", description: "Help" })],
      getDynamicSkillCommands: async () => [
        makeCmd({ name: "my-dynamic", description: "Dynamic only", isDynamic: true }),
      ],
    });

    const cmds = await getCommands("/proj");
    const names = cmds.map((c) => c.name);

    expect(names).toContain("my-dynamic");
    expect(names).toContain("help");
  });
});

// ---------------------------------------------------------------------------
// AC9: getCommand('nonexistent', commands) throws with available names listed.
// ---------------------------------------------------------------------------

describe("AC9 — getCommand throws with available list on miss", () => {
  it("throws an error listing available command names when not found", () => {
    const commands: RegistryCommand[] = [
      makeCmd({ name: "help", description: "Help" }),
      makeCmd({ name: "clear", description: "Clear" }),
    ];

    expect(() => getCommand("nonexistent", commands)).toThrow();
    try {
      getCommand("nonexistent", commands);
    } catch (err) {
      const msg = (err as Error).message;
      expect(msg).toContain("help");
      expect(msg).toContain("clear");
      expect(msg).toContain("nonexistent");
    }
  });

  it("returns the command when found by name", () => {
    const commands = [makeCmd({ name: "help", description: "Help" })];
    expect(getCommand("help", commands).name).toBe("help");
  });

  it("returns the command when found by alias", () => {
    const commands = [makeCmd({ name: "help", description: "Help", aliases: ["h", "?"] })];
    expect(getCommand("h", commands).name).toBe("help");
    expect(getCommand("?", commands).name).toBe("help");
  });
});

// ---------------------------------------------------------------------------
// AC10: getSkillToolCommands excludes disableModelInvocation:true even when
//       the command is prompt-type with a description.
// ---------------------------------------------------------------------------

describe("AC10 — getSkillToolCommands excludes disableModelInvocation:true", () => {
  it("excludes a prompt command that has disableModelInvocation:true", async () => {
    setCommandRegistryDeps({
      getBuiltinCommands: () => [
        makeCmd({
          name: "invokable",
          description: "Can be invoked",
          type: "prompt",
        }),
        makeCmd({
          name: "blocked",
          description: "Cannot be invoked",
          type: "prompt",
          disableModelInvocation: true,
        }),
      ],
    });

    const cmds = await getSkillToolCommands("/proj");
    const names = cmds.map((c) => c.name);

    expect(names).toContain("invokable");
    expect(names).not.toContain("blocked");
  });

  it("also excludes non-prompt commands regardless of disableModelInvocation", async () => {
    setCommandRegistryDeps({
      getBuiltinCommands: () => [
        makeCmd({ name: "jsx-cmd", description: "Local JSX", type: "local-jsx" }),
      ],
    });

    const cmds = await getSkillToolCommands("/proj");
    expect(cmds.map((c) => c.name)).not.toContain("jsx-cmd");
  });
});

// ---------------------------------------------------------------------------
// AC11: formatDescriptionWithSource appends the plugin name for plugin cmds.
// ---------------------------------------------------------------------------

describe("AC11 — formatDescriptionWithSource annotates plugin commands", () => {
  it("appends the plugin name for a plugin-sourced command", () => {
    const cmd = makeCmd({
      name: "myplugin-cmd",
      description: "Does something",
      pluginName: "my-awesome-plugin",
    });
    const result = formatDescriptionWithSource(cmd);
    expect(result).toContain("Does something");
    expect(result).toContain("my-awesome-plugin");
  });

  it("annotates bundled skills with 'bundled'", () => {
    const cmd = makeCmd({ name: "bundled-skill", description: "A bundled skill", isBundled: true });
    const result = formatDescriptionWithSource(cmd);
    expect(result).toContain("bundled");
  });

  it("annotates workflow commands with 'workflow'", () => {
    const cmd = makeCmd({ name: "wf", description: "A workflow", isWorkflow: true });
    const result = formatDescriptionWithSource(cmd);
    expect(result).toContain("workflow");
  });

  it("annotates settings-file commands with the settings source label", () => {
    const cmd = makeCmd({
      name: "settings-cmd",
      description: "From settings",
      settingsSource: "project settings",
    });
    const result = formatDescriptionWithSource(cmd);
    expect(result).toContain("project settings");
  });

  it("returns description as-is for built-in commands (no annotation)", () => {
    const cmd = makeCmd({ name: "help", description: "Show help" });
    const result = formatDescriptionWithSource(cmd);
    expect(result).toBe("Show help");
  });
});

// ---------------------------------------------------------------------------
// AC12: MCP commands absent from getCommands() when the MCP flag is disabled.
// ---------------------------------------------------------------------------

describe("AC12 — MCP commands absent when feature flag disabled", () => {
  it("excludes MCP commands when isMcpSkillsEnabled returns false (default)", async () => {
    // no isMcpSkillsEnabled dep set → defaults to false
    setCommandRegistryDeps({
      getMcpCommandList: () => [
        makeCmd({ name: "mcp-tool", description: "MCP tool", isMcpSkill: true, type: "prompt" }),
      ],
    });

    const cmds = await getCommands("/proj");
    expect(cmds.map((c) => c.name)).not.toContain("mcp-tool");
  });

  it("includes MCP commands when isMcpSkillsEnabled returns true", async () => {
    setCommandRegistryDeps({
      isMcpSkillsEnabled: () => true,
      getMcpCommandList: () => [
        makeCmd({ name: "mcp-tool", description: "MCP tool", isMcpSkill: true, type: "prompt" }),
      ],
    });

    const cmds = await getCommands("/proj");
    expect(cmds.map((c) => c.name)).toContain("mcp-tool");
  });
});

// ---------------------------------------------------------------------------
// Additional behavioral tests
// ---------------------------------------------------------------------------

describe("meetsAvailabilityRequirement", () => {
  it("returns true when availability is empty", () => {
    expect(meetsAvailabilityRequirement(makeCmd({ name: "x", description: "x", availability: [] }))).toBe(true);
  });

  it("returns true when availability is unset", () => {
    expect(meetsAvailabilityRequirement(makeCmd({ name: "x", description: "x" }))).toBe(true);
  });

  it("returns false for ['cloud'] when subscriber dep not set", () => {
    const cmd = makeCmd({ name: "x", description: "x", availability: ["cloud"] });
    expect(meetsAvailabilityRequirement(cmd)).toBe(false);
  });

  it("returns true for ['console'] when isConsoleUser returns true", () => {
    setCommandRegistryDeps({ isConsoleUser: () => true });
    const cmd = makeCmd({ name: "x", description: "x", availability: ["console"] });
    expect(meetsAvailabilityRequirement(cmd)).toBe(true);
  });
});

describe("findCommand and hasCommand", () => {
  const commands = [
    makeCmd({ name: "help", description: "Help", aliases: ["h"] }),
    makeCmd({ name: "clear", description: "Clear" }),
  ];

  it("findCommand finds by name", () => {
    expect(findCommand("help", commands)?.name).toBe("help");
  });

  it("findCommand finds by alias", () => {
    expect(findCommand("h", commands)?.name).toBe("help");
  });

  it("findCommand returns undefined for unknown name", () => {
    expect(findCommand("unknown", commands)).toBeUndefined();
  });

  it("hasCommand returns true for known name", () => {
    expect(hasCommand("clear", commands)).toBe(true);
  });

  it("hasCommand returns false for unknown name", () => {
    expect(hasCommand("nope", commands)).toBe(false);
  });
});

describe("getMcpSkillCommands — live read, not memoized", () => {
  it("returns empty list when no dep set", () => {
    expect(getMcpSkillCommands()).toEqual([]);
  });

  it("filters to prompt-type isMcpSkill commands without disableModelInvocation", () => {
    setCommandRegistryDeps({
      getMcpCommandList: () => [
        makeCmd({ name: "a", description: "A", type: "prompt", isMcpSkill: true }),
        makeCmd({ name: "b", description: "B", type: "local-jsx", isMcpSkill: true }),
        makeCmd({ name: "c", description: "C", type: "prompt", isMcpSkill: true, disableModelInvocation: true }),
        makeCmd({ name: "d", description: "D", type: "prompt", isMcpSkill: false }),
      ],
    });
    const names = getMcpSkillCommands().map((c) => c.name);
    expect(names).toContain("a");
    expect(names).not.toContain("b"); // local-jsx
    expect(names).not.toContain("c"); // disableModelInvocation
    expect(names).not.toContain("d"); // not isMcpSkill
  });
});

describe("getSlashCommandToolSkills", () => {
  it("includes commands with description but no whenToUse", async () => {
    setCommandRegistryDeps({
      getBuiltinCommands: () => [
        makeCmd({ name: "described", description: "Has description" }),
      ],
    });
    const cmds = await getSlashCommandToolSkills("/proj");
    expect(cmds.map((c) => c.name)).toContain("described");
  });

  it("includes commands with whenToUse even if description is empty", async () => {
    setCommandRegistryDeps({
      getBuiltinCommands: () => [
        // description is required by the Command interface; we give it an empty string
        // but the command has whenToUse
        makeCmd({ name: "when-only", description: "", whenToUse: "Use when X" }),
      ],
    });
    const cmds = await getSlashCommandToolSkills("/proj");
    expect(cmds.map((c) => c.name)).toContain("when-only");
  });
});

describe("BRIDGE_SAFE_COMMANDS constants", () => {
  it("contains the spec-listed names", () => {
    expect(BRIDGE_SAFE_COMMANDS).toContain("compact");
    expect(BRIDGE_SAFE_COMMANDS).toContain("clear");
    expect(BRIDGE_SAFE_COMMANDS).toContain("cost");
    expect(BRIDGE_SAFE_COMMANDS).toContain("summary");
    expect(BRIDGE_SAFE_COMMANDS).toContain("releaseNotes");
    expect(BRIDGE_SAFE_COMMANDS).toContain("files");
  });

  it("returns true from isBridgeSafeCommand for a command in BRIDGE_SAFE_COMMANDS with no type", () => {
    const cmd = makeCmd({ name: "compact", description: "Compact" }); // no type set
    expect(isBridgeSafeCommand(cmd)).toBe(true);
  });
});
