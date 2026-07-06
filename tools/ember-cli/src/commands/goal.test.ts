// commands/goal.test.ts — /goal slash command tests (ember issue #211): dispatch
// parsing (/goal <objective> | /goal | /goal clear), status formatting, the
// create-vs-edit branch, ephemeral-session refusal, and the objective-updated
// steering injection (only when the shared idle-gated injector says yes).
//
// NOTE: this file previously tested a bounded ~5-iteration prototype
// (runGoalLoop/deriveLoopPhaseForEvent/setGoalEngineProvider) that commands/goal.ts's
// own header comment says was dead code, never wired into command-registry.ts, and
// has been fully replaced by the persisted-goal-record + event-driven-continuation
// mechanism below. That prototype's exports no longer exist in commands/goal.ts.

import { describe, it, expect, beforeEach } from "bun:test";
import {
  createGoalCommand,
  formatGoalStatus,
  setGoalSteeringInjectorProvider,
  resetGoalSteeringInjectorForTests,
  setGoalContinuationTrigger,
  resetGoalContinuationTriggerForTests,
  type GoalSteeringInjector,
} from "./goal.ts";
import { createGoalStore, createInMemoryGoalPersistence, type GoalStore } from "../core/goal-store.ts";
import type { CommandContext } from "../types/command-types.ts";

const ctx: CommandContext = { sessionId: "s", mode: "default", cwd: "/x" };

function freshStore(): GoalStore {
  return createGoalStore({ persistence: createInMemoryGoalPersistence() });
}

describe("formatGoalStatus", () => {
  it("reports usage text when no goal exists", () => {
    expect(formatGoalStatus(null)).toContain("no active goal");
    expect(formatGoalStatus(null)).toContain("/goal <objective>");
  });

  it("shows objective, status, and usage without a budget", () => {
    const store = freshStore();
    store.createGoal("reach the summit");
    const text = formatGoalStatus(store.getGoal());
    expect(text).toContain("objective: reach the summit");
    expect(text).toContain("status: Active");
    expect(text).toContain("no budget set");
  });

  it("shows usage against the budget when one is set", () => {
    const store = freshStore();
    store.createGoal("reach the summit", { tokenBudget: 5000 });
    store.recordUsage(200);
    const text = formatGoalStatus(store.getGoal());
    expect(text).toContain("200 / 5000 tokens");
  });

  it("shows the consecutive-blocked-turn count only when it is nonzero", () => {
    const store = freshStore();
    store.createGoal("reach the summit");
    expect(formatGoalStatus(store.getGoal())).not.toContain("consecutive same-blocker");
    store.noteBlocked("rate limited");
    expect(formatGoalStatus(store.getGoal())).toContain("consecutive same-blocker turns: 1");
  });
});

describe("createGoalCommand — registry shape", () => {
  it("name/description/isEnabled are set for registry integration", () => {
    const cmd = createGoalCommand({ getStore: freshStore });
    expect(cmd.name).toBe("goal");
    expect(cmd.isEnabled()).toBe(true);
    expect(cmd.description.length).toBeGreaterThan(0);
  });
});

describe("createGoalCommand — /goal (view)", () => {
  it("shows 'no active goal' usage text when empty args and no goal exists", async () => {
    const cmd = createGoalCommand({ getStore: freshStore });
    const result = await cmd.execute("", ctx);
    expect(result?.message).toContain("no active goal");
  });

  it("shows the live status when a goal exists", async () => {
    const store = freshStore();
    store.createGoal("reach the summit");
    const cmd = createGoalCommand({ getStore: () => store });
    const result = await cmd.execute("", ctx);
    expect(result?.message).toContain("reach the summit");
    expect(result?.message).toContain("status: Active");
  });

  it("trims surrounding whitespace before dispatching to the view branch", async () => {
    const cmd = createGoalCommand({ getStore: freshStore });
    const result = await cmd.execute("   ", ctx);
    expect(result?.message).toContain("no active goal");
  });
});

describe("createGoalCommand — /goal clear", () => {
  it("clears an existing goal and reports it", async () => {
    const store = freshStore();
    store.createGoal("reach the summit");
    const cmd = createGoalCommand({ getStore: () => store });
    const result = await cmd.execute("clear", ctx);
    expect(result?.message).toBe("goal cleared.");
    expect(store.getGoal()).toBeNull();
  });

  it("honestly reports there was nothing to clear", async () => {
    const cmd = createGoalCommand({ getStore: freshStore });
    const result = await cmd.execute("clear", ctx);
    expect(result?.message).toBe("no active goal to clear.");
  });
});

