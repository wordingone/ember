// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { query, type QueryEvent } from "./query-engine.ts";
import { buildTool, type PermissionBehavior, type Tool, type ToolUseContext } from "./tool-interface.ts";
import type { LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";

type Input = { value: string; normalized?: boolean };

function makeContext(tool: Tool<any, any>): ToolUseContext {
  return {
    options: { tools: [tool], mainLoopModel: "test" },
    abortController: new AbortController(),
    cwd: "C:\\safe",
    getAppState: () => ({}),
    setAppState: () => {},
    messages: [],
  };
}

async function exerciseTool(options: {
  behavior: PermissionBehavior;
  permissionMessage?: string;
  canUseTool: (input: Input) => Promise<boolean>;
}) {
  let callCount = 0;
  let calledInput: Input | undefined;
  let predicateInput: Input | undefined;

  const tool = buildTool<Input, string>({
    name: "mutation",
    description: () => "test mutation",
    inputJSONSchema: { type: "object" },
    checkPermissions: async (input) => ({
      behavior: options.behavior,
      updatedInput: { ...input, normalized: true },
      message: options.permissionMessage,
    }),
    call: async (input) => {
      callCount += 1;
      calledInput = input;
      return { data: "executed" };
    },
    mapToolResultToToolResultBlockParam: (data, id) => ({
      type: "tool_result",
      tool_use_id: id,
      content: data,
    }),
  });

  const toolUse: ModelResponse = {
    role: "assistant",
    content: [{ type: "tool_use", id: "tool-1", name: tool.name, input: { value: "raw" } }],
    stop_reason: "tool_use",
  };
  const done: ModelResponse = {
    role: "assistant",
    content: [{ type: "text", text: "done" }],
    stop_reason: "end_turn",
  };
  let modelCall = 0;
  const deps: LoopDepsOverrides = {
    callModel: async () => (modelCall++ === 0 ? toolUse : done),
    generateUuid: () => `uuid-${modelCall}`,
  };

  const events: QueryEvent[] = [];
  for await (const event of query(
    {
      messages: [{ role: "user", content: [{ type: "text", text: "test" }] }],
      systemPrompt: "test",
      toolUseContext: makeContext(tool),
      canUseTool: async (_tool, input) => {
        predicateInput = input as Input;
        return options.canUseTool(input as Input);
      },
    },
    deps,
  )) {
    events.push(event);
  }

  const result = events
    .filter((event) => event.type === "user")
    .flatMap((event) => event.message.content)
    .find((block) => (block as { tool_use_id?: string }).tool_use_id === "tool-1") as
      | { content: string; is_error?: boolean }
      | undefined;

  return { callCount, calledInput, predicateInput, result };
}

describe("#1215 central tool permission gate", () => {
  test("a tool hard-deny cannot be overridden by a permissive session predicate", async () => {
    const observed = await exerciseTool({
      behavior: "deny",
      permissionMessage: "outside the governed root",
      canUseTool: async () => true,
    });

    expect(observed.callCount).toBe(0);
    expect(observed.predicateInput).toBeUndefined();
    expect(observed.result?.is_error).toBe(true);
    expect(observed.result?.content).toContain("outside the governed root");
  });

  test("a session predicate refusal prevents tool execution after permission normalization", async () => {
    const observed = await exerciseTool({
      behavior: "allow",
      canUseTool: async () => false,
    });

    expect(observed.callCount).toBe(0);
    expect(observed.predicateInput).toEqual({ value: "raw", normalized: true });
    expect(observed.result?.is_error).toBe(true);
    expect(observed.result?.content).toContain("sandbox");
  });

  test("an authorized tool executes with the permission-normalized input", async () => {
    const observed = await exerciseTool({
      behavior: "ask",
      canUseTool: async () => true,
    });

    expect(observed.callCount).toBe(1);
    expect(observed.calledInput).toEqual({ value: "raw", normalized: true });
    expect(observed.result?.content).toBe("executed");
    expect(observed.result?.is_error).toBeUndefined();
  });
});
