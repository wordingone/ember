// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/goal-live-session.ts — deterministic local model-session probe for
// the compiled Ember goal organ (issue #211). This explicit diagnostic surface
// drives the production GoalStore/continuation engine with a content-fixed
// local stub and returns only path-free evidence.

import {
  createGoalContinuationEngine,
} from "../core/goal-continuation.ts";
import { createGoalContinuationPoke } from "../core/goal-continuation-wiring.ts";
import {
  createGoalStore,
  createInMemoryGoalPersistence,
  type CompletionAudit,
  type GoalStatus,
} from "../core/goal-store.ts";
import {
  receiptGoalTransition,
  type GoalReceiptEvent,
  type GoalReceiptWriter,
} from "./goal-receipts.ts";
import { captureGoalLiveFrames, type GoalLiveFrameCapture } from "./goal-live-session-frames.ts";
import { UpdateGoalTool } from "../tools/goal-tools.ts";

export const GOAL_LIVE_RECEIPT_SCHEMA = "ember-goal-live-session-receipt-v1" as const;

interface CapturedEvent {
  event: GoalReceiptEvent;
  goalId?: string;
  detail?: Record<string, unknown>;
}

export interface GoalLiveSessionReceipt {
  goal_id: "EMBER-02";
  workstream_id: "EMBER-02A";
  next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember";
  schema_version: typeof GOAL_LIVE_RECEIPT_SCHEMA;
  result: "MEASURED";
  model: "deterministic-local-stub-v1";
  zero_user_input_after_boot: true;
  autonomous_continuations: number;
  continuation_events: number;
  premature_complete_refusal: {
    tool_validation: true;
    store_boundary: true;
  };
  complete_transition: {
    status: "Complete";
    audit_bound: true;
    requirement_ids: string[];
  };
  user_preemption: {
    outcome: "queued_user_input";
    start_turn_calls: number;
    receipt_event: "continuation_skipped";
  };
  frame_captures: GoalLiveFrameCapture[];
  events: CapturedEvent[];
}

const FIXED_NOW = new Date("2026-08-07T00:00:00.000Z");
const FIXED_GOAL_ID = "goal-live-session-v1";
const FIXED_PREEMPT_GOAL_ID = "goal-live-preemption-v1";

function memoryWriter(events: CapturedEvent[]): GoalReceiptWriter {
  return {
    filePath: "",
    append(event, goalId, detail) {
      events.push({
        event,
        ...(goalId === undefined ? {} : { goalId }),
        ...(detail === undefined ? {} : { detail }),
      });
    },
  };
}

function waitFor(predicate: () => boolean, timeoutMs = 2_000): Promise<void> {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const check = (): void => {
      if (predicate()) {
        resolve();
        return;
      }
      if (Date.now() - started >= timeoutMs) {
        reject(new Error("goal live-session probe timed out"));
        return;
      }
      setTimeout(check, 1);
    };
    check();
  });
}

function statusFromGoal(value: unknown): GoalStatus | null {
  if (!value || typeof value !== "object") return null;
  const status = (value as { status?: unknown }).status;
  return typeof status === "string" ? status as GoalStatus : null;
}

/** Runs the real production continuation engine against a deterministic local stub. */
interface PreemptionEvidence {
  events: CapturedEvent[];
  startTurnCalls: number;
  reason: string;
}

async function runQueuedInputPreemption(): Promise<PreemptionEvidence> {
  const preemptionEvents: CapturedEvent[] = [];
  const preemptionWriter = memoryWriter(preemptionEvents);
  const preemptionStore = createGoalStore({
    persistence: createInMemoryGoalPersistence(),
    now: () => new Date(FIXED_NOW),
    generateId: () => FIXED_PREEMPT_GOAL_ID,
    onTransition: (event) => receiptGoalTransition(preemptionWriter, event),
  });
  const preemptionGoal = preemptionStore.createGoal("queued input wins", { tokenBudget: 10 });
  if (!preemptionGoal.ok) throw new Error(preemptionGoal.message);
  let startTurnCalls = 0;
  const outcome = await createGoalContinuationEngine().maybeContinueIfIdle({
    store: preemptionStore,
    getEligibilitySignals: () => ({
      featureEnabled: true,
      planMode: false,
      turnActive: false,
      queuedUserInput: true,
    }),
    startTurn: async () => { startTurnCalls += 1; },
  });
  if (outcome.fired) throw new Error("queued user input did not preempt continuation");
  preemptionWriter.append("continuation_skipped", FIXED_PREEMPT_GOAL_ID, {
    reason: outcome.reason,
  });
  return { events: preemptionEvents, startTurnCalls, reason: outcome.reason };
}

