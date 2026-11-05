// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { initialResumeTranscript } from "./repl.ts";

describe("initialResumeTranscript (#2373)", () => {
  it("is empty when the launch did not ask to resume", () => {
    expect(initialResumeTranscript(undefined)).toEqual([]);
  });

  it("draws the restored conversation, then the resume notices", () => {
    const rows = initialResumeTranscript({
      sessionId: "abc",
      messages: [
        { role: "user", content: [{ type: "text", text: "remember PLUM" }] },
        { role: "assistant", content: [{ type: "text", text: "noted" }] },
      ],
      notices: ["Resumed session abc (2 messages).", "Skipped 1 unreadable line in session abc (line 3)."],
    });
    expect(rows.map((r) => r.type)).toEqual(["user", "assistant", "assistant", "assistant"]);
    expect(rows[0]!["content"]).toBe("remember PLUM");
    expect(rows[2]!["content"]).toContain("Resumed session abc");
    expect(rows[3]!["content"]).toContain("Skipped 1 unreadable line");
    expect(new Set(rows.map((r) => r.id)).size).toBe(4);
  });

  it("a failed resume still shows why, with no history", () => {
    const rows = initialResumeTranscript({ sessionId: null, messages: [], notices: ["No earlier session in this directory to continue; starting a new one."] });
    expect(rows.length).toBe(1);
    expect(rows[0]!["content"]).toContain("starting a new one");
  });
});
