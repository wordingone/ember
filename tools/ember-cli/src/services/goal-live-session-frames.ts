// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue_id: 211
// milestone: EMBER-03
import { createHash } from "node:crypto";
import type { GoalReceiptEvent } from "./goal-receipts.ts";

export const GOAL_LIVE_RENDERER_SOURCE_ID = "ember-goal-live-renderer-v1" as const;
export const GOAL_LIVE_FRAME_ENCODING = "utf8-terminal-grid-v1" as const;
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
  frame_encoding: typeof GOAL_LIVE_FRAME_ENCODING;
  frame_id: string;
  phase: GoalLiveFramePhase;
  sequence: number;
  width: typeof GOAL_LIVE_FRAME_WIDTH;
  height: typeof GOAL_LIVE_FRAME_HEIGHT;
  receipt_start_index: number;
  receipt_end_index: number;
  event_indices: number[];
  event_count: number;
  delta_bytes_base64: string;
  delta_sha256: string;
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

function decodeBase64(value: string, label: string): Uint8Array {
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length % 4 === 1) {
    throw new Error(`goal live-session ${label} encoding is invalid`);
  }
  const bytes = Buffer.from(value, "base64");
  if (bytes.toString("base64") !== value) {
    throw new Error(`goal live-session ${label} encoding is noncanonical`);
  }
  return bytes;
}

interface VirtualTerminal {
  cells: string[][];
  row: number;
  column: number;
  savedRow: number;
  savedColumn: number;
}

function createVirtualTerminal(): VirtualTerminal {
  return {
    cells: Array.from({ length: GOAL_LIVE_FRAME_HEIGHT }, () =>
      Array.from({ length: GOAL_LIVE_FRAME_WIDTH }, () => " ")),
    row: 0,
    column: 0,
    savedRow: 0,
    savedColumn: 0,
  };
}

function clampRow(value: number): number {
  return Math.max(0, Math.min(GOAL_LIVE_FRAME_HEIGHT - 1, value));
}

function clampColumn(value: number): number {
  return Math.max(0, Math.min(GOAL_LIVE_FRAME_WIDTH, value));
}

function clearTerminal(terminal: VirtualTerminal): void {
  for (const row of terminal.cells) row.fill(" ");
  terminal.row = 0;
  terminal.column = 0;
}

function eraseLine(terminal: VirtualTerminal, mode: number): void {
  const start = mode === 1 ? 0 : terminal.column;
  const end = mode === 0 ? GOAL_LIVE_FRAME_WIDTH : terminal.column + 1;
  for (let index = start; index < end && index < GOAL_LIVE_FRAME_WIDTH; index += 1) {
    terminal.cells[terminal.row]![index] = " ";
  }
}

function csiParams(raw: string): number[] {
  const normalized = raw.replace(/^\?/, "");
  if (!normalized) return [];
  return normalized.split(";").map((value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  });
}

/** Apply the ANSI delta emitted by the real Ink reconciler to a fixed grid. */
export function applyGoalLiveAnsiDelta(terminal: VirtualTerminal, bytes: Uint8Array): void {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  for (let index = 0; index < text.length;) {
    const character = text[index]!;
    if (character === "\u001b") {
      const next = text[index + 1];
      if (next === "[") {
        let end = index + 2;
        while (end < text.length && !(text.charCodeAt(end) >= 0x40 && text.charCodeAt(end) <= 0x7e)) end += 1;
        if (end >= text.length) throw new Error("goal live-session ANSI delta is truncated");
        const params = csiParams(text.slice(index + 2, end));
        const final = text[end]!;
        const amount = params[0] || 1;
        if (final === "H" || final === "f") {
          terminal.row = clampRow((params[0] || 1) - 1);
          terminal.column = clampColumn((params[1] || 1) - 1);
        } else if (final === "G") {
          terminal.column = clampColumn((params[0] || 1) - 1);
        } else if (final === "d") {
          terminal.row = clampRow((params[0] || 1) - 1);
        } else if (final === "A") terminal.row = clampRow(terminal.row - amount);
        else if (final === "B") terminal.row = clampRow(terminal.row + amount);
        else if (final === "C") terminal.column = clampColumn(terminal.column + amount);
        else if (final === "D") terminal.column = clampColumn(terminal.column - amount);
        else if (final === "J" && (params[0] === 2 || params[0] === 3)) clearTerminal(terminal);
        else if (final === "K") eraseLine(terminal, params[0] || 0);
        else if (final === "s") {
          terminal.savedRow = terminal.row;
          terminal.savedColumn = terminal.column;
        } else if (final === "u") {
          terminal.row = terminal.savedRow;
          terminal.column = terminal.savedColumn;
        }
        index = end + 1;
        continue;
      }
      if (next === "]") {
        let end = index + 2;
        while (end < text.length && text[end] !== "\u0007" && !(text[end] === "\u001b" && text[end + 1] === "\\")) end += 1;
        index = text[end] === "\u001b" ? end + 2 : end + 1;
        continue;
      }
      index += 2;
      continue;
    }
    if (character === "\r") terminal.column = 0;
    else if (character === "\n") terminal.row = clampRow(terminal.row + 1);
    else if (character === "\b") terminal.column = clampColumn(terminal.column - 1);
    else if (character === "\t") terminal.column = clampColumn(terminal.column + (4 - (terminal.column % 4)));
    else if (character >= " ") {
      if (terminal.row < GOAL_LIVE_FRAME_HEIGHT && terminal.column < GOAL_LIVE_FRAME_WIDTH) {
        terminal.cells[terminal.row]![terminal.column] = character;
      }
      terminal.column = clampColumn(terminal.column + 1);
    }
    index += 1;
  }
}

