// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/run-progress-scanner.ts — issue #447: "active runs" telemetry, sourced from the
// newest `*progress*.jsonl` file under the repo's receipts/ tree (the real on-disk convention,
// e.g. receipts/ember-c-scale/w1-live-progress-20260707T135344Z.jsonl -- one line per training
// step: {"step":1800,"tokens_so_far":...,"eval_loss":4.9375,"target_eval_loss":...,"ts":"..."}).
//
// This is a file-presence/freshness signal, not a self-report: a training loop can only make
// this file's mtime (and its last line's own `ts`) advance by actually writing to it. A dead or
// hung run's progress file simply stops advancing -- the same "freshness IS the fact" contract
// services/liveness-heartbeat.ts already uses for cockpit-process liveness.
//
// Acquisition only (scan + read + parse) -- formatting the phase line for display lives in the
// renderer (core/live-telemetry-render.ts), matching gpu-state-poller.ts's acquire/render split.

import fs from "node:fs/promises";
import path from "node:path";
import { formatReceiptAge } from "../core/receipt-age.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One parsed progress-line's known fields. All optional -- a line missing/mistyping a field
 *  degrades to that field being absent, never throws and never fabricates a 0/placeholder. */
export interface ProgressPhase {
  step?: number;
  tokensSoFar?: number;
  evalLoss?: number;
  targetEvalLoss?: number;
  /** The line's own `ts` field verbatim (compact-ISO8601 in observed files, e.g.
   *  "20260707T141940Z") -- core/receipt-age.ts's formatReceiptAge/isReceiptStale already parse
   *  this exact format, so callers feed it straight through rather than re-deriving age math. */
  ts?: string;
}

export interface ActiveRunSnapshot {
  /** Path to the newest progress file found, relative to receiptsRoot (safe to display -- no
   *  absolute machine path leaks into the UI). */
  relativePath: string;
  /** File mtime in epoch ms -- the fallback freshness signal when the line itself carries no
   *  usable `ts` (or none is parseable). */
  mtimeMs: number;
  phase: ProgressPhase;
}

// ---------------------------------------------------------------------------
// Directory walk (bounded depth)
// ---------------------------------------------------------------------------

/** Real on-disk convention is `receipts/<lane>/<run>-progress-<ts>.jsonl` -- two levels deep.
 *  Bounded well past that (not just exactly 2) so a differently-nested lane still resolves,
 *  while still refusing to walk the entire repository on a pathological tree. */
const MAX_WALK_DEPTH = 4;

function isProgressFile(name: string): boolean {
  return name.toLowerCase().includes("progress") && name.endsWith(".jsonl");
}

/** Recursively finds the newest-mtime file whose name matches isProgressFile under `root`,
 *  bounded to MAX_WALK_DEPTH. Fails open: an unreadable directory (permissions, race with a
 *  concurrent delete) is skipped, never thrown -- the walk simply continues with what it CAN
 *  read. Returns null when no matching file exists anywhere in the tree.
 */
export async function findNewestProgressFile(
  root: string,
): Promise<{ path: string; mtimeMs: number } | null> {
  let best: { path: string; mtimeMs: number } | null = null;

  async function walk(dir: string, depth: number): Promise<void> {
    if (depth > MAX_WALK_DEPTH) return;
    let entries: import("node:fs").Dirent[];
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      return; // unreadable dir -- skip, never throw
    }

    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(full, depth + 1);
      } else if (entry.isFile() && isProgressFile(entry.name)) {
        try {
          const st = await fs.stat(full);
          if (!best || st.mtimeMs > best.mtimeMs) {
            best = { path: full, mtimeMs: st.mtimeMs };
          }
        } catch {
          // Race: file vanished between readdir and stat -- skip it.
        }
      }
    }
  }

  try {
    await walk(root, 0);
  } catch {
    return null; // root itself missing/unreadable
  }
  return best;
}

// ---------------------------------------------------------------------------
// Reading + parsing
// ---------------------------------------------------------------------------

/** Reads `filePath` and returns its last non-empty line, or null if the file is empty/missing.
 *  Never throws -- an unreadable file (deleted mid-poll, permission race) degrades to null. */
export async function readLastJsonlLine(filePath: string): Promise<string | null> {
  let content: string;
  try {
    content = await fs.readFile(filePath, "utf8");
  } catch {
    return null;
  }
  const lines = content.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  return lines.length > 0 ? lines[lines.length - 1]! : null;
}

/** Parses one progress-JSONL line into a ProgressPhase. Returns null only when the line isn't
 *  parseable JSON or isn't an object -- an object missing/mistyping individual fields still
 *  parses, just with those fields absent (never a thrown TypeError on `.step` of a wrong type). */
export function parseProgressLine(line: string): ProgressPhase | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const row = parsed as Record<string, unknown>;

  const phase: ProgressPhase = {};
  if (typeof row["step"] === "number") phase.step = row["step"];
  if (typeof row["tokens_so_far"] === "number") phase.tokensSoFar = row["tokens_so_far"];
  if (typeof row["eval_loss"] === "number") phase.evalLoss = row["eval_loss"];
  if (typeof row["target_eval_loss"] === "number") phase.targetEvalLoss = row["target_eval_loss"];
  if (typeof row["ts"] === "string") phase.ts = row["ts"];
  return phase;
}

