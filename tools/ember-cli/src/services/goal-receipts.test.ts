// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// goal-receipts.test.ts — JSONL receipt writer tests for the goal organ
// (ember issue #211). Mirrors operator-receipts.test.ts's conventions.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  compactUtcStamp,
  createGoalReceiptWriter,
  defaultRepoRoot,
  receiptGoalTransition,
} from "./goal-receipts.ts";
import type { GoalTransitionEvent, GoalRecord } from "../core/goal-store.ts";

let scratchDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-goal-receipts-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
});

function fakeGoal(overrides: Partial<GoalRecord> = {}): GoalRecord {
  return {
    goalId: "g1",
    objective: "reach the summit",
    status: "Active",
    usage: { tokensUsed: 0, elapsedMs: 0 },
    createdAt: "2026-07-06T00:00:00.000Z",
    updatedAt: "2026-07-06T00:00:00.000Z",
    consecutiveBlockedTurns: 0,
    ...overrides,
  };
}

describe("compactUtcStamp", () => {
  test("strips dashes, colons, and milliseconds from an ISO timestamp", () => {
    const d = new Date("2026-07-06T05:05:25.000Z");
    expect(compactUtcStamp(d)).toBe("20260706T050525Z");
  });
});

describe("defaultRepoRoot", () => {
  test("resolves to a directory containing GOAL.md (the real repo root)", () => {
    const root = defaultRepoRoot();
    expect(fs.existsSync(path.join(root, "GOAL.md"))).toBe(true);
  });
});

describe("createGoalReceiptWriter", () => {
  test("creates receipts/goal-sessions/session-<UTC>[-<sessionId>].jsonl under the given root", () => {
    const bootTime = new Date("2026-07-06T05:05:25.000Z");
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir, bootTime, sessionId: "s1" });

    expect(writer.filePath).toBe(
      path.join(scratchDir, "receipts", "goal-sessions", "session-20260706T050525Z-s1.jsonl"),
    );
    expect(fs.existsSync(path.dirname(writer.filePath))).toBe(true);
  });

  test("omits the session suffix when no sessionId is given", () => {
    const bootTime = new Date("2026-07-06T05:05:25.000Z");
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir, bootTime });
    expect(writer.filePath).toBe(
      path.join(scratchDir, "receipts", "goal-sessions", "session-20260706T050525Z.jsonl"),
    );
  });

  test("append() writes one JSON row per line, in order", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });

    writer.append("created", "g1", { objective: "reach the summit" });
    writer.append("continuation_fired", "g1");
    writer.append("status_changed", "g1", { from: "Active", to: "Paused" });

    const lines = fs.readFileSync(writer.filePath, "utf8").trim().split("\n");
    expect(lines.length).toBe(3);

    const rows = lines.map((l) => JSON.parse(l));
    expect(rows[0].event).toBe("created");
    expect(rows[0].goalId).toBe("g1");
    expect(rows[0].detail.objective).toBe("reach the summit");
    expect(typeof rows[0].ts).toBe("string");
    expect(rows[1].event).toBe("continuation_fired");
    expect(rows[2].detail).toEqual({ from: "Active", to: "Paused" });
  });

  test("fails open: append() never throws even when the target directory cannot be created", () => {
    const blockerPath = path.join(scratchDir, "receipts");
    fs.writeFileSync(blockerPath, "not a directory");

    expect(() => {
      const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
      writer.append("created", "g1");
      writer.append("continuation_fired", "g1");
    }).not.toThrow();
  });
});

describe("receiptGoalTransition — maps every GoalTransitionEvent kind to a receipted row", () => {
  test("created", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
    const event: GoalTransitionEvent = { kind: "created", goal: fakeGoal() };
    receiptGoalTransition(writer, event);
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8").trim());
    expect(row.event).toBe("created");
    expect(row.goalId).toBe("g1");
    expect(row.detail.objective).toBe("reach the summit");
  });

  test("status_changed carries from/to/reason", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
    const event: GoalTransitionEvent = {
      kind: "status_changed",
      goal: fakeGoal({ status: "Blocked" }),
      from: "Active",
      to: "Blocked",
      reason: "same blocker x3",
    };
    receiptGoalTransition(writer, event);
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8").trim());
    expect(row.detail).toEqual({ from: "Active", to: "Blocked", reason: "same blocker x3" });
  });

  test("status_changed carries completion-audit evidence for Complete", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
    const audit = { requirements: [{ id: "objective", evidence: "receipt:objective-proven" }] };
    const event: GoalTransitionEvent = {
      kind: "status_changed",
      goal: fakeGoal({ status: "Complete", completionAudit: audit }),
      from: "Active",
      to: "Complete",
      completionAudit: audit,
    };
    receiptGoalTransition(writer, event);
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8").trim());
    expect(row.detail.completionAudit).toEqual(audit);
  });

  test("objective_edited carries previousObjective + new objective", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
    const event: GoalTransitionEvent = {
      kind: "objective_edited",
      goal: fakeGoal({ objective: "revised" }),
      previousObjective: "original",
    };
    receiptGoalTransition(writer, event);
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8").trim());
    expect(row.detail.previousObjective).toBe("original");
    expect(row.detail.objective).toBe("revised");
  });

  test("usage_recorded carries the usage tally", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
    const event: GoalTransitionEvent = {
      kind: "usage_recorded",
      goal: fakeGoal({ usage: { tokensUsed: 500, elapsedMs: 100 } }),
    };
    receiptGoalTransition(writer, event);
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8").trim());
    expect(row.detail.usage).toEqual({ tokensUsed: 500, elapsedMs: 100 });
  });

  test("cleared carries only the goalId (no goal record survives to describe)", () => {
    const writer = createGoalReceiptWriter({ repoRoot: scratchDir });
    const event: GoalTransitionEvent = { kind: "cleared", goalId: "g1" };
    receiptGoalTransition(writer, event);
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8").trim());
    expect(row.event).toBe("cleared");
    expect(row.goalId).toBe("g1");
  });
});