function terminalSnapshotBytes(terminal: VirtualTerminal): Uint8Array {
  return Buffer.from(terminal.cells.map((row) => row.join("")).join("\n") + "\n", "utf8");
}

function validateSnapshotBytes(frame: GoalLiveFrameCapture, snapshot: Uint8Array): void {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(snapshot);
  const lines = text.split("\n");
  if (lines.length !== GOAL_LIVE_FRAME_HEIGHT + 1 || lines.at(-1) !== "" ||
      lines.slice(0, -1).some((line) => line.length !== GOAL_LIVE_FRAME_WIDTH || /[\r\u0000-\u001f\u007f]/.test(line))) {
    throw new Error("goal live-session frame snapshot dimensions/content are invalid");
  }
  if (frame.width !== GOAL_LIVE_FRAME_WIDTH || frame.height !== GOAL_LIVE_FRAME_HEIGHT) {
    throw new Error("goal live-session frame dimensions are invalid");
  }
}

export function validateGoalLiveFrameCapture(
  frame: GoalLiveFrameCapture,
  events: GoalLiveFrameEvent[],
  authority: GoalLiveFrameAuthority,
): void {
  if (frame.frame_encoding !== GOAL_LIVE_FRAME_ENCODING || frame.event_count <= 0 || frame.event_count !== frame.event_indices.length
    || frame.event_indices.some((index) => !Number.isInteger(index) || index < 0 || index >= events.length)
    || frame.receipt_start_index !== Math.min(...frame.event_indices)
    || frame.receipt_end_index !== Math.max(...frame.event_indices)
    || frame.sequence <= 0) {
    throw new Error("goal live-session frame range/encoding is invalid");
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
  const delta = decodeBase64(frame.delta_bytes_base64, "delta");
  const snapshot = decodeBase64(frame.frame_bytes_base64, "snapshot");
  if (frame.delta_sha256 !== sha256(delta) || frame.frame_sha256 !== sha256(snapshot)) {
    throw new Error("goal live-session frame bytes do not match their hashes");
  }
  validateSnapshotBytes(frame, snapshot);
}

export function validateGoalLiveFrameCaptures(
  frames: GoalLiveFrameCapture[],
  events: GoalLiveFrameEvent[],
  authority: GoalLiveFrameAuthority,
): void {
  const expectedPhases: GoalLiveFramePhase[] = ["preemption", "continuations", "completion"];
  if (frames.length !== expectedPhases.length) throw new Error("goal live-session frame count is invalid");
  const terminal = createVirtualTerminal();
  frames.forEach((frame, index) => {
    validateGoalLiveFrameCapture(frame, events, authority);
    if (frame.phase !== expectedPhases[index] || frame.sequence !== index + 1) {
      throw new Error("goal live-session renderer frame phases are incomplete or out of order");
    }
    applyGoalLiveAnsiDelta(terminal, decodeBase64(frame.delta_bytes_base64, "delta"));
    const snapshot = terminalSnapshotBytes(terminal);
    if (Buffer.from(frame.frame_bytes_base64, "base64").compare(Buffer.from(snapshot)) !== 0) {
      throw new Error("goal live-session frame snapshot does not reconstruct from renderer delta");
    }
  });
}

export interface RenderedGoalLiveFrameInput {
  frame_id: string;
  phase: GoalLiveFramePhase;
  sequence: number;
  event_indices: number[];
  bytes: Uint8Array;
}

/** Converts actual Ink ANSI deltas into complete fixed-size terminal snapshots. */
export function captureRenderedGoalLiveFrames(
  rendered: RenderedGoalLiveFrameInput[],
  events: GoalLiveFrameEvent[],
  authority: GoalLiveFrameAuthority,
): GoalLiveFrameCapture[] {
  if (authority.source_id !== GOAL_LIVE_RENDERER_SOURCE_ID || rendered.length !== 3) {
    throw new Error("goal live-session renderer capture authority is incomplete");
  }
  const terminal = createVirtualTerminal();
  const frames = rendered.map((input) => {
    if (input.bytes.length === 0 || input.event_indices.length === 0) {
      throw new Error("goal live-session renderer emitted an empty frame");
    }
    applyGoalLiveAnsiDelta(terminal, input.bytes);
    const snapshot = terminalSnapshotBytes(terminal);
    return {
      frame_id: input.frame_id,
      frame_encoding: GOAL_LIVE_FRAME_ENCODING,
      phase: input.phase,
      sequence: input.sequence,
      width: GOAL_LIVE_FRAME_WIDTH,
      height: GOAL_LIVE_FRAME_HEIGHT,
      receipt_start_index: Math.min(...input.event_indices),
      receipt_end_index: Math.max(...input.event_indices),
      event_indices: input.event_indices,
      event_count: input.event_indices.length,
      delta_bytes_base64: Buffer.from(input.bytes).toString("base64"),
      delta_sha256: sha256(input.bytes),
      frame_bytes_base64: Buffer.from(snapshot).toString("base64"),
      frame_sha256: sha256(snapshot),
      renderer: "ember-ink-reconciler" as const,
      source_binding: {
        id: GOAL_LIVE_RENDERER_SOURCE_ID,
        sha256: authority.source_sha256,
        executable_sha256: authority.executable_sha256,
      },
    } satisfies GoalLiveFrameCapture;
  });
  validateGoalLiveFrameCaptures(frames, events, authority);
  return frames;
}