// ---------------------------------------------------------------------------
// Combined poll
// ---------------------------------------------------------------------------

/**
 * Finds the newest progress file under `receiptsRoot`, reads its last line, and parses it.
 * Returns null when no progress file exists, or when the newest one's last line isn't
 * parseable -- both are legitimate "nothing to report" states, never fabricated.
 */
export async function pollActiveRun(receiptsRoot: string): Promise<ActiveRunSnapshot | null> {
  const found = await findNewestProgressFile(receiptsRoot);
  if (!found) return null;

  const line = await readLastJsonlLine(found.path);
  if (!line) return null;

  const phase = parseProgressLine(line);
  if (!phase) return null;

  return {
    relativePath: path.relative(receiptsRoot, found.path),
    mtimeMs: found.mtimeMs,
    phase,
  };
}

// ---------------------------------------------------------------------------
// Freshness + display formatting
// ---------------------------------------------------------------------------

/** How long since the progress file's last write before a run is no longer considered "active".
 *  Deliberately based on file mtime (always a valid number, no timestamp-parsing ambiguity) --
 *  NOT the line's own `ts` field, which could theoretically be absent/unparseable and this gate
 *  must degrade to "not fresh" under any doubt (a false "training-active" claim is the worse
 *  failure direction here, see gpu-state-poller.ts's classifyGpuActivity). 10 minutes is a
 *  judgment call: generous enough to cover normal inter-step gaps on a slow training loop,
 *  tight enough that a genuinely stalled/dead run reads as not-fresh within one poll cycle. */
export const ACTIVE_RUN_FRESHNESS_TTL_MS = 10 * 60 * 1000;

/** Whether `run`'s progress file was written recently enough to call the run "active" right now. */
export function isActiveRunFresh(run: ActiveRunSnapshot | null, nowMs: number = Date.now()): boolean {
  if (!run) return false;
  return nowMs - run.mtimeMs <= ACTIVE_RUN_FRESHNESS_TTL_MS;
}

/** Formats the active-run feed line, e.g. "run: ember-c-scale/w1-live-progress-... step 1800,
 *  eval_loss 4.9375 · 12s ago". Returns null when no progress file was found -- never a
 *  fabricated "no run" line where the caller can instead simply omit this row entirely. */
export function formatActiveRunLine(
  run: ActiveRunSnapshot | null,
  nowMs: number = Date.now(),
): { text: string } | null {
  if (!run) return null;

  const ageSource = run.phase.ts ?? new Date(run.mtimeMs).toISOString();
  const age = formatReceiptAge(ageSource, nowMs);
  // Lane name only (the file's parent directory), NOT the full path+filename -- a real 190-col
  // boot capture showed the full "<lane>/<long-timestamped-filename>" label collapsing to a bare
  // "run:…" the instant the panel narrowed to 100 cols (word-boundary clipping has nowhere to
  // break inside one long unbroken filename), which tells the operator nothing at exactly the
  // width where a compact glance matters most. The lane name is what identifies WHICH run this
  // is; the embedded timestamp in the filename is redundant with the `age` suffix anyway.
  // Split on either separator, not just the current platform's path.sep: findNewestProgressFile
  // always produces an OS-native-separated relativePath in practice, but this stays correct
  // regardless (defensive, not load-bearing on which convention actually produced the string).
  const segments = run.relativePath.split(/[\\/]/).filter((s) => s.length > 0);
  const label = segments.length > 1 ? segments[0]! : segments[0]!.replace(/\.jsonl$/i, "");

  const parts: string[] = [];
  if (run.phase.step != null) parts.push(`step ${run.phase.step}`);
  if (run.phase.evalLoss != null) parts.push(`eval_loss ${run.phase.evalLoss}`);
  const phaseStr = parts.length > 0 ? parts.join(", ") : "running";

  return { text: `run: ${label} ${phaseStr} \xB7 ${age}` };
}

// ---------------------------------------------------------------------------
// React polling hook
// ---------------------------------------------------------------------------

/** Poll cadence: a bounded recursive directory walk every tick, so this stays on the slow side
 *  like the other file-scanning pollers (board-ts-poller: 45s). 20s balances "an active run
 *  shows up promptly" against "never a per-second directory walk". */
export const DEFAULT_ACTIVE_RUN_POLL_INTERVAL_MS = 20_000;

import { useEffect, useState } from "react";

/** Polls for the newest active-run progress file at `intervalMs` cadence. Returns null until the
 *  first successful poll, or whenever no progress file is found -- the caller renders nothing
 *  in that case. Cleans up the interval on unmount. */
export function useActiveRunPoller(
  receiptsRoot: string,
  intervalMs: number = DEFAULT_ACTIVE_RUN_POLL_INTERVAL_MS,
): ActiveRunSnapshot | null {
  const [state, setState] = useState<ActiveRunSnapshot | null>(null);

  useEffect(() => {
    let active = true;

    const poll = async (): Promise<void> => {
      const result = await pollActiveRun(receiptsRoot);
      if (active) setState(result);
    };

    void poll();
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [receiptsRoot, intervalMs]);

  return state;
}
