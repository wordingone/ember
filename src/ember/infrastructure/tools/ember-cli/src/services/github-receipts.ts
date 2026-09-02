// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/github-receipts.ts — JSONL receipt writer for GitHub write actions
// (ember issue #507 spec floor point 4: "every WRITE action appends a JSONL
// receipt row -- provenance discipline extends to the body's outward
// actions"). Same fail-open contract as operator-receipts.ts / goal-receipts.ts:
// a receipts-directory problem must never crash or delay the CLI. Every write
// is wrapped; failures are swallowed after a best-effort console warning.

import fs from "node:fs";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";

export const GITHUB_RECEIPT_ACTOR = "ember-cli-bot" as const;

export type GithubReceiptAction = "issue_create" | "issue_comment" | "pr_create";

export interface GithubReceiptRow {
  ts: string;
  actor: typeof GITHUB_RECEIPT_ACTOR;
  action: GithubReceiptAction;
  target: string;
  ok: boolean;
}

/** Same compact UTC stamp convention as operator-receipts.ts / goal-receipts.ts. */
export function compactUtcStamp(now: Date = new Date()): string {
  return now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

export function defaultRepoRoot(): string {
  return resolveEmberRepoRootOrCwd({}, "[github-receipts]");
}

export interface GithubReceiptWriter {
  readonly filePath: string;
  append: (action: GithubReceiptAction, target: string, ok: boolean) => void;
}

export interface CreateGithubReceiptWriterOptions {
  /** Overrides the resolved repo root — tests point this at a scratch directory. */
  repoRoot?: string;
  /** Overrides "now" for the writer's file-naming timestamp. */
  bootTime?: Date;
}

/**
 * Creates a receipt writer bound to a single file
 * (receipts/github-actions/actions-<UTC>.jsonl). Directory creation and every
 * append are best-effort and never throw.
 */
export function createGithubReceiptWriter(
  options: CreateGithubReceiptWriterOptions = {},
): GithubReceiptWriter {
  const repoRoot = options.repoRoot ?? defaultRepoRoot();
  const stamp = compactUtcStamp(options.bootTime ?? new Date());
  const dir = path.join(repoRoot, "receipts", "github-actions");
  const filePath = path.join(dir, `actions-${stamp}.jsonl`);

  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (err) {
    console.warn(
      `[github-receipts] could not create ${dir}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    filePath,
    append(action, target, ok) {
      const row: GithubReceiptRow = {
        ts: new Date().toISOString(),
        actor: GITHUB_RECEIPT_ACTOR,
        action,
        target,
        ok,
      };
      try {
        fs.appendFileSync(filePath, JSON.stringify(row) + "\n", "utf8");
      } catch (err) {
        console.warn(
          `[github-receipts] append failed: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
  };
}

// Singleton accessor -- the GitHub tool surface shares one writer per process
// (same lazy-singleton convention as goal-runtime's getGoalStore()), created
// on first use so every write action within a session lands in one file.
let singleton: GithubReceiptWriter | null = null;

export function getGithubReceiptWriter(): GithubReceiptWriter {
  if (!singleton) singleton = createGithubReceiptWriter();
  return singleton;
}

export function _resetGithubReceiptWriterForTests(): void {
  singleton = null;
}
