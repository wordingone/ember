// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { approvalKeyDecision, describeToolCallForApproval } from "./repl.ts";

describe("interactive tool approval", () => {
  it("maps y / Enter / a / n / Esc and ignores other keys", () => {
    expect(approvalKeyDecision("y", {})).toBe("yes");
    expect(approvalKeyDecision("Y", {})).toBe("yes");
    expect(approvalKeyDecision("", { return: true })).toBe("yes");
    expect(approvalKeyDecision("a", {})).toBe("always");
    expect(approvalKeyDecision("n", {})).toBe("no");
    expect(approvalKeyDecision("", { escape: true })).toBe("no");
    expect(approvalKeyDecision("x", {})).toBeNull();
  });

  it("summarises the call by its meaningful fields, bounded", () => {
    expect(describeToolCallForApproval("Write", { file_path: "a.txt", content: "secret body" })).toBe("Write: file_path=a.txt");
    expect(describeToolCallForApproval("Bash", { command: "echo  hi\nthere" })).toBe("Bash: command=echo hi there");
    expect(describeToolCallForApproval("X", { command: "z".repeat(500) }).length).toBeLessThanOrEqual(183);
  });
});

describe("prompt history", () => {
  it("walks back through submissions and returns to the draft", async () => {
    const { historyStep } = await import("./repl.ts");
    const h = ["one", "two"];
    let s = historyStep(h, null, -1, "draft");
    expect(s).toEqual({ index: 1, text: "two" });
    s = historyStep(h, s.index, -1, "draft");
    expect(s).toEqual({ index: 0, text: "one" });
    expect(historyStep(h, 0, -1, "draft")).toEqual({ index: 0, text: "one" });
    s = historyStep(h, 0, 1, "draft");
    expect(s).toEqual({ index: 1, text: "two" });
    expect(historyStep(h, 1, 1, "draft")).toEqual({ index: null, text: "draft" });
    expect(historyStep([], null, -1, "d")).toEqual({ index: null, text: null });
  });
});
