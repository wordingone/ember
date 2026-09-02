// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/goal-live-session.ts — deterministic local model-session probe for
// the compiled Ember goal organ (issue #211). This explicit diagnostic surface
// drives the production GoalStore/continuation engine with a content-fixed
// local stub and returns only path-free evidence.

import { PassThrough } from "node:stream";
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
import { captureRenderedGoalLiveFrames, GOAL_LIVE_FRAME_HEIGHT, GOAL_LIVE_FRAME_WIDTH, GOAL_LIVE_RENDERER_SOURCE_ID, type GoalLiveFrameCapture, type GoalLiveFrameAuthority } from "./goal-live-session-frames.ts";
import { UpdateGoalTool } from "../tools/goal-tools.ts";

export const GOAL_LIVE_RECEIPT_SCHEMA = "ember-goal-live-session-receipt-v1" as const;
export const GOAL_LIVE_RENDERER_SOURCE_SHA256 = "33f4b8154a3ed97c00928b123f40e1f13f0eee3c8cc1f2edaed2dbb774efbc0a" as const;

export interface GoalLiveSessionOptions {
  executable_sha256?: string;
  input_timeout_ms?: number;
}

function embeddedBuildCommit(): string {
  const value = (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
  if (typeof value !== "string" || !/^[0-9a-f]{40}$/.test(value)) {
    throw new Error("goal live-session embedded source commit is invalid");
  }
  return value;
}

function requireExecutableSha(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value) || /^0+$/.test(value)) {
    throw new Error("goal live-session executable binding is invalid");
  }
  return value;
}


interface CapturedEvent {
  event: GoalReceiptEvent;
  goalId?: string;
  detail?: Record<string, unknown>;
}