describe("createGoalCommand — /goal <objective> (create)", () => {
  it("creates a new goal when none exists and reports it set + Active", async () => {
    const store = freshStore();
    const cmd = createGoalCommand({ getStore: () => store });
    const result = await cmd.execute("reach the summit", ctx);
    expect(result?.message).toContain("goal set: reach the summit");
    expect(result?.message).toContain("status: Active");
    expect(store.getGoal()?.objective).toBe("reach the summit");
  });

  it("honestly reports a refusal on an ephemeral session, without creating a record", async () => {
    const store = freshStore();
    const cmd = createGoalCommand({ getStore: () => store, isEphemeralSession: () => true });
    const result = await cmd.execute("reach the summit", ctx);
    expect(result?.message).toContain("goal not set");
    expect(result?.message).toContain("ephemeral");
    expect(store.getGoal()).toBeNull();
  });

  it("pokes the continuation trigger once, fire-and-forget, on a successful create", async () => {
    const store = freshStore();
    let pokes = 0;
    const cmd = createGoalCommand({ getStore: () => store, triggerContinuationCheck: () => { pokes += 1; } });
    await cmd.execute("reach the summit", ctx);
    expect(pokes).toBe(1);
  });

  it("does NOT poke the continuation trigger when creation fails (ephemeral session)", async () => {
    const store = freshStore();
    let pokes = 0;
    const cmd = createGoalCommand({
      getStore: () => store,
      isEphemeralSession: () => true,
      triggerContinuationCheck: () => { pokes += 1; },
    });
    await cmd.execute("reach the summit", ctx);
    expect(pokes).toBe(0);
  });

  it("uses the module-level provider set by setGoalContinuationTrigger when no dep override is given", async () => {
    resetGoalContinuationTriggerForTests();
    let pokes = 0;
    setGoalContinuationTrigger(() => { pokes += 1; });
    const store = freshStore();
    const cmd = createGoalCommand({ getStore: () => store });
    await cmd.execute("reach the summit", ctx);
    expect(pokes).toBe(1);
    resetGoalContinuationTriggerForTests();
  });
});

describe("createGoalCommand — /goal <objective> (mid-task edit)", () => {
  beforeEach(() => {
    resetGoalSteeringInjectorForTests();
  });

  it("edits the existing objective rather than creating a second goal", async () => {
    const store = freshStore();
    store.createGoal("original objective");
    const cmd = createGoalCommand({ getStore: () => store });
    const result = await cmd.execute("revised objective", ctx);
    expect(result?.message).toContain("objective updated: revised objective");
    expect(store.getGoal()?.objective).toBe("revised objective");
  });

  it("rejects an invalid edit (empty) and leaves the objective untouched", async () => {
    const store = freshStore();
    store.createGoal("original objective");
    const cmd = createGoalCommand({ getStore: () => store });
    const result = await cmd.execute("   ", ctx);
    // Empty-after-trim args route to the VIEW branch, not an edit -- confirm
    // it shows status rather than attempting (and failing) an empty edit.
    expect(result?.message).toContain("original objective");
    expect(store.getGoal()?.objective).toBe("original objective");
  });

  it("injects the objective-updated steering prompt immediately when the injector says canInjectNow", async () => {
    const store = freshStore();
    store.createGoal("original objective");
    let injected = "";
    const injector: GoalSteeringInjector = {
      canInjectNow: () => true,
      inject: (prompt: string) => { injected = prompt; },
    };
    const cmd = createGoalCommand({ getStore: () => store, getSteeringInjector: () => injector });
    const result = await cmd.execute("revised objective", ctx);
    expect(injected).toContain("revised objective");
    expect(injected).toContain("GOAL OBJECTIVE UPDATED");
    expect(result?.message).toContain("steering message injected");
  });

  it("does NOT inject and says so when the injector reports it cannot inject now", async () => {
    const store = freshStore();
    store.createGoal("original objective");
    let injectCalls = 0;
    const injector: GoalSteeringInjector = {
      canInjectNow: () => false,
      inject: () => { injectCalls += 1; },
    };
    const cmd = createGoalCommand({ getStore: () => store, getSteeringInjector: () => injector });
    const result = await cmd.execute("revised objective", ctx);
    expect(injectCalls).toBe(0);
    expect(result?.message).toContain("will re-anchor once the current turn finishes");
  });

  it("does not throw and falls back to the not-injected message when no injector provider is set", async () => {
    const store = freshStore();
    store.createGoal("original objective");
    const cmd = createGoalCommand({ getStore: () => store });
    const result = await cmd.execute("revised objective", ctx);
    expect(result?.message).toContain("will re-anchor once the current turn finishes");
  });

  it("uses the module-level provider set by setGoalSteeringInjectorProvider when no dep override is given", async () => {
    const store = freshStore();
    store.createGoal("original objective");
    let injected = "";
    setGoalSteeringInjectorProvider(() => ({
      canInjectNow: () => true,
      inject: (prompt: string) => { injected = prompt; },
    }));
    const cmd = createGoalCommand({ getStore: () => store });
    await cmd.execute("revised objective", ctx);
    expect(injected).toContain("revised objective");
  });
});
