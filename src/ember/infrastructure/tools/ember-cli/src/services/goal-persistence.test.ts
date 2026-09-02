// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// goal-persistence.test.ts — file-backed GoalStorePersistence tests.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createFileGoalPersistence, goalStateFilePath } from "./goal-persistence.ts";
import { emberStatePath } from "../utils/ember-state-root.ts";
import type { GoalRecord } from "../core/goal-store.ts";

let scratchDir: string;
let stateDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-goal-persistence-"));
  // Pin the external state root, for two reasons: the default resolves under the real
  // user config home (which would outlive this suite), and the root must sit OUTSIDE the
  // repo root it serves or the writer-side guard refuses it.
  stateDir = `${scratchDir}-cockpit-state`;
  process.env["EMBER_STATE_ROOT"] = stateDir;
});

afterEach(() => {
  delete process.env["EMBER_STATE_ROOT"];
  fs.rmSync(scratchDir, { recursive: true, force: true });
  fs.rmSync(stateDir, { recursive: true, force: true });
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

describe("goalStateFilePath", () => {
  test("resolves to goals/<sessionId>.json under the EXTERNAL state root", () => {
    // Never under the repo root itself: the completion verifier censuses that tree by
    // totality, so a goal file written during a run would red the certificate (#1330).
    expect(goalStateFilePath("/repo", "sess-1")).toBe(
      emberStatePath("/repo", "goals", "sess-1.json"),
    );
    expect(goalStateFilePath("/repo", "sess-1").startsWith(path.resolve("/repo") + path.sep))
      .toBe(false);
  });
});

describe("createFileGoalPersistence", () => {
  test("read() returns null when no file exists yet", () => {
    const persistence = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "s1" });
    expect(persistence.read()).toBeNull();
  });

  test("write() then read() round-trips the record exactly", () => {
    const persistence = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "s1" });
    const goal = fakeGoal();
    persistence.write(goal);
    expect(persistence.read()).toEqual(goal);
  });

  test("write(null) deletes the file — read() then returns null", () => {
    const persistence = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "s1" });
    persistence.write(fakeGoal());
    persistence.write(null);
    expect(persistence.read()).toBeNull();
    expect(fs.existsSync(goalStateFilePath(scratchDir, "s1"))).toBe(false);
  });

  test("write(null) on an already-absent file is a safe no-op", () => {
    const persistence = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "s1" });
    expect(() => persistence.write(null)).not.toThrow();
  });

  test("different sessionIds are isolated from each other", () => {
    const a = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "session-a" });
    const b = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "session-b" });
    a.write(fakeGoal({ objective: "goal for a" }));
    expect(b.read()).toBeNull();
    expect(a.read()?.objective).toBe("goal for a");
  });

  test("a corrupt (non-JSON) file reads as null rather than throwing", () => {
    const persistence = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "s1" });
    const filePath = goalStateFilePath(scratchDir, "s1");
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, "{not valid json");
    expect(persistence.read()).toBeNull();
  });

  test("write() never throws even when the directory cannot be created", () => {
    const blockerPath = path.dirname(goalStateFilePath(scratchDir, "s1"));
    fs.mkdirSync(path.dirname(blockerPath), { recursive: true });
    fs.writeFileSync(blockerPath, "not a directory");
    const persistence = createFileGoalPersistence({ repoRoot: scratchDir, sessionId: "s1" });
    expect(() => persistence.write(fakeGoal())).not.toThrow();
  });
});
