// tools/goal-tools.test.ts — model-side tool tests for get_goal / create_goal /
// update_goal (ember issue #211). Every test wires setGoalStoreForTests to an
// in-memory store so no filesystem is ever touched.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { GetGoalTool, CreateGoalTool, UpdateGoalTool } from "./goal-tools.ts";
import { createGoalStore, createInMemoryGoalPersistence } from "../core/goal-store.ts";
import { setGoalStoreForTests, resetGoalRuntimeForTests } from "../core/goal-runtime.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";

function fakeContext(overrides: Partial<ToolUseContext> = {}): ToolUseContext {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: async () => {},
    messages: [],
    ...overrides,
  };
}

beforeEach(() => {
  setGoalStoreForTests(createGoalStore({ persistence: createInMemoryGoalPersistence() }));
});

afterEach(() => {
  resetGoalRuntimeForTests();
});

// ---------------------------------------------------------------------------
// get_goal
// ---------------------------------------------------------------------------

describe("get_goal", () => {
  it("returns exists:false when no goal is set", async () => {
    const result = await GetGoalTool.call({}, fakeContext());
    expect(result.data).toEqual({ exists: false, message: "no active goal" });
  });

  it("returns the full goal record when one exists", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit", { tokenBudget: 5000 });
    setGoalStoreForTests(store);

    const result = (await GetGoalTool.call({}, fakeContext())).data as Record<string, unknown>;
    expect(result["exists"]).toBe(true);
    expect(result["objective"]).toBe("reach the summit");
    expect(result["status"]).toBe("Active");
    expect(result["tokenBudget"]).toBe(5000);
  });

  it("is read-only and concurrency-safe", () => {
    expect(GetGoalTool.isReadOnly()).toBe(true);
    expect(GetGoalTool.isConcurrencySafe()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// create_goal
// ---------------------------------------------------------------------------

describe("create_goal", () => {
  it("creates a new goal and returns ok:true", async () => {
    const result = await CreateGoalTool.call({ objective: "reach the summit" }, fakeContext());
    const data = result.data as { ok: boolean; goal?: { objective: string } };
    expect(data.ok).toBe(true);
    expect(data.goal?.objective).toBe("reach the summit");
  });

  it("fails with ok:false when a goal already exists", async () => {
    await CreateGoalTool.call({ objective: "first" }, fakeContext());
    const result = await CreateGoalTool.call({ objective: "second" }, fakeContext());
    const data = result.data as { ok: boolean; message?: string };
    expect(data.ok).toBe(false);
    expect(data.message).toContain("already exists");
  });

  it("refuses on an ephemeral (non-interactive) session", async () => {
    const result = await CreateGoalTool.call(
      { objective: "reach the summit" },
      fakeContext({ isNonInteractiveSession: true }),
    );
    const data = result.data as { ok: boolean; message?: string };
    expect(data.ok).toBe(false);
    expect(data.message).toContain("ephemeral");
  });

  it("mapToolResultToToolResultBlockParam sets is_error on failure, not on success", () => {
    const okBlock = CreateGoalTool.mapToolResultToToolResultBlockParam({ ok: true }, "t1");
    expect(okBlock.is_error).toBeFalsy();
    const failBlock = CreateGoalTool.mapToolResultToToolResultBlockParam(
      { ok: false, message: "boom" },
      "t2",
    );
    expect(failBlock.is_error).toBe(true);
  });

  it("validateInput rejects a payload missing 'objective'", () => {
    const result = CreateGoalTool.validateInput?.({ tokenBudget: 100 });
    expect(result?.result).toBe(false);
  });

  it("validateInput rejects an unknown extra field (schema is .strict())", () => {
    const result = CreateGoalTool.validateInput?.({
      objective: "x",
      unexpectedField: "should not be allowed",
    });
    expect(result?.result).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// update_goal — the objective-immutability enforcement point
// ---------------------------------------------------------------------------

describe("update_goal — status-only, objective immutable", () => {
  it("validateInput REJECTS a payload carrying an 'objective' field — the schema has no such field", () => {
    const result = UpdateGoalTool.validateInput?.({
      status: "Paused",
      objective: "sneaky rewrite attempt",
    });
    expect(result?.result).toBe(false);
  });

  it("a successful status-only call never changes the objective", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("original objective");
    setGoalStoreForTests(store);

    await UpdateGoalTool.call({ status: "Paused" }, fakeContext());
    expect(store.getGoal()?.objective).toBe("original objective");
    expect(store.getGoal()?.status).toBe("Paused");
  });

  it("rejects a status value outside the model-settable set (e.g. 'UsageLimited' is system-only)", () => {
    const result = UpdateGoalTool.validateInput?.({ status: "UsageLimited" });
    expect(result?.result).toBe(false);
  });

  it("rejects a status value outside the model-settable set (e.g. 'BudgetLimited' is system-only)", () => {
    const result = UpdateGoalTool.validateInput?.({ status: "BudgetLimited" });
    expect(result?.result).toBe(false);
  });

  it("an illegal transition (per the state machine) returns ok:false without mutating status", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    store.updateStatus("Paused");
    setGoalStoreForTests(store);

    // Paused can only resume to Active; Blocked is illegal from Paused.
    const result = await UpdateGoalTool.call({ status: "Blocked" }, fakeContext());
    const data = result.data as { ok: boolean };
    expect(data.ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Paused");
  });

  it("carries an optional reason through to the store", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    await UpdateGoalTool.call({ status: "Paused", reason: "operator requested" }, fakeContext());
    expect(store.getGoal()?.status).toBe("Paused");
  });

  it("fails with ok:false when no goal exists", async () => {
    const result = await UpdateGoalTool.call({ status: "Active" }, fakeContext());
    const data = result.data as { ok: boolean };
    expect(data.ok).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// update_goal("Blocked") — the code-checkable half of the BLOCKED AUDIT
// ---------------------------------------------------------------------------

describe("update_goal — Blocked requires the 3-consecutive-turn audit", () => {
  it("rejects a Blocked call with no reason given", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    const result = await UpdateGoalTool.call({ status: "Blocked" }, fakeContext());
    const data = result.data as { ok: boolean; message?: string };
    expect(data.ok).toBe(false);
    expect(data.message).toContain("reason");
    expect(store.getGoal()?.status).toBe("Active");
  });

  it("rejects the FIRST and SECOND Blocked call for the same reason (not yet 3 consecutive)", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    const r1 = await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());
    expect((r1.data as { ok: boolean }).ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Active");

    const r2 = await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());
    expect((r2.data as { ok: boolean }).ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Active");
  });

  it("accepts the THIRD consecutive Blocked call for the SAME reason", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());
    const r3 = await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());

    expect((r3.data as { ok: boolean }).ok).toBe(true);
    expect(store.getGoal()?.status).toBe("Blocked");
  });

  it("a DIFFERENT reason on the second call resets the audit — never blocked on a rotating cause", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "rate limited" }, fakeContext());
    // Third call switches reason -- audit restarts at 1, so this must still be rejected.
    const r3 = await UpdateGoalTool.call({ status: "Blocked", reason: "disk full" }, fakeContext());
    expect((r3.data as { ok: boolean }).ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Active");
  });
});