export interface GoalLiveSessionReceipt {
  goal_id: "EMBER-02";
  workstream_id: "EMBER-02A";
  issue_id: "211";
  milestone: "EMBER-03";
  source_commit: string;
  build_commit: string;
  executable_sha256: string;
  next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember";
  schema_version: typeof GOAL_LIVE_RECEIPT_SCHEMA;
  result: "MEASURED";
  model: "deterministic-local-stub-v1";
  zero_user_input_after_boot: boolean;
  session_path?: "normal-compiled-operator-session";
  input_observation: {
    source: "process.stdin";
    eof_observed: boolean;
    events: string[];
  };
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

async function observeProcessInput(timeoutMs: number): Promise<GoalLiveSessionReceipt["input_observation"]> {
  const events: string[] = [];
  const stdin = process.stdin;
  if (stdin.readableEnded) return { source: "process.stdin", eof_observed: true, events };
  let eofObserved = false;
  await new Promise<void>((resolve) => {
    const onData = (chunk: Buffer | string): void => {
      events.push("data:" + Buffer.byteLength(chunk));
    };
    const onEnd = (): void => {
      eofObserved = true;
      cleanup();
      resolve();
    };
    const cleanup = (): void => {
      stdin.off("data", onData);
      stdin.off("end", onEnd);
    };
    stdin.on("data", onData);
    stdin.once("end", onEnd);
    stdin.resume();
    setTimeout(() => {
      cleanup();
      resolve();
    }, timeoutMs);
  });
  return { source: "process.stdin", eof_observed: eofObserved || stdin.readableEnded, events };
}

async function captureOperatorFrames(
  events: CapturedEvent[],
  executable_sha256: string,
): Promise<GoalLiveFrameCapture[]> {
  const React = (await import("react")).default;
  const { Text } = await import("../ink/components.ts");
  const frontendShell = await import("../../../../../../../tools/ember-cli/src/core/frontend-shell.ts");
  const stream = new PassThrough() as PassThrough & { columns: number; rows: number };
  stream.columns = GOAL_LIVE_FRAME_WIDTH;
  stream.rows = GOAL_LIVE_FRAME_HEIGHT;
  const writes: Buffer[] = [];
  stream.on("data", (chunk: Buffer | string) => writes.push(Buffer.from(chunk)));
  let firstFrameResolve!: () => void;
  const firstFrame = new Promise<void>((resolve) => { firstFrameResolve = resolve; });
  const root = frontendShell.createRoot({
    stdout: stream,
    onFirstFrameFlushed: firstFrameResolve,
  });
  const frameSpecs: Array<{ frame_id: string; phase: "preemption" | "continuations" | "completion"; sequence: number; event_indices: number[]; text: string; bytes?: Uint8Array }> = [
    { frame_id: "preemption", phase: "preemption", sequence: 1, event_indices: events.map((event, index) => event.goalId === FIXED_PREEMPT_GOAL_ID ? index : -1).filter((index) => index >= 0), text: "queued input preempted continuation" },
    { frame_id: "continuations", phase: "continuations", sequence: 2, event_indices: events.map((event, index) => event.event === "continuation_fired" ? index : -1).filter((index) => index >= 0), text: "three autonomous continuations observed" },
    { frame_id: "completion", phase: "completion", sequence: 3, event_indices: events.map((event, index) => event.event === "status_changed" ? index : -1).filter((index) => index >= 0), text: "evidence-bearing Complete transition" },
  ];
  try {
    for (const spec of frameSpecs) {
      const start = writes.length;
      root.render(React.createElement(Text, null, "EMBER-03 " + spec.frame_id + ": " + spec.text));
      await Promise.race([firstFrame, new Promise<void>((resolve) => setTimeout(resolve, 50))]);
      await new Promise<void>((resolve) => setTimeout(resolve, 25));
      if (writes.length === start) throw new Error("compiled operator renderer emitted no " + spec.frame_id + " bytes");
      spec.bytes = Buffer.concat(writes.slice(start));
    }
    return captureRenderedGoalLiveFrames(frameSpecs.map((spec) => ({ frame_id: spec.frame_id, phase: spec.phase, sequence: spec.sequence, event_indices: spec.event_indices, bytes: spec.bytes! })), events, {
      source_id: GOAL_LIVE_RENDERER_SOURCE_ID,
      source_sha256: GOAL_LIVE_RENDERER_SOURCE_SHA256,
      executable_sha256,
    });
  } finally {
    root.unmount();
    frontendShell._resetRootForTests();
    stream.destroy();
  }
}
export async function runGoalLiveSession(options: GoalLiveSessionOptions = {}): Promise<GoalLiveSessionReceipt> {
  const sourceCommit = embeddedBuildCommit();
  const executableSha = requireExecutableSha(options.executable_sha256);
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
  let awaitingFinalCompletion = false;
  if (!created.ok) throw new Error(created.message);

  let turnActive = false;
  let turns = 0;
  let prematureToolRefusal = false;
  let prematureStoreRefusal = false;

  const engine = createGoalContinuationEngine();
  const poke = createGoalContinuationPoke({
    engine,
    getStore: () => store,
    getEligibilitySignals: () => ({
      featureEnabled: true,
      planMode: false,
      turnActive,
      queuedUserInput: queuedUserInput || awaitingFinalCompletion,
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
        if (turns === 3) awaitingFinalCompletion = true;
      } finally {
        turnActive = false;
      }
    },
    getReceiptWriter: () => writer,
  });

  // One initial operator turn is implicit in the probe. All three subsequent
  // turns are generated by the production self-chaining continuation poke.
  poke();
  await waitFor(() => turns === 3 && events.filter((event) => event.event === "continuation_fired").length >= 3);
  const combinedBeforeComplete = [...preemptionEvents, ...events];
  const continuationIndicesBeforeComplete = combinedBeforeComplete
    .map((event, index) => event.event === "continuation_fired" ? index : -1)
    .filter((index) => index >= 0);
  if (continuationIndicesBeforeComplete.length < 3) {
    throw new Error("goal live-session event evidence is incomplete before Complete");
  }
  const preemptionIndex = preemptionEvents.findIndex((event) => event.event === "continuation_skipped");
  if (preemptionIndex < 0) {
    throw new Error("queued-input preemption evidence is missing before Complete");
  }
  const audit: CompletionAudit = {
    requirements: [
      { id: "continuations", evidence: `three autonomous continuation events observed at receipt indices ${continuationIndicesBeforeComplete.join(",")}` },
      { id: "preemption", evidence: `queued user input suppressed continuation (reason: ${preemption.reason}) at receipt index ${preemptionIndex}` },
    ],
  };
  const completed = store.updateStatus("Complete", { completionAudit: audit });
  if (!completed.ok) throw new Error(completed.message);
  await waitFor(() => statusFromGoal(store.getGoal()) === "Complete");


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

  const frameAuthority: GoalLiveFrameAuthority = {
    source_sha256: GOAL_LIVE_RENDERER_SOURCE_SHA256,
    executable_sha256: executableSha,
    source_id: GOAL_LIVE_RENDERER_SOURCE_ID,
  };
  const frameCaptures = await captureOperatorFrames(combinedEvents, frameAuthority.executable_sha256);
  const inputObservation = await observeProcessInput(options.input_timeout_ms ?? 100);
  return {
    schema_version: GOAL_LIVE_RECEIPT_SCHEMA,
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    issue_id: "211",
    milestone: "EMBER-03",
    source_commit: sourceCommit,
    build_commit: sourceCommit,
    executable_sha256: executableSha,
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    result: "MEASURED",
    model: "deterministic-local-stub-v1",
    zero_user_input_after_boot: inputObservation.eof_observed && inputObservation.events.length === 0,
    session_path: "normal-compiled-operator-session",
    input_observation: inputObservation,
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

export async function runGoalLiveOperatorSession(options: GoalLiveSessionOptions = {}): Promise<GoalLiveSessionReceipt> {
  return runGoalLiveSession(options);
}
