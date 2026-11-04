// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2381 wave-2 agents/skills blind-test fixes: T10 TodoWrite, T11 CR in tool output, T12 Esc during
// a subagent, malformed SKILL.md.
import { describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { TodoWriteTool } from "./todo-write.ts";
import { createSessionAppState } from "../core/session-app-state.ts";
import { formatToolResultForDisplay } from "../components/tool-result-renderers.ts";
import { toolDisplayName } from "../components/message-renderers.ts";
import { applyInterrupt } from "../screens/interrupt-transcript.ts";
import { parseSkillMd } from "../skill-framework.ts";
import { discoverSkills } from "./skill-registration.ts";

const todos1 = [
  { content: "write code", activeForm: "writing code", status: "in_progress" as const },
  { content: "test it", activeForm: "testing it", status: "pending" as const },
];

describe("T10 TodoWrite", () => {
  it("keeps todo state between calls and renders a checklist", async () => {
    const st = createSessionAppState("/x");
    const ctx = { getAppState: st.get, setAppState: async (u: (p: unknown) => unknown) => st.set(u) } as never;
    const r1 = (await TodoWriteTool.call(
      { todos: todos1 } as never, ctx, undefined as never, undefined as never,
    )) as { data: { oldTodos: unknown[] } };
    expect(r1.data.oldTodos).toEqual([]);
    const done = todos1.map((t) => ({ ...t, status: "completed" as const }));
    const r2 = (await TodoWriteTool.call({ todos: done } as never, ctx, undefined as never, undefined as never)) as {
      data: Record<string, unknown>;
    };
    expect(r2.data["oldTodos"]).toEqual(todos1);
    const shown = formatToolResultForDisplay(JSON.stringify(r2.data));
    expect(shown).toBe("☑ write code\n☑ test it");
  });
  it("shows in-progress and pending items and the proper tool name", () => {
    const shown = formatToolResultForDisplay(JSON.stringify({ oldTodos: [], newTodos: todos1, todos: todos1 }));
    expect(shown).toBe("◐ writing code (in progress)\n☐ test it");
    expect(toolDisplayName("todowrite")).toBe("TodoWrite");
    expect(toolDisplayName("Bash")).toBe("Bash");
  });
});

describe("T11 carriage returns", () => {
  it("never lets a \r reach the terminal", () => {
    const out = JSON.stringify({ type: "text", content: "     1\tlinesONE\r\n     2\tmber-TWO\r", totalLines: 2 });
    expect(formatToolResultForDisplay(out)).not.toContain("\r");
    expect(formatToolResultForDisplay("a\r\nb\rc")).toBe("a\nb\nc");
  });
});

describe("T12 interrupt ordering", () => {
  it("puts the notice after tool output and marks the running Agent call interrupted", () => {
    const prev = [
      { id: "u", type: "user", content: "go" },
      { id: "a1", type: "assistant", content: "" },
      { id: "t1", type: "tool_call", toolName: "Agent", status: "running" },
      { id: "r1", type: "tool_result", content: "sub result" },
    ];
    const out = applyInterrupt(prev, "a1");
    expect(out[out.length - 1]!["content"]).toBe("__user_abort__");
    expect(out.findIndex((m) => m["content"] === "__user_abort__")).toBe(out.length - 1);
    expect(out.find((m) => m.id === "t1")!["status"]).toBe("interrupted");
    expect(out.filter((m) => m["content"] === "__user_abort__").length).toBe(1);
  });
  it("still annotates a plain interrupted reply in place", () => {
    const out = applyInterrupt([{ id: "u", type: "user" }, { id: "a1", type: "assistant", content: "par" }], "a1");
    expect(out[1]!["content"]).toBe("par\n\n(interrupted)");
  });
});

describe("malformed SKILL.md", () => {
  it("reports an unclosed block and keeps its lines out of the body", () => {
    const r = parseSkillMd("---\nname: x\ndescription: y\n\nDo the thing.\n");
    expect(r.error).toContain("could not be parsed");
    expect(r.body).toBe("Do the thing.\n");
    expect(r.body).not.toContain("name: x");
  });
  it("reports a non key:value line and a missing block; valid stays clean", () => {
    expect(parseSkillMd("---\nname x\n---\nbody").error).toContain("line 2");
    expect(parseSkillMd("---\nname x\n---\nbody").body).toBe("body");
    expect(parseSkillMd("just text").error).toContain("no frontmatter");
    expect(parseSkillMd("---\r\nname: a\r\n---\r\nbody").error).toBeUndefined();
  });
  it("discoverSkills still returns it, with a warning", () => {
    const home = mkdtempSync(join(tmpdir(), "sk-"));
    mkdirSync(join(home, ".ember", "skills", "badfm"), { recursive: true });
    writeFileSync(join(home, ".ember", "skills", "badfm", "SKILL.md"), "---\nname: badfm\nBody here\n");
    const s = discoverSkills(home).find((x) => x.name === "badfm")!;
    expect(s.warning).toBe("skill badfm: frontmatter could not be parsed (the opening --- has no closing ---)");
    expect(s.content).toBe("Body here\n");
  });
});
