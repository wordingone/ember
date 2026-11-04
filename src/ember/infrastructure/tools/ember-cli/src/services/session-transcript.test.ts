// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-transcript.test.ts -- a resumed session redraws its past transcript (#2373).

import { describe, expect, it } from "bun:test";
import { engineMessagesToTranscript } from "./session-transcript.ts";

let n = 0;
const id = () => `row-${++n}`;

describe("engineMessagesToTranscript", () => {
  it("rebuilds user, assistant, tool call and tool result rows in order", () => {
    const rows = engineMessagesToTranscript(
      [
        { role: "user", content: [{ type: "text", text: "read the readme" }] },
        {
          role: "assistant",
          content: [
            { type: "text", text: "Reading it." },
            { type: "tool_use", id: "t1", name: "Read", input: { file_path: "README.md" } },
            { type: "tool_use", id: "t2", name: "Bash", input: { command: "false" } },
          ],
        },
        {
          role: "user",
          content: [
            { type: "tool_result", tool_use_id: "t1", content: "# Title" },
            { type: "tool_result", tool_use_id: "t2", content: "exit 1", is_error: true },
          ],
        },
        { role: "assistant", content: [{ type: "text", text: "Done." }] },
      ],
      id,
    );
    expect(rows.map((r) => r.type)).toEqual([
      "user", "assistant", "tool_call", "tool_call", "tool_result", "tool_result", "assistant",
    ]);
    expect(rows[0]!["content"]).toBe("read the readme");
    expect(rows[2]).toMatchObject({ toolUseId: "t1", toolName: "Read", status: "done" });
    expect(rows[3]).toMatchObject({ toolUseId: "t2", toolName: "Bash", status: "error" });
    expect(rows[4]).toMatchObject({ tool_use_id: "t1", content: "# Title", is_error: false });
    expect(rows[5]).toMatchObject({ tool_use_id: "t2", is_error: true });
    expect(new Set(rows.map((r) => r.id)).size).toBe(rows.length);
  });

  it("shows a compaction summary as an earlier-conversation row, not as something the user typed", () => {
    const rows = engineMessagesToTranscript(
      [{ role: "user", content: [{ type: "text", text: "[compacted conversation summary]\nThe build token is PLUM-42." }] }],
      id,
    );
    expect(rows.length).toBe(1);
    expect(rows[0]!.type).toBe("assistant");
    expect(String(rows[0]!["content"])).toContain("PLUM-42");
    expect(String(rows[0]!["content"])).toContain("summarized");
  });

  it("skips malformed entries and empty text", () => {
    const rows = engineMessagesToTranscript(
      [null, "x", { role: "assistant", content: [{ type: "text", text: "  " }] }, { role: "user", content: "plain string prompt" }],
      id,
    );
    expect(rows.map((r) => r.type)).toEqual(["user"]);
    expect(rows[0]!["content"]).toBe("plain string prompt");
  });
});
