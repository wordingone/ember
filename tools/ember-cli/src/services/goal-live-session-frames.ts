// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { createHash } from "node:crypto";
import type { GoalReceiptEvent } from "./goal-receipts.ts";

export const GOAL_LIVE_RENDERER_SOURCE_ID = "ember-goal-live-renderer-v1" as const;
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
  source_id: typeof GOAL_LIVE_RENDERER_SOURCE_ID;
}

export interface GoalLiveFrameCapture {
  renderer: "ember-ink-reconciler";
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
    id: typeof GOAL_LIVE_RENDERER_SOURCE_ID;
    sha256: string;
    executable_sha256: string;
  };
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
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
    || frame.event_indices.some((index) => !Number.isInteger(index) || index < 0 || index >= events.length)
    || frame.receipt_start_index !== Math.min(...frame.event_indices)
    || frame.receipt_end_index !== Math.max(...frame.event_indices)
    || frame.sequence <= 0) {
    throw new Error("goal live-session frame dimensions/range are invalid");
  }
  if (authority.source_id !== GOAL_LIVE_RENDERER_SOURCE_ID
    || frame.source_binding.id !== GOAL_LIVE_RENDERER_SOURCE_ID
    || frame.renderer !== "ember-ink-reconciler"
    || frame.source_binding.sha256 !== authority.source_sha256
    || frame.source_binding.executable_sha256 !== authority.executable_sha256) {
    throw new Error("goal live-session frame source authority is invalid");
  }
  requireHex(authority.source_sha256, "source");
  requireHex(authority.executable_sha256, "executable");
  const actualBytes = Buffer.from(frame.frame_bytes_base64, "base64");
  if (frame.frame_sha256 !== sha256(actualBytes)) {
    throw new Error("goal live-session frame bytes do not match observed events");
  }
}


export interface RenderedGoalLiveFrameInput {
  frame_id: string;
  phase: GoalLiveFramePhase;
  sequence: number;
  event_indices: number[];
  bytes: Uint8Array;
}

/** Binds bytes emitted by the real Ink reconciler; it never synthesizes bytes from receipt events. */
export function captureRenderedGoalLiveFrames(
  rendered: RenderedGoalLiveFrameInput[],
  events: GoalLiveFrameEvent[],
  authority: GoalLiveFrameAuthority,
): GoalLiveFrameCapture[] {
  if (authority.source_id !== GOAL_LIVE_RENDERER_SOURCE_ID || rendered.length !== 3) {
    throw new Error("goal live-session renderer capture authority is incomplete");
  }
  const frames = rendered.map((input) => {
    if (input.bytes.length === 0 || input.event_indices.length === 0) {
      throw new Error("goal live-session renderer emitted an empty frame");
    }
    const frame: GoalLiveFrameCapture = {
      frame_id: input.frame_id,
      phase: input.phase,
      sequence: input.sequence,
      width: GOAL_LIVE_FRAME_WIDTH,
      height: GOAL_LIVE_FRAME_HEIGHT,
      receipt_start_index: Math.min(...input.event_indices),
      receipt_end_index: Math.max(...input.event_indices),
      event_indices: input.event_indices,
      event_count: input.event_indices.length,
      frame_bytes_base64: Buffer.from(input.bytes).toString("base64"),
      frame_sha256: sha256(input.bytes),
      renderer: "ember-ink-reconciler",
      source_binding: {
        id: GOAL_LIVE_RENDERER_SOURCE_ID,
        sha256: authority.source_sha256,
        executable_sha256: authority.executable_sha256,
      },
    };
    validateGoalLiveFrameCapture(frame, events, authority);
    return frame;
  });
  const expectedPhases: GoalLiveFramePhase[] = ["preemption", "continuations", "completion"];
  if (frames.some((frame, index) => frame.phase !== expectedPhases[index] || frame.sequence !== index + 1)) {
    throw new Error("goal live-session renderer frame phases are incomplete or out of order");
  }
  return frames;
}