export async function runGoalLiveSession(): Promise<GoalLiveSessionReceipt> {
  const events: CapturedEvent[] = [];
  const writer = memoryWriter(events);
  const store = createGoalStore({
    persistence: createInMemoryGoalPersistence(),
    now: () => new Date(FIXED_NOW),
    generateId: () => FIXED_GOAL_ID,
    onTransition: (event) => receiptGoalTransition(writer, event),
  });
  const preemption = await runQueuedInputPreemption();
  const preemptionEvents = preemption.events;
  const preemptionStartCalls = preemption.startTurnCalls;
  const created = store.createGoal("prove the compiled goal organ is live", { tokenBudget: 100 });
  let queuedUserInput = false;
  if (!created.ok) throw new Error(created.message);

  let turnActive = false;
  let turns = 0;
  let prematureToolRefusal = false;
  let prematureStoreRefusal = false;
  const audit: CompletionAudit = {
    requirements: [
      { id: "continuations", evidence: "three autonomous continuation events observed" },
      { id: "preemption", evidence: `queued user input suppressed continuation (reason: ${preemption.reason})` },
    ],
  };

  const engine = createGoalContinuationEngine();
  const poke = createGoalContinuationPoke({
    engine,
    getStore: () => store,
    getEligibilitySignals: () => ({
      featureEnabled: true,
      planMode: false,
      turnActive,
      queuedUserInput,
    }),
    startTurn: async () => {
      turns += 1;
      turnActive = true;
      try {
        store.recordUsage(1, 1);
        if (turns === 1) {
          const validateInput = UpdateGoalTool.validateInput;
          if (typeof validateInput !== "function") throw new Error("update_goal validator is unavailable");
          const toolAttempt = validateInput({ status: "Complete" });
          prematureToolRefusal = toolAttempt?.result === false;
          prematureStoreRefusal = !store.updateStatus("Complete").ok;
        }
        if (turns === 3) {
          const completed = store.updateStatus("Complete", { completionAudit: audit });
          if (!completed.ok) throw new Error(completed.message);
        }
      } finally {
        turnActive = false;
      }
    },
    getReceiptWriter: () => writer,
  });

  // One initial operator turn is implicit in the probe. All three subsequent
  // turns are generated by the production self-chaining continuation poke.
  poke();
  await waitFor(() => turns === 3 && statusFromGoal(store.getGoal()) === "Complete");


  const complete = store.getGoal();
  if (!complete || complete.status !== "Complete" || !complete.completionAudit) {
    throw new Error("Complete transition did not retain its audit evidence");
  }
  const combinedEvents = [...preemptionEvents, ...events];
  const continuationEvents = combinedEvents.filter((event) => event.event === "continuation_fired");
  const preemptionEvent = preemptionEvents.find((event) => event.event === "continuation_skipped");
  if (continuationEvents.length < 3 || !preemptionEvent) {
    throw new Error("goal live-session event evidence is incomplete");
  }
  if (!prematureToolRefusal || !prematureStoreRefusal) {
    throw new Error("premature Complete transition was not refused at both boundaries");
  }

  const frameCaptures = captureGoalLiveFrames(combinedEvents, FIXED_PREEMPT_GOAL_ID);
  return {
    schema_version: GOAL_LIVE_RECEIPT_SCHEMA,
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    result: "MEASURED",
    model: "deterministic-local-stub-v1",
    zero_user_input_after_boot: true,
    autonomous_continuations: turns,
    continuation_events: continuationEvents.length,
    premature_complete_refusal: {
      tool_validation: prematureToolRefusal,
      store_boundary: prematureStoreRefusal,
    },
    complete_transition: {
      status: "Complete",
      audit_bound: true,
      requirement_ids: audit.requirements.map((item) => item.id),
    },
    user_preemption: {
      outcome: "queued_user_input",
      start_turn_calls: preemptionStartCalls,
      receipt_event: "continuation_skipped",
    },
    frame_captures: frameCaptures,
    events: combinedEvents,
  };
}
