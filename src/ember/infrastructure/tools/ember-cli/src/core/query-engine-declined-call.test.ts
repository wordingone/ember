// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine-declined-call.test.ts -- #2380 S32 and S24 at the engine seam.
//
// S32: after the user declined a destructive command, the model proposed it again in the next
//      turn. The decline reaches the model as a tool result in the conversation history, which
//      the engine keeps across turns; what was missing was the exact call in that result.
// S24: the engine announces each executed tool call so the screen can name it.

import { afterEach, describe, expect, it } from "bun:test";
import { declinedToolCallMessage, QueryEngine } from "./query-engine.ts";
import { onToolProgress, type ToolProgressEvent } from "./tool-progress.ts";
import { buildTool, type Tool } from "./tool-interface.ts";
import type { CallModelParams, LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";

const unsubscribe: Array<() => void> = [];
afterEach(() => { for (const off of unsubscribe.splice(0)) off(); });

function shellLikeTool(onCall: (toolUseId: string | undefined) => void): Tool<any, any> {
  return buildTool<{ command: string }, string>({
    name: "Bash",
    description: () => "test shell",
    inputJSONSchema: { type: "object" },
    checkPermissions: async (input) => ({ behavior: "ask", updatedInput: input }),
    call: async (_input, ctx) => {
      onCall(ctx.toolUseId);
      return { data: "ran" };
    },
    mapToolResultToToolResultBlockParam: (data, id) => ({ type: "tool_result", tool_use_id: id, content: data }),
  });
}

function toolUse(id: string, command: string): ModelResponse {
  return { role: "assistant", content: [{ type: "tool_use", id, name: "Bash", input: { command } }], stop_reason: "tool_use" };
}
function text(t: string): ModelResponse {
  return { role: "assistant", content: [{ type: "text", text: t }], stop_reason: "end_turn" };
}
async function drain(engine: QueryEngine, prompt: string): Promise<void> {
  for await (const _ev of engine.submitMessage(prompt)) {
    // drain
  }
}

describe("declined tool calls (#2380 S32)", () => {
  it("names the exact call, says not to propose it again, and keeps the prefix the screen matches", () => {
    const msg = declinedToolCallMessage("Bash", { command: "rd /s /q decoy4" });
    expect(msg.startsWith("Tool call not approved: Bash(rd /s /q decoy4).")).toBe(true);
    expect(msg).toContain("do not propose it again");
    expect(declinedToolCallMessage("Bash", { command: "a\nb" })).toContain("Bash(a b)");
    expect(declinedToolCallMessage("Mystery", {})).toStartWith("Tool call not approved: Mystery.");
    expect(declinedToolCallMessage("Bash", { command: "x".repeat(500) }).length).toBeLessThan(700);
  });

  it("the NEXT turn's model call still carries the decline, with the command in it", async () => {
    const sent: CallModelParams[] = [];
    let turn = 0;
    const deps: LoopDepsOverrides = {
      callModel: async (p) => {
        sent.push(p);
        turn += 1;
        if (turn === 1) return toolUse("t1", "rd /s /q decoy4");
        return text("ok");
      },
      generateUuid: () => "u",
    };
    let executed = 0;
    const tool = shellLikeTool(() => { executed += 1; });
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, tools: [tool], canUseTool: async () => false },
      deps,
    );
    await drain(engine, "delete decoy4");
    await drain(engine, "now just echo harmless-b");

    expect(executed).toBe(0);
    const lastCall = sent[sent.length - 1]!;
    const history = JSON.stringify(lastCall.messages);
    expect(history).toContain("Tool call not approved: Bash(rd /s /q decoy4)");
    expect(history).toContain("do not propose it again");
    // and it is the user's later request, not the declined command, that ends the history
    expect(JSON.stringify((lastCall.messages as unknown[])[(lastCall.messages as unknown[]).length - 1])).toContain("harmless-b");
  });
});

describe("tool progress seam (#2380 S24)", () => {
  it("announces a call that runs (start, then end) and hands the tool its own call id", async () => {
    const events: ToolProgressEvent[] = [];
    unsubscribe.push(onToolProgress((e) => events.push(e)));
    let seenId: string | undefined;
    let n = 0;
    const deps: LoopDepsOverrides = {
      callModel: async () => (n++ === 0 ? toolUse("call-77", "sleep 1") : text("done")),
      generateUuid: () => "u",
    };
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, tools: [shellLikeTool((id) => { seenId = id; })], canUseTool: async () => true },
      deps,
    );
    await drain(engine, "go");
    expect(seenId).toBe("call-77");
    expect(events.map((e) => e.kind)).toEqual(["start", "end"]);
    const start = events[0] as Extract<ToolProgressEvent, { kind: "start" }>;
    expect(start.toolName).toBe("Bash");
    expect(start.input).toEqual({ command: "sleep 1" });
    expect(start.toolUseId).toBe("call-77");
  });

  it("announces nothing for a call that was declined: no tool ran", async () => {
    const events: ToolProgressEvent[] = [];
    unsubscribe.push(onToolProgress((e) => events.push(e)));
    let n = 0;
    const deps: LoopDepsOverrides = {
      callModel: async () => (n++ === 0 ? toolUse("call-9", "rm -rf x") : text("ok")),
      generateUuid: () => "u",
    };
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, tools: [shellLikeTool(() => {})], canUseTool: async () => false },
      deps,
    );
    await drain(engine, "go");
    expect(events).toEqual([]);
  });
});
