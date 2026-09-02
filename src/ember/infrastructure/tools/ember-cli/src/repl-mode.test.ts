// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for repl-mode.ts — covers AC1–AC6 from repl-mode.md spec.
import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import {
  isReplMode,
  getReplPrimitiveTools,
  filterToolsForReplMode,
  REPL_PRIMITIVE_TOOL_NAMES,
} from "./repl-mode.ts";
import { buildTool } from "../core/tool-interface.ts";

// --- Environment helpers ---

function setEnv(vars: Record<string, string | undefined>) {
  for (const [k, v] of Object.entries(vars)) {
    if (v === undefined) {
      delete process.env[k];
    } else {
      process.env[k] = v;
    }
  }
}

// Capture env before each test and restore after
let savedEnv: Record<string, string | undefined>;

beforeEach(() => {
  savedEnv = {};
  for (const k of ["EMBER_REPL", "EMBER_REPL_MODE", "USER_TYPE", "EMBER_ENTRYPOINT"]) {
    savedEnv[k] = process.env[k];
    delete process.env[k];
  }
});

afterEach(() => {
  setEnv(savedEnv);
});

// --- AC2: EMBER_REPL=1 enables REPL mode ---
describe("AC2: EMBER_REPL env var", () => {
  test("EMBER_REPL=1 enables REPL mode", () => {
    setEnv({ EMBER_REPL: "1" });
    expect(isReplMode()).toBe(true);
  });

  test("EMBER_REPL=true enables REPL mode", () => {
    setEnv({ EMBER_REPL: "true" });
    expect(isReplMode()).toBe(true);
  });

  // AC3: EMBER_REPL=0 in ant/cli session overrides the default-on
  test("AC3: EMBER_REPL=0 disables REPL mode even in ant+cli session", () => {
    setEnv({ EMBER_REPL: "0", USER_TYPE: "ant", EMBER_ENTRYPOINT: "cli" });
    expect(isReplMode()).toBe(false);
  });

  test("EMBER_REPL=false disables REPL mode", () => {
    setEnv({ EMBER_REPL: "false" });
    expect(isReplMode()).toBe(false);
  });
});

// --- EMBER_REPL_MODE ---
describe("EMBER_REPL_MODE env var", () => {
  test("EMBER_REPL_MODE=1 enables REPL mode", () => {
    setEnv({ EMBER_REPL_MODE: "1" });
    expect(isReplMode()).toBe(true);
  });

  test("EMBER_REPL_MODE=0 does not enable", () => {
    setEnv({ EMBER_REPL_MODE: "0" });
    expect(isReplMode()).toBe(false);
  });
});

// --- Build-time default: ant+cli ---
describe("build-time default: ant/cli", () => {
  test("USER_TYPE=ant + EMBER_ENTRYPOINT=cli enables REPL mode by default", () => {
    setEnv({ USER_TYPE: "ant", EMBER_ENTRYPOINT: "cli" });
    expect(isReplMode()).toBe(true);
  });

  test("only USER_TYPE=ant without EMBER_ENTRYPOINT=cli does not enable", () => {
    setEnv({ USER_TYPE: "ant" });
    expect(isReplMode()).toBe(false);
  });
});

// --- AC4: SDK sessions do not enable REPL by default ---
describe("AC4: SDK sessions default off", () => {
  test("no env vars set → REPL mode off (SDK default)", () => {
    // All relevant env vars cleared in beforeEach
    expect(isReplMode()).toBe(false);
  });
});

// --- AC5: getReplPrimitiveTools returns 8 tools regardless of mode ---
describe("AC5: getReplPrimitiveTools", () => {
  test("returns exactly 8 tools", () => {
    const tools = getReplPrimitiveTools();
    expect(tools.length).toBe(8);
  });

  test("returns the same instance on repeated calls (singleton)", () => {
    const first = getReplPrimitiveTools();
    const second = getReplPrimitiveTools();
    expect(first).toBe(second);
  });

  test("contains tools with correct names matching REPL_PRIMITIVE_TOOL_NAMES", () => {
    const tools = getReplPrimitiveTools();
    const names = tools.map((t) => t.name);
    for (const expectedName of REPL_PRIMITIVE_TOOL_NAMES) {
      expect(names).toContain(expectedName);
    }
  });

  test("always returns 8 tools regardless of REPL mode state", () => {
    setEnv({ EMBER_REPL: "0" });
    const toolsWhenOff = getReplPrimitiveTools();
    setEnv({ EMBER_REPL: "1" });
    const toolsWhenOn = getReplPrimitiveTools();
    expect(toolsWhenOff.length).toBe(8);
    expect(toolsWhenOn.length).toBe(8);
    expect(toolsWhenOff).toBe(toolsWhenOn); // same singleton
  });
});

// --- AC1: When REPL mode is active, primitive tools are hidden from model tool list ---
describe("AC1: filterToolsForReplMode hides primitive tools when active", () => {
  function makeDummyTool(name: string) {
    return buildTool({
      name,
      call: async () => ({ data: null }),
      description: () => name,
      prompt: () => "",
      mapToolResultToToolResultBlockParam: (_, id) => ({
        type: "tool_result" as const,
        tool_use_id: id,
        content: "",
      }),
    });
  }

  test("hides Read, Write, Edit, Glob, Grep, Bash, NotebookEdit, Agent when REPL active", () => {
    setEnv({ EMBER_REPL: "1" });
    const allTools = [
      ...REPL_PRIMITIVE_TOOL_NAMES.map(makeDummyTool),
      makeDummyTool("some_other_tool"),
    ];
    const filtered = filterToolsForReplMode(allTools);
    const filteredNames = filtered.map((t) => t.name);
    // Primitive tools absent
    for (const name of REPL_PRIMITIVE_TOOL_NAMES) {
      expect(filteredNames).not.toContain(name);
    }
    // Other tools present
    expect(filteredNames).toContain("some_other_tool");
  });

  test("passes all tools through when REPL mode is off", () => {
    setEnv({ EMBER_REPL: "0" });
    const allTools = REPL_PRIMITIVE_TOOL_NAMES.map(makeDummyTool);
    const filtered = filterToolsForReplMode(allTools);
    expect(filtered.length).toBe(allTools.length);
  });
});

// --- REPL_PRIMITIVE_TOOL_NAMES constant ---
describe("REPL_PRIMITIVE_TOOL_NAMES", () => {
  test("contains 8 entries", () => {
    expect(REPL_PRIMITIVE_TOOL_NAMES.length).toBe(8);
  });

  test("includes expected tool names", () => {
    const expected = ["read", "write", "edit", "glob", "grep", "bash", "notebook_edit", "agent"];
    for (const name of expected) {
      expect(REPL_PRIMITIVE_TOOL_NAMES).toContain(name as never);
    }
  });
});
