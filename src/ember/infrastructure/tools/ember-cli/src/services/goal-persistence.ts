// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/goal-persistence.ts — file-backed GoalStorePersistence (ember issue
// #211, the current "Selection and persistence" section: "Goal persisted in
// the session state store"). One JSON file
// per session under <emberStateRoot>/goals/<sessionId>.json. Fails OPEN on
// read (a corrupt/missing file behaves as "no goal", never a crash) but
// SURFACES write failures via console.warn so a silently-lost goal record
// isn't mistaken for "no goal was ever set" — same disclose-don't-hide
// discipline as operator-receipts.ts / goal-receipts.ts, applied to the
// record itself rather than just its receipt trail.

import fs from "node:fs";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { emberStatePath } from "../utils/ember-state-root.ts";
import type { GoalRecord, GoalStorePersistence } from "../core/goal-store.ts";

export interface CreateFileGoalPersistenceOptions {
  /** Overrides the resolved repo root — tests point this at a scratch directory. */
  repoRoot?: string;
  sessionId: string;
}

export function goalStateFilePath(repoRoot: string, sessionId: string): string {
  return emberStatePath(repoRoot, "goals", `${sessionId}.json`);
}

export function createFileGoalPersistence(
  options: CreateFileGoalPersistenceOptions,
): GoalStorePersistence {
  const repoRoot = options.repoRoot ?? resolveEmberRepoRootOrCwd({}, "[goal-persistence]");
  const filePath = goalStateFilePath(repoRoot, options.sessionId);

  return {
    read(): GoalRecord | null {
      try {
        if (!fs.existsSync(filePath)) return null;
        const raw = fs.readFileSync(filePath, "utf8");
        if (raw.trim().length === 0) return null;
        return JSON.parse(raw) as GoalRecord;
      } catch (err) {
        console.warn(
          `[goal-persistence] read failed, treating as no goal: ${err instanceof Error ? err.message : String(err)}`,
        );
        return null;
      }
    },
    write(record: GoalRecord | null): void {
      try {
        fs.mkdirSync(path.dirname(filePath), { recursive: true });
        if (record === null) {
          if (fs.existsSync(filePath)) fs.rmSync(filePath, { force: true });
          return;
        }
        fs.writeFileSync(filePath, JSON.stringify(record, null, 2), "utf8");
      } catch (err) {
        console.warn(
          `[goal-persistence] write failed: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
  };
}
