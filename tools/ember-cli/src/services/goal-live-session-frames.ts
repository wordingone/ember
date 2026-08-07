// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { createHash } from "node:crypto";
import type { GoalReceiptEvent } from "./goal-receipts.ts";

export const GOAL_LIVE_FRAME_SOURCE_ID = "ember-goal-live-session-source-v1" as const;
export const GOAL_LIVE_FRAME_SOURCE_SHA256 = createHash("sha256")
  .update(GOAL_LIVE_FRAME_SOURCE_ID)
  .digest("hex");

export type GoalLiveFramePhase = "preemption" | "continuations" | "completion";

export interface GoalLiveFrameEvent {
  event: GoalReceiptEvent;
  goalId?: string;
}

export interface GoalLiveFrameCapture {
  frame_id: string;
  phase: GoalLiveFramePhase;
  event_indices: number[];
  event_count: number;
  frame_sha256: string;
  source_binding: {
    id: typeof GOAL_LIVE_FRAME_SOURCE_ID;
    sha256: string;
  };
}

interface FrameDigestInput {
  frame_id: string;
  phase: GoalLiveFramePhase;
  event_indices: number[];
  event_count: number;
  event_types: GoalReceiptEvent[];
}

function frameDigest(input: FrameDigestInput): string {
  return createHash("sha256").update(JSON.stringify(input)).digest("hex");
}

function captureFrame(
  frameId: string,
  phase: GoalLiveFramePhase,
  eventIndices: number[],
  events: GoalLiveFrameEvent[],
): GoalLiveFrameCapture {
  const eventTypes = eventIndices.map((index) => events[index]?.event);
  if (eventTypes.some((event) => event === undefined)) {
    throw new Error(`frame ${frameId} references an unavailable event`);
  }
  const input: FrameDigestInput = {
    frame_id: frameId,
    phase,
    event_indices: eventIndices,
    event_count: eventIndices.length,
    event_types: eventTypes as GoalReceiptEvent[],
  };
  return {
    ...input,
    frame_sha256: frameDigest(input),
    source_binding: {
      id: GOAL_LIVE_FRAME_SOURCE_ID,
      sha256: GOAL_LIVE_FRAME_SOURCE_SHA256,
    },
  };
}

export function captureGoalLiveFrames(
  events: GoalLiveFrameEvent[],
  preemptionGoalId: string,
): GoalLiveFrameCapture[] {
  const preemptionIndices = events
    .map((event, index) => event.goalId === preemptionGoalId ? index : -1)
    .filter((index) => index >= 0);
  const continuationIndices = events
    .map((event, index) => event.event === "continuation_fired" ? index : -1)
    .filter((index) => index >= 0);
  const completionIndices = events
    .map((event, index) => event.event === "status_changed" ? index : -1)
    .filter((index) => index >= 0);
  const frames = [
    captureFrame("preemption", "preemption", preemptionIndices, events),
    captureFrame("continuations", "continuations", continuationIndices, events),
    captureFrame("completion", "completion", completionIndices, events),
  ];
  const expectedPhases: GoalLiveFramePhase[] = ["preemption", "continuations", "completion"];
  if (frames.some((frame, index) => frame.phase !== expectedPhases[index])) {
    throw new Error("goal live-session frame phases are incomplete or out of order");
  }
  for (const frame of frames) {
    if (frame.source_binding.id !== GOAL_LIVE_FRAME_SOURCE_ID
      || frame.source_binding.sha256 !== GOAL_LIVE_FRAME_SOURCE_SHA256
      || frame.event_count <= 0
      || frame.event_count !== frame.event_indices.length) {
      throw new Error("goal live-session frame authority is invalid");
    }
    const eventTypes = frame.event_indices.map((index) => events[index]?.event);
    if (eventTypes.some((event) => event === undefined)) {
      throw new Error("goal live-session frame references an unavailable event");
    }
    const input: FrameDigestInput = {
      frame_id: frame.frame_id,
      phase: frame.phase,
      event_indices: frame.event_indices,
      event_count: frame.event_count,
      event_types: eventTypes as GoalReceiptEvent[],
    };
    if (frame.frame_sha256 !== frameDigest(input)) {
      throw new Error("goal live-session frame hash does not match observed events");
    }
  }
  return frames;
}
