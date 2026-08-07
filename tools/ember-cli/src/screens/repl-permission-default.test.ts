// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { buildTool } from "../core/tool-interface.ts";
import {
  DEFAULT_REPL_PERMISSION_MODE,
  REPL_PERMISSION_CYCLE,
  authorizeReplTool,
  cycleReplPermissionMode,
} from "./repl.ts";
import { statusBarText } from "../components/status-bar.ts";

const readTool = buildTool({
  name: "read",
  description: () => "read",
  isReadOnly: () => true,
  call: async () => ({ data: "read" }),
  mapToolResultToToolResultBlockParam: (data, id) => ({
    type: "tool_result",
    tool_use_id: id,
    content: String(data),
  }),
});

const writeTool = buildTool({
  name: "write",
  description: () => "write",
  isReadOnly: () => false,
  call: async () => ({ data: "write" }),
  mapToolResultToToolResultBlockParam: (data, id) => ({
    type: "tool_result",
    tool_use_id: id,
    content: String(data),
  }),
});

describe("#1215 sandbox-default authority display and enforcement", () => {
  test("a fresh production session uses the prompt's canonical sandbox mode", () => {
    expect(DEFAULT_REPL_PERMISSION_MODE).toBe("regular");
    expect(REPL_PERMISSION_CYCLE[0]).toBe("regular");
    expect(statusBarText("regular", false)).toContain("sandbox");
    expect(statusBarText("regular", false)).not.toContain("regular mode");
  });

  test("bypass remains explicit and cycling an unknown state fails closed to sandbox", () => {
    expect(REPL_PERMISSION_CYCLE).toContain("bypass");
    expect(cycleReplPermissionMode("swarm-worker" as never)).toBe("regular");
    expect(statusBarText("bypass", false)).toContain("bypass permissions on");
  });

  test("sandbox permits only permission-allowed read-only tools", () => {
    expect(authorizeReplTool("regular", readTool, {}, "allow")).toBe(true);
    expect(authorizeReplTool("regular", writeTool, {}, "allow")).toBe(false);
    expect(authorizeReplTool("regular", readTool, {}, "ask")).toBe(false);
  });

  test("explicit bypass permits ask and mutation but never overrides hard deny", () => {
    expect(authorizeReplTool("bypass", writeTool, {}, "allow")).toBe(true);
    expect(authorizeReplTool("bypass", writeTool, {}, "ask")).toBe(true);
    expect(authorizeReplTool("bypass", readTool, {}, "deny")).toBe(false);
  });

  test("plan posture is fail-closed like the regular sandbox", () => {
    expect(authorizeReplTool("plan", readTool, {}, "allow")).toBe(true);
    expect(authorizeReplTool("plan", writeTool, {}, "allow")).toBe(false);
  });
});
