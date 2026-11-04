// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// The engine must carry tool-produced images beside (not inside) the text
// content, so truncation never mangles base64 and eviction can drop them.
import { describe, expect, test } from "bun:test";
import { query, type QueryEvent } from "./query-engine.ts";
import { buildTool, type ToolUseContext } from "./tool-interface.ts";
import type { LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";

const BIG = "A".repeat(200_000);

describe("tool result images through the query engine", () => {
  test("a 200KB base64 image is not truncated and not stringified into content", async () => {
    const tool = buildTool<Record<string, never>, string>({
      name: "shot",
      description: () => "x",
      inputJSONSchema: { type: "object" },
      call: async () => ({ data: "ok" }),
      mapToolResultToToolResultBlockParam: (_d, id) => ({
        type: "tool_result",
        tool_use_id: id,
        content: [
          { type: "text", text: "caption" },
          { type: "image", source: { type: "base64", media_type: "image/png", data: BIG } },
        ],
      }),
    });
    const ctx: ToolUseContext = {
      options: { tools: [tool as never], mainLoopModel: "t" },
      abortController: new AbortController(),
      cwd: "C:\\x",
      getAppState: () => ({}),
      setAppState: () => {},
      messages: [],
    };
    const use: ModelResponse = { role: "assistant", content: [{ type: "tool_use", id: "t1", name: "shot", input: {} }], stop_reason: "tool_use" };
    const done: ModelResponse = { role: "assistant", content: [{ type: "text", text: "done" }], stop_reason: "end_turn" };
    let n = 0;
    const deps: LoopDepsOverrides = { callModel: async () => (n++ === 0 ? use : done), generateUuid: () => "u" + n };
    const events: QueryEvent[] = [];
    for await (const e of query({ messages: [{ role: "user", content: [{ type: "text", text: "go" }] }], systemPrompt: "s", toolUseContext: ctx }, deps)) events.push(e);
    const block = events
      .filter((e) => e.type === "user")
      .flatMap((e) => e.message.content)
      .find((b) => (b as { tool_use_id?: string }).tool_use_id === "t1") as {
      content: string;
      images?: Array<{ media_type: string; data: string }>;
    };
    expect(block.content).toBe("caption");
    expect(block.images).toHaveLength(1);
    expect(block.images![0]!.data).toBe(BIG);
  });
});
