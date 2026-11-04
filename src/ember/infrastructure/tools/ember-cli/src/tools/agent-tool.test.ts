// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { QueryEngine } from "../core/query-engine.ts";
import type { QueryEvent } from "../core/query-engine.ts";
import type { Tool, ToolUseContext } from "../core/tool-interface.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";
import { BUILTIN_TOOLS } from "./builtin-tools.ts";
import { AGENT_MAX_DEPTH, AgentTool, runSubagent, selectSubagentTools, SUBAGENT_TYPES } from "./agent-tool.ts";
import { buildRegisteredSkillTool, discoverSkills } from "./skill-registration.ts";

const text = (t: string): ModelResponse => ({
  role: "assistant",
  content: [{ type: "text", text: t }],
  stop_reason: "end_turn",
});
const toolUse = (id: string, name: string, input: unknown): ModelResponse => ({
  role: "assistant",
  content: [{ type: "tool_use", id, name, input }],
  stop_reason: "tool_use",
});

function ctx(over: Partial<ToolUseContext> = {}): ToolUseContext {
  return {
    options: { tools: BUILTIN_TOOLS as Tool[] },
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: () => {},
    messages: [],
    ...over,
  } as ToolUseContext;
}

async function drain(engine: QueryEngine, prompt: string): Promise<QueryEvent[]> {
  const out: QueryEvent[] = [];
  for await (const e of engine.submitMessage(prompt)) out.push(e);
  return out;
}

const saved = {
  EMBER_AGENT_TIMEOUT_MS: process.env["EMBER_AGENT_TIMEOUT_MS"],
  EMBER_AGENT_MAX_TURNS: process.env["EMBER_AGENT_MAX_TURNS"],
  EMBER_HOME: process.env["EMBER_HOME"],
};
afterEach(() => {
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
});

function engineFor(callModel: (p: CallModelParams) => Promise<ModelResponse>, maxTurns = 6): QueryEngine {
  return new QueryEngine(
    { tools: BUILTIN_TOOLS as Tool[], getAppState: () => ({}), setAppState: () => {}, maxTurns },
    { callModel, sleep: async () => {} },
  );
}

describe("registration", () => {
  test("Agent and Skill are registered with JSON schemas", () => {
    const names = BUILTIN_TOOLS.map((t) => (t as Tool).name);
    expect(names).toContain("Agent");
    expect(names).toContain("Skill");
    const agent = BUILTIN_TOOLS.find((t) => (t as Tool).name === "Agent") as Tool;
    const props = (agent.inputJSONSchema as { properties: Record<string, unknown> }).properties;
    expect(Object.keys(props)).toEqual(["description", "prompt", "subagent_type"]);
    const skill = BUILTIN_TOOLS.find((t) => (t as Tool).name === "Skill") as Tool;
    expect(Object.keys((skill.inputJSONSchema as { properties: Record<string, unknown> }).properties)).toEqual([
      "skill",
      "args",
    ]);
  });
});

describe("tool subset", () => {
  const all = BUILTIN_TOOLS as Tool[];
  test("explore is read-only; general-purpose drops interactive tools", () => {
    const ex = selectSubagentTools(all, SUBAGENT_TYPES["explore"]!, 1).map((t) => t.name).sort();
    expect(ex).toEqual(["Glob", "Grep", "Read"]);
    const gp = selectSubagentTools(all, SUBAGENT_TYPES["general-purpose"]!, 1).map((t) => t.name);
    expect(gp).toContain("Agent");
    expect(gp).toContain("Bash");
    expect(gp).not.toContain("AskUserQuestion");
  });
  test("Agent is withheld at the maximum depth", () => {
    const gp = selectSubagentTools(all, SUBAGENT_TYPES["general-purpose"]!, AGENT_MAX_DEPTH).map((t) => t.name);
    expect(gp).not.toContain("Agent");
  });
});

