// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { createHash } from "node:crypto";
import type { GoalReceiptEvent } from "./goal-receipts.ts";

export const GOAL_LIVE_FRAME_SOURCE_ID = "ember-goal-live-session-source-v1" as const;
export const GOAL_LIVE_FRAME_WIDTH = 96 as const;
export const GOAL_LIVE_FRAME_HEIGHT = 8 as const;

export type GoalLiveFramePhase = "preemption" | "continuations" | "completion";

export interface GoalLiveFrameEvent {
  event: GoalReceiptEvent;
  goalId?: string;
  detail?: Record<string, unknown>;
}

export interface GoalLiveFrameAuthority {
  source_sha256: string;
  executable_sha256: string;
}

export interface GoalLiveFrameCapture {
  frame_id: string;
  phase: GoalLiveFramePhase;
  sequence: number;
  width: typeof GOAL_LIVE_FRAME_WIDTH;
  height: typeof GOAL_LIVE_FRAME_HEIGHT;
  receipt_start_index: number;
  receipt_end_index: number;
  event_indices: number[];
  event_count: number;
  frame_bytes_base64: string;
  frame_sha256: string;
  source_binding: {
    id: typeof GOAL_LIVE_FRAME_SOURCE_ID;
    sha256: string;
    executable_sha256: string;
  };
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function renderFrameBytes(
  frameId: string,
  phase: GoalLiveFramePhase,
  eventIndices: number[],
  events: GoalLiveFrameEvent[],
): Uint8Array {
  const start = Math.min(...eventIndices);
  const end = Math.max(...eventIndices);
  const lines = [
    "ember-goal-live-frame-v1",
    `frame_id=${frameId}`,
    `phase=${phase}`,
    `receipt_range=${start}-${end}`,
    ...eventIndices.map((index) => `event_index=${index} ${JSON.stringify(events[index])}`),
  ];
  const rendered = Array.from(
    { length: GOAL_LIVE_FRAME_HEIGHT },
    (_, index) => (lines[index] ?? "").slice(0, GOAL_LIVE_FRAME_WIDTH).padEnd(GOAL_LIVE_FRAME_WIDTH, " "),
  ).join("\n");
  return new TextEncoder().encode(rendered);
}

function requireHex(value: string, label: string): void {
  if (!/^[0-9a-f]{64}$/.test(value)) throw new Error(`goal live-session ${label} binding is invalid`);
}

export function validateGoalLiveFrameCapture(
  frame: GoalLiveFrameCapture,
  events: GoalLiveFrameEvent[],
  authority: GoalLiveFrameAuthority,
): void {
  if (frame.width !== GOAL_LIVE_FRAME_WIDTH || frame.height !== GOAL_LIVE_FRAME_HEIGHT
    || frame.event_count <= 0 || frame.event_count !== frame.event_indices.length
    || frame.receipt_start_index !== Math.min(...frame.event_indices)
    || frame.receipt_end_index !== Math.max(...frame.event_indices)
    || frame.sequence <= 0) {
    throw new Error("goal live-session frame dimensions/range are invalid");
  }
  if (frame.source_binding.id !== GOAL_LIVE_FRAME_SOURCE_ID
    || frame.source_binding.sha256 !== authority.source_sha256
    || frame.source_binding.executable_sha256 !== authority.executable_sha256) {
    throw new Error("goal live-session frame source authority is invalid");
  }
  requireHex(authority.source_sha256, "source");
  requireHex(authority.executable_sha256, "executable");
  const expectedBytes = renderFrameBytes(frame.frame_id, frame.phase, frame.event_indices, events);
  const actualBytes = Buffer.from(frame.frame_bytes_base64, "base64");
  if (actualBytes.length !== expectedBytes.length
    || !Buffer.from(actualBytes).equals(Buffer.from(expectedBytes))
    || frame.frame_sha256 !== sha256(expectedBytes)) {
    throw new Error("goal live-session frame bytes/hash do not match observed events");
  }
}

function captureFrame(
  frameId: string,
  phase: GoalLiveFramePhase,
  sequence: number,
  eventIndices: number[],
  events: GoalLiveFrameEvent[],
  authority: GoalLiveFrameAuthority,
): GoalLiveFrameCapture {
  if (eventIndices.length === 0 || eventIndices.some((index) => !events[index])) {
    throw new Error(`frame ${frameId} references an unavailable event`);
  }
  const bytes = renderFrameBytes(frameId, phase, eventIndices, events);
  const frame: GoalLiveFrameCapture = {
    frame_id: frameId,
    phase,
    sequence,
    width: GOAL_LIVE_FRAME_WIDTH,
    height: GOAL_LIVE_FRAME_HEIGHT,
    receipt_start_index: Math.min(...eventIndices),
    receipt_end_index: Math.max(...eventIndices),
    event_indices: eventIndices,
    event_count: eventIndices.length,
    frame_bytes_base64: Buffer.from(bytes).toString("base64"),
    frame_sha256: sha256(bytes),
    source_binding: {
      id: GOAL_LIVE_FRAME_SOURCE_ID,
      sha256: authority.source_sha256,
      executable_sha256: authority.executable_sha256,
    },
  };
  validateGoalLiveFrameCapture(frame, events, authority);
  return frame;
}

export function captureGoalLiveFrames(
  events: GoalLiveFrameEvent[],
  preemptionGoalId: string,
  authority: GoalLiveFrameAuthority,
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
    captureFrame("preemption", "preemption", 1, preemptionIndices, events, authority),
    captureFrame("continuations", "continuations", 2, continuationIndices, events, authority),
    captureFrame("completion", "completion", 3, completionIndices, events, authority),
  ];
  const expectedPhases: GoalLiveFramePhase[] = ["preemption", "continuations", "completion"];
  if (frames.some((frame, index) => frame.phase !== expectedPhases[index]
    || frame.sequence !== index + 1)) {
    throw new Error("goal live-session frame phases are incomplete or out of order");
  }
  return frames;
}
