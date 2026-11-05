// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compaction.carryforward.test.ts — summaries of summaries must keep file work.

import { describe, it, expect } from "bun:test";
import { createAutocompact } from "./compaction.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

const text = (role: string, t: string): unknown => ({ role, content: [{ type: "text", text: t }] });
const call = (id: string, name: string, input: Record<string, unknown>): unknown => ({
  role: "assistant",
  content: [{ type: "tool_use", id, name, input }],
});
const result = (id: string, isError = false): unknown => ({
  role: "user",
  content: [{ type: "tool_result", tool_use_id: id, content: "x", ...(isError ? { is_error: true } : {}) }],
});
const reply = (t: string): ModelResponse => ({ role: "assistant", content: [{ type: "text", text: t }], stop_reason: "end_turn" });
const allText = (m: unknown): string => JSON.stringify((m as { content: unknown }).content);

function run(model: (p: CallModelParams) => string, store: { messages: unknown[] }) {
  const requests: CallModelParams[] = [];
  const compact = createAutocompact({
    callModel: async (p) => {
      requests.push(p);
      return reply(model(p));
    },
    getMessages: () => store.messages,
    setMessages: (m) => {
      store.messages = m;
    },
  });
  return { compact, requests };
}

describe("compaction carries file work and prior summaries forward", () => {
  it("round two keeps a file the model's own summary omitted", async () => {
    const store = {
      messages: [
        text("user", "make a readme"),
        call("w1", "Write", { file_path: "README.md", content: "hi" }),
        result("w1"),
        call("w2", "Write", { file_path: "todo.md", content: "t" }),
        result("w2"),
        call("w3", "Write", { file_path: "bad.md", content: "t" }),
        result("w3", true),
        text("assistant", "done"),
      ] as unknown[],
    };
    let n = 0;
    const { compact, requests } = run(() => (++n === 1 ? "Created README.md and todo.md." : "Worked on tests."), store);
    expect((await compact({ force: true })).status).toBe("compacted");
    store.messages.push(
      text("user", "now edit"),
      call("e1", "Edit", { file_path: "src/a.ts" }),
      result("e1"),
      call("n1", "NotebookEdit", { notebook_path: "nb.ipynb" }),
      result("n1"),
      text("assistant", "ok"),
    );
    expect((await compact({ force: true })).status).toBe("compacted");
    const final = allText(store.messages[0]);
    for (const f of ["README.md", "todo.md", "src/a.ts", "nb.ipynb"]) expect(final).toContain(f);
    expect(final).not.toContain("bad.md");
    expect(final.match(/README\.md/g)!.length).toBe(1);
    // second request asks to carry the previous summary forward; first does not
    const lastReq = JSON.stringify(requests[1]!.messages.at(-1));
    expect(lastReq).toContain("previous summary");
    expect(JSON.stringify(requests[0]!.messages.at(-1))).not.toContain("previous summary");
  });
});
