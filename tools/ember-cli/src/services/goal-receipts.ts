// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/goal-receipts.ts — JSONL receipt writer for the goal organ (ember
// issue #211, the current "Continuation loop" and "Artifact binding" sections:
// "every transition and continuation fire ALSO
// appends to the receipt store -- the organ itself obeys receipts-only law").
//
// Same fail-open contract as operator-receipts.ts (issue #165/#154): a
// receipts-directory problem (missing repo root, readonly disk, permissions)
// must never crash or delay the CLI or the goal loop. Every write is wrapped;
// failures are swallowed after a best-effort console warning.

import fs from "node:fs";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import type { GoalTransitionEvent } from "../core/goal-store.ts";

export type GoalReceiptEvent =
  | "created"
  | "status_changed"
  | "objective_edited"
  | "usage_recorded"
  | "cleared"
  | "continuation_fired"
  | "continuation_skipped";

export interface GoalReceiptRow {
  ts: string;
  event: GoalReceiptEvent;
  goalId?: string;
  detail?: Record<string, unknown>;
}

/** Same compact UTC stamp convention as operator-receipts.ts. */
export function compactUtcStamp(now: Date = new Date()): string {
  return now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

export function defaultRepoRoot(): string {
  return resolveEmberRepoRootOrCwd({}, "[goal-receipts]");
}

export interface GoalReceiptWriter {
  readonly filePath: string;
  append: (event: GoalReceiptEvent, goalId?: string, detail?: Record<string, unknown>) => void;
}

export interface CreateGoalReceiptWriterOptions {
  /** Overrides the resolved repo root — tests point this at a scratch directory. */
  repoRoot?: string;
  /** Overrides "now" for the session filename's timestamp. */
  bootTime?: Date;
  /** Session id the receipts file is keyed to (one file per goal-bearing session,
   *  same convention as receipts/operator-sessions/session-<UTC>.jsonl). */
  sessionId?: string;
}

/**
 * Creates a receipt writer bound to a single session file
 * (receipts/goal-sessions/session-<UTC>.jsonl). Directory creation and every
 * append are best-effort and never throw.
 */
export function createGoalReceiptWriter(
  options: CreateGoalReceiptWriterOptions = {},
): GoalReceiptWriter {
  const repoRoot = options.repoRoot ?? defaultRepoRoot();
  const stamp = compactUtcStamp(options.bootTime ?? new Date());
  const dir = path.join(repoRoot, "receipts", "goal-sessions");
  const suffix = options.sessionId ? `-${options.sessionId}` : "";
  const filePath = path.join(dir, `session-${stamp}${suffix}.jsonl`);

  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (err) {
    console.warn(
      `[goal-receipts] could not create ${dir}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    filePath,
    append(event, goalId, detail) {
      const row: GoalReceiptRow = { ts: new Date().toISOString(), event };
      if (goalId !== undefined) row.goalId = goalId;
      if (detail !== undefined) row.detail = detail;
      try {
        fs.appendFileSync(filePath, JSON.stringify(row) + "\n", "utf8");
      } catch (err) {
        console.warn(
          `[goal-receipts] append failed: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
  };
}

/**
 * Maps a GoalStore transition event to a receipted row -- the single seam
 * goal-runtime.ts wires as the store's onTransition callback, so EVERY
 * transition the state machine can produce is receipted uniformly (the current
 * "Continuation loop" section:
 * "every transition ... appends to the receipt store").
 */
export function receiptGoalTransition(writer: GoalReceiptWriter, event: GoalTransitionEvent): void {
  switch (event.kind) {
    case "created":
      writer.append("created", event.goal.goalId, {
        objective: event.goal.objective,
        tokenBudget: event.goal.tokenBudget,
      });
      return;
    case "status_changed":
      writer.append("status_changed", event.goal.goalId, {
        from: event.from,
        to: event.to,
        ...(event.reason !== undefined ? { reason: event.reason } : {}),
        ...(event.to === "Complete" && event.completionAudit !== undefined
          ? { completionAudit: event.completionAudit }
          : {}),
      });
      return;
    case "objective_edited":
      writer.append("objective_edited", event.goal.goalId, {
        previousObjective: event.previousObjective,
        objective: event.goal.objective,
      });
      return;
    case "usage_recorded":
      writer.append("usage_recorded", event.goal.goalId, { usage: event.goal.usage });
      return;
    case "cleared":
      writer.append("cleared", event.goalId);
      return;
  }
}
