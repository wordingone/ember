// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/scheduler.ts — fires scheduled prompts while the REPL is idle.
//
// Two sources feed one ticker:
//   * cron jobs created by the CronCreate tool (tools/schedule-cron.ts), and
//   * /loop jobs: `/loop <interval> <prompt>` runs the prompt now and again every interval.
//
// The ticker only fires when `isIdle()` is true (no turn running, nothing typed), and at
// most one prompt per tick, so a due job never interrupts the operator or a running turn.
// A job that came due while the TUI was busy fires once, late, never as a burst.
// Esc stops every /loop (cancelAllLoops).

import { takeNextDueCronJob } from "../tools/schedule-cron.ts";

export const MIN_LOOP_INTERVAL_MS = 5_000;
export const DEFAULT_TICK_MS = 1_000;

// ---------------------------------------------------------------------------
// Intervals
// ---------------------------------------------------------------------------

const UNIT_MS: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000 };

/** "30s", "5m", "2h", "1d" -> ms; null when it is not an interval. */
export function parseInterval(text: string): number | null {
  const m = /^(\d+(?:\.\d+)?)\s*([smhd])$/i.exec(text.trim());
  if (!m) return null;
  const ms = Math.round(parseFloat(m[1]!) * UNIT_MS[m[2]!.toLowerCase()]!);
  return ms > 0 ? ms : null;
}

export function formatInterval(ms: number): string {
  for (const [unit, size] of [["d", 86_400_000], ["h", 3_600_000], ["m", 60_000], ["s", 1000]] as const) {
    if (ms % size === 0) return `${ms / size}${unit}`;
  }
  return `${ms}ms`;
}

// ---------------------------------------------------------------------------
// /loop jobs
// ---------------------------------------------------------------------------

export interface LoopJob {
  id: number;
  intervalMs: number;
  prompt: string;
  nextFireAt: number;
  /** Runs so far, counting the immediate first run. */
  runs: number;
}

const loops = new Map<number, LoopJob>();
let loopSeq = 0;

/** Registers a loop whose first run the caller starts now; the next one is due in one interval. */
export function startLoop(intervalMs: number, prompt: string, now: number = Date.now()): LoopJob {
  const job: LoopJob = { id: ++loopSeq, intervalMs, prompt, nextFireAt: now + intervalMs, runs: 1 };
  loops.set(job.id, job);
  return job;
}

export function listLoops(): LoopJob[] {
  return [...loops.values()];
}

export function hasActiveLoops(): boolean {
  return loops.size > 0;
}

/** Stops every loop; returns how many were running. */
export function cancelAllLoops(): number {
  const n = loops.size;
  loops.clear();
  return n;
}

function takeNextDueLoop(now: number): LoopJob | null {
  for (const job of loops.values()) {
    if (job.nextFireAt > now) continue;
    job.nextFireAt = now + job.intervalMs;
    job.runs += 1;
    return job;
  }
  return null;
}

export function _resetSchedulerForTests(): void {
  loops.clear();
  loopSeq = 0;
}

// ---------------------------------------------------------------------------
// Ticker
// ---------------------------------------------------------------------------

export interface DuePrompt {
  source: "cron" | "loop";
  id: string;
  prompt: string;
}

/** The next due prompt (cron first, then loops), consumed; null when nothing is due. */
export function takeNextDuePrompt(now: number): DuePrompt | null {
  const cron = takeNextDueCronJob(now);
  if (cron) return { source: "cron", id: cron.id, prompt: cron.prompt };
  const loop = takeNextDueLoop(now);
  if (loop) return { source: "loop", id: `loop_${loop.id}`, prompt: loop.prompt };
  return null;
}

export interface SchedulerTickerOptions {
  /** True when a prompt may start now (no turn running, nothing typed). */
  isIdle: () => boolean;
  /** Starts a model turn with the prompt. */
  fire: (due: DuePrompt) => void;
  now?: () => number;
  tickMs?: number;
}

export class SchedulerTicker {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(private readonly opts: SchedulerTickerOptions) {}

  /** One tick: fires the next due prompt when idle. Returns what fired, if anything. */
  tick(): DuePrompt | null {
    if (!this.opts.isIdle()) return null; // not idle: nothing is consumed, it stays due
    const due = takeNextDuePrompt((this.opts.now ?? Date.now)());
    if (!due) return null;
    try {
      this.opts.fire(due);
    } catch {
      // a failing fire must not stop the ticker
    }
    return due;
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(), this.opts.tickMs ?? DEFAULT_TICK_MS);
    this.timer.unref?.();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