describe("end-to-end through the query loop with a scripted model", () => {
  test("parent delegates, subagent has own history, final text returns as tool result", async () => {
    const seen: CallModelParams[] = [];
    const callModel = async (p: CallModelParams): Promise<ModelResponse> => {
      seen.push(p);
      if (p.systemPrompt.includes("subagent")) return text("CHILD-ANSWER-42");
      return JSON.stringify(p.messages).includes("CHILD-ANSWER-42")
        ? text("parent done")
        : toolUse("t1", "Agent", { description: "ask", prompt: "compute the answer" });
    };
    const events = await drain(engineFor(callModel, 5), "please delegate");
    const userEv = events.find((e) => e.type === "user") as unknown as {
      message: { toolUseResult: { content: string; is_error?: boolean }[] };
    };
    expect(userEv.message.toolUseResult[0]!.content).toBe("CHILD-ANSWER-42");
    expect(userEv.message.toolUseResult[0]!.is_error).toBeFalsy();
    const childCalls = seen.filter((p) => p.systemPrompt.includes("subagent"));
    expect(childCalls.length).toBe(1);
    expect(JSON.stringify(childCalls[0]!.messages)).toContain("compute the answer");
    expect(JSON.stringify(childCalls[0]!.messages)).not.toContain("please delegate");
    expect(events.at(-1)!.type).toBe("result");
  });

  test("nested delegation: depth 2 agents lose the Agent tool", async () => {
    const toolSets: string[][] = [];
    const callModel = async (p: CallModelParams): Promise<ModelResponse> => {
      toolSets.push(p.tools.map((t) => t.name));
      const sawResult = p.messages.some((m) => (m as { toolUseResult?: unknown }).toolUseResult);
      if (sawResult) return text("done-level");
      return p.tools.some((t) => t.name === "Agent")
        ? toolUse("n" + toolSets.length, "Agent", { description: "d", prompt: "again" })
        : text("leaf");
    };
    const events = await drain(engineFor(callModel, 6), "go");
    expect((events.at(-1) as unknown as { subtype: string }).subtype).toBe("success");
    // main (has Agent) -> depth1 (has Agent) -> depth2 (no Agent) = 3 model calls before results flow back
    expect(toolSets.slice(0, 3).map((s) => s.includes("Agent"))).toEqual([true, true, false]);
  });
});

describe("limits and error paths", () => {
  test("depth limit: depth-2 context cannot spawn", async () => {
    const c = ctx({ agentDepth: AGENT_MAX_DEPTH, loopDeps: { callModel: async () => text("x") } });
    await expect(runSubagent({ description: "d", prompt: "p" }, c)).rejects.toThrow(/depth limit/);
  });
  test("unknown subagent_type is an error", async () => {
    const c = ctx({ loopDeps: { callModel: async () => text("x") } });
    await expect(
      runSubagent({ description: "d", prompt: "p", subagent_type: "nope" }, c),
    ).rejects.toThrow(/Unknown subagent_type/);
  });
  test("missing loop deps is an error, not a crash", async () => {
    await expect(runSubagent({ description: "d", prompt: "p" }, ctx())).rejects.toThrow(/loop deps/);
  });
  test("timeout aborts the model call and reports an error", async () => {
    process.env["EMBER_AGENT_TIMEOUT_MS"] = "100";
    let aborted = false;
    const callModel = (p: CallModelParams): Promise<ModelResponse> =>
      new Promise((_, rej) => {
        p.abortSignal?.addEventListener("abort", () => {
          aborted = true;
          rej(new Error("aborted"));
        });
      });
    const c = ctx({ loopDeps: { callModel } });
    await expect(runSubagent({ description: "d", prompt: "p" }, c)).rejects.toThrow(/timed out after 100ms/);
    await Bun.sleep(20);
    expect(aborted).toBe(true);
  });
  test("turn cap reports an error", async () => {
    process.env["EMBER_AGENT_MAX_TURNS"] = "2";
    let n = 0;
    const callModel = async (): Promise<ModelResponse> =>
      toolUse("u" + n++, "Glob", { pattern: "*.nothing-here" });
    const c = ctx({ loopDeps: { callModel } });
    await expect(runSubagent({ description: "d", prompt: "p" }, c)).rejects.toThrow(/turn cap \(2\)/);
  });
  test("model failure inside subagent is reported, not thrown past the tool", async () => {
    const callModel = async (): Promise<ModelResponse> => {
      throw new Error("server down");
    };
    const c = ctx({ loopDeps: { callModel, sleep: async () => {} } });
    await expect(runSubagent({ description: "d", prompt: "p" }, c)).rejects.toThrow(/Subagent ended with error/);
  });
  test("parent abort propagates", async () => {
    const parent = new AbortController();
    const callModel = (p: CallModelParams): Promise<ModelResponse> =>
      new Promise((_, rej) => p.abortSignal?.addEventListener("abort", () => rej(new Error("aborted"))));
    const c = ctx({ loopDeps: { callModel }, abortController: parent });
    const pr = runSubagent({ description: "d", prompt: "p" }, c);
    setTimeout(() => parent.abort(), 30);
    await expect(pr).rejects.toThrow(/aborted/);
  });
  test("failure through the query loop surfaces as is_error and the parent continues", async () => {
    const callModel = async (p: CallModelParams): Promise<ModelResponse> => {
      if (p.systemPrompt.includes("subagent")) throw new Error("boom");
      return JSON.stringify(p.messages).includes("is_error")
        ? text("handled")
        : toolUse("t1", "Agent", { description: "d", prompt: "p" });
    };
    const events = await drain(engineFor(callModel, 5), "go");
    const u = events.find((e) => e.type === "user") as unknown as {
      message: { toolUseResult: { is_error?: boolean }[] };
    };
    expect(u.message.toolUseResult[0]!.is_error).toBe(true);
    expect((events.at(-1) as unknown as { subtype: string }).subtype).toBe("success");
  });
  test("validateInput rejects bad input", () => {
    expect(AgentTool.validateInput!({ prompt: "x" })).toMatchObject({ result: false });
    expect(AgentTool.validateInput!({ description: "a", prompt: "x" })).toEqual({ result: true });
  });
});

