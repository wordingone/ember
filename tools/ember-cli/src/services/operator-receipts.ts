// operator-receipts.ts — JSONL receipt writer for the operator input channel
// (ember issue #165 / #154 §2: "every session logs prompt/reply/next-action to
// receipts/operator-sessions/<UTC>.jsonl").
//
// Fail-open by design: a receipts-directory problem (missing repo root, readonly
// disk, permissions) must never crash or delay the CLI. Every write is wrapped;
// failures are swallowed after a best-effort console warning.

import fs from "node:fs";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";

export type OperatorReceiptEvent = "pipe_connected" | "prompt_injected" | "response_rendered";

export interface OperatorReceiptRow {
  ts: string;
  role: "system";
  event: OperatorReceiptEvent;
  detail?: string;
}

/** Compact UTC stamp matching the repo's existing operator-session file naming
 *  (e.g. 20260705T160101Z) — see receipts/operator-sessions/session-*.jsonl. */
export function compactUtcStamp(now: Date = new Date()): string {
  return now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

/** Repo root, resolved via the shared repo-root anchor (utils/repo-root.ts) — never via
 *  import.meta.url, which resolves to a virtual bunfs path under `bun build --compile`
 *  and walks to the drive root instead of the repo (issue #172: this is exactly how the
 *  2026-07-05 operator-session receipt landed at B:/receipts instead of the real repo,
 *  and GOAL.md lookups failed for the same reason). Fails OPEN here (never throws) per
 *  this module's own contract below — resolution failure degrades to process.cwd() with
 *  a loud warning, it never crashes the CLI and never silently returns a wrong root. */
export function defaultRepoRoot(): string {
  return resolveEmberRepoRootOrCwd({}, "[operator-receipts]");
}

export interface OperatorReceiptWriter {
  readonly filePath: string;
  append: (event: OperatorReceiptEvent, detail?: string) => void;
}

export interface CreateOperatorReceiptWriterOptions {
  /** Overrides the resolved repo root — tests point this at a scratch directory. */
  repoRoot?: string;
  /** Overrides "now" for the session filename's timestamp. */
  bootTime?: Date;
}

/**
 * Creates a receipt writer bound to a single session file
 * (receipts/operator-sessions/session-<UTC>.jsonl), fixed at the boot time this
 * writer was created. Directory creation and every append are best-effort and
 * never throw.
 */
export function createOperatorReceiptWriter(
  options: CreateOperatorReceiptWriterOptions = {},
): OperatorReceiptWriter {
  const repoRoot = options.repoRoot ?? defaultRepoRoot();
  const stamp    = compactUtcStamp(options.bootTime ?? new Date());
  const dir      = path.join(repoRoot, "receipts", "operator-sessions");
  const filePath = path.join(dir, `session-${stamp}.jsonl`);

  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (err) {
    console.warn(
      `[operator-receipts] could not create ${dir}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    filePath,
    append(event, detail) {
      const row: OperatorReceiptRow = { ts: new Date().toISOString(), role: "system", event };
      if (detail !== undefined) row.detail = detail;
      try {
        fs.appendFileSync(filePath, JSON.stringify(row) + "\n", "utf8");
      } catch (err) {
        console.warn(
          `[operator-receipts] append failed: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
  };
}
