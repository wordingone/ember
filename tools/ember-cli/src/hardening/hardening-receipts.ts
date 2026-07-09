// hardening/hardening-receipts.ts — issue #159: one JSONL receipt row per battle-test harness
// cell, so a CI run's per-cell pass/fail is a checkable artifact rather than lost in log output.
// Same append-only, best-effort discipline as the rest of this codebase's receipt writers
// (services/activity-feed.ts's ledger, model-lifecycle.ts's kill receipts): a receipt-write
// failure must never fail the test it's recording.

import path from "node:path";
import { appendLineWithDirs } from "../utils/file-operations.ts";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";

export interface HardeningReceipt {
  /** Which #159 harness item this cell belongs to, e.g. "boot-matrix", "tool-injection". */
  suite: string;
  /** The specific cell/case name, e.g. "bad-binary-path", "Bash: forced throw". */
  cell: string;
  outcome: "pass" | "fail";
  /** Free-form detail (assertion summary, error message on failure). */
  detail?: string;
}

export function getDefaultHardeningReceiptsPath(): string {
  const repoRoot = resolveEmberRepoRootOrCwd({}, "[hardening-receipts]");
  return path.join(repoRoot, "tools", "ember-cli", "state", "hardening-receipts.jsonl");
}

/** Appends one receipt row. Best-effort: a write failure is swallowed, never thrown, so a
 *  receipts-path problem can never turn a real pass into a reported failure (or vice versa). */
export async function writeHardeningReceipt(
  entry: HardeningReceipt,
  receiptsPath: string = getDefaultHardeningReceiptsPath(),
): Promise<void> {
  const row = { ts: new Date().toISOString(), ...entry };
  await appendLineWithDirs(receiptsPath, JSON.stringify(row)).catch(() => {});
}