describe("skills", () => {
  function mkSkill(root: string, dir: string, name: string, desc: string, body: string): void {
    const d = join(root, "skills", dir);
    mkdirSync(d, { recursive: true });
    writeFileSync(join(d, "SKILL.md"), `---\nname: ${name}\ndescription: ${desc}\n---\n${body}\n`);
  }
  test("discovery from <cwd>/.ember/skills and EMBER_HOME/skills, project wins", async () => {
    const base = mkdtempSync(join(tmpdir(), "ember-skills-"));
    try {
      const cwd = join(base, "proj");
      const home = join(base, "home");
      mkSkill(join(cwd, ".ember"), "alpha", "alpha", "project alpha", "PROJECT BODY $ARGUMENTS");
      mkSkill(home, "alpha", "alpha", "home alpha", "HOME BODY");
      mkSkill(home, "beta", "beta", "home beta", "BETA BODY dir=${EMBER_SKILL_DIR}");
      process.env["EMBER_HOME"] = home;
      const found = discoverSkills(cwd);
      expect(found.map((s) => s.name).sort()).toEqual(["alpha", "beta"]);
      expect(found.find((s) => s.name === "alpha")!.description).toBe("project alpha");

      const tool = buildRegisteredSkillTool(() => cwd);
      expect(tool.description()).toContain("beta: home beta");
      const res = await tool.call({ skill: "alpha", args: "X1" }, ctx());
      const block = tool.mapToolResultToToolResultBlockParam(res.data, "id");
      expect(String(block.content)).toContain("PROJECT BODY X1");
      const b2 = await tool.call({ skill: "/beta" }, ctx());
      expect(String(tool.mapToolResultToToolResultBlockParam(b2.data, "id").content)).toContain("skills/beta");
      await expect(tool.call({ skill: "nope" }, ctx())).rejects.toThrow(/not found.*alpha, beta/);
    } finally {
      rmSync(base, { recursive: true, force: true });
    }
  });
  test("no skill dirs gives empty list, no crash", () => {
    process.env["EMBER_HOME"] = join(tmpdir(), "ember-no-such-home-xyz");
    expect(discoverSkills(join(tmpdir(), "no-such-cwd-xyz"))).toEqual([]);
  });
});
