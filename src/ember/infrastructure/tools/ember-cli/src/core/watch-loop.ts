// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/watch-loop.ts — the non-interactive `ember --watch [--interval N]` ambient observatory
// mode (gh issue #34, condition C-OBS), rebuilt against the real CLI entrypoint
// (entrypoints/process-entry.ts's dispatchFastPath) after the #405 cleanup removed the previous
// composer for having zero production callers (see core/watch-render.ts's header comment).
//
// Deliberately thin: every piece of rendering logic is borrowed from what commands/world-state.ts
// already uses for the /cockpit "monitor" turn -- core/ember-world-state.ts's
// buildEmberWorldState() (fresh snapshot, never cached -- this module never keeps a
// previous-cycle EmberWorldState around either) and core/monitor-render.ts's renderMonitorPanel()
// plus core/watch-render.ts's findNewestReceipts()/renderReceiptsTail(). This file's only new
// contribution is the LOOP: argument parsing (--interval, hostile-input fail-closed), a single
// testable refresh cycle, and the repeat/refresh-error-resilience/SIGINT lifecycle around it.
//
// Every I/O boundary (build/render/write/clock/sleep/signal registration) is an injected
// dependency so the loop and its SIGINT/error-resilience behavior are unit-testable without a
// real timer or a real terminal -- see core/watch-loop.test.ts.

import type { EmberWorldState } from "./ember-world-state.ts";
import { buildEmberWorldState } from "./ember-world-state.ts";
import { renderMonitorPanel } from "./monitor-render.ts";
import type { MonitorPanelOptions } from "./monitor-render.ts";
import { findNewestReceipts, renderReceiptsTail } from "./watch-render.ts";
import type { ReceiptStat } from "./watch-render.ts";

// ---------------------------------------------------------------------------
// parseWatchArgs — --watch / --interval detection, hostile-input fail-closed
// ---------------------------------------------------------------------------

export const DEFAULT_WATCH_INTERVAL_MS = 5000; // 5s -- matches the cadence commands/watch.ts's
// telemetry poll already uses elsewhere in this CLI, so the two "watch" surfaces feel consistent.
const MAX_INTERVAL_SECONDS = 86400; // 24h -- an "absurdly large" --interval is refused rather than
// silently accepted; a refresh loop that only fires once a day is not what the flag is for, and a
// caller who typed a stray extra zero deserves a named error, not a day-long silent hang.

export interface ParsedWatchArgs {
  /** Whether "--watch" appeared anywhere in argv at all. */
  enabled: boolean;
  intervalMs: number;
  /** Set when --interval was present but the value fails validation. The caller (dispatchFastPath)
   * always treats a non-undefined error as fail-CLOSED: refuse to start the loop, print this
   * message naming the argument, exit non-zero. `intervalMs` is still populated (the default) so
   * a caller that ignores the error for some reason never gets an undefined/NaN interval. */
  error?: string;
}

/** argv is the raw `process.argv` shape (argv[0]=runtime, argv[1]=script, argv[2..]=user args) --
 * same convention every other parse* helper in entrypoints/process-entry.ts uses. */
export function parseWatchArgs(argv: string[]): ParsedWatchArgs {
  const args = argv.slice(2);
  if (!args.includes("--watch")) {
    return { enabled: false, intervalMs: DEFAULT_WATCH_INTERVAL_MS };
  }

  let rawValue: string | undefined;
  let sawFlag = false;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i]!;
    if (arg === "--interval") {
      sawFlag = true;
      const next = args[i + 1];
      // A bare "-" prefix alone doesn't mean "this is another flag" -- a negative interval
      // ("-5") must reach the >0 validation below with its real value so the error message names
      // the actual offending number, not a fabricated "missing value". Only a non-numeric-looking
      // dash-prefixed token (e.g. "--foo", "-x") is treated as "no value supplied".
      const looksLikeValue = next !== undefined && (!next.startsWith("-") || /^-\d/.test(next));
      rawValue = looksLikeValue ? next : undefined;
      break;
    }
    if (arg.startsWith("--interval=")) {
      sawFlag = true;
      rawValue = arg.slice("--interval=".length);
      break;
    }
  }

  if (!sawFlag) {
    return { enabled: true, intervalMs: DEFAULT_WATCH_INTERVAL_MS };
  }
  if (rawValue === undefined || rawValue.trim() === "") {
    return {
      enabled: true,
      intervalMs: DEFAULT_WATCH_INTERVAL_MS,
      error: "--interval requires a value in seconds (e.g. --interval 5)",
    };
  }

  const seconds = Number(rawValue);
  if (!Number.isFinite(seconds)) {
    return {
      enabled: true,
      intervalMs: DEFAULT_WATCH_INTERVAL_MS,
      error: `--interval must be a finite number of seconds, got "${rawValue}"`,
    };
  }
  if (seconds <= 0) {
    return {
      enabled: true,
      intervalMs: DEFAULT_WATCH_INTERVAL_MS,
      error: `--interval must be greater than 0, got "${rawValue}"`,
    };
  }
  if (seconds > MAX_INTERVAL_SECONDS) {
    return {
      enabled: true,
      intervalMs: DEFAULT_WATCH_INTERVAL_MS,
      error: `--interval must be at most ${MAX_INTERVAL_SECONDS} seconds, got "${rawValue}"`,
    };
  }

  return { enabled: true, intervalMs: seconds * 1000 };
}

// ---------------------------------------------------------------------------
// runWatchCycle — one fresh-state refresh, error-resilient
// ---------------------------------------------------------------------------

export interface WatchCycleDeps {
  buildState: (opts?: { goalforgeRoot?: string }) => Promise<EmberWorldState>;
  findReceipts: (goalforgeRoot: string, count?: number) => Promise<ReceiptStat[]>;
  renderPanel: (state: EmberWorldState, opts: MonitorPanelOptions) => string[];
  renderTail: (receipts: ReceiptStat[], nowMs: number) => string[];
  goalforgeRoot: string;
  colorEnabled: boolean;
  width: number;
  now: () => number;
}

export type WatchCycleResult =
  | { ok: true; lines: string[] }
  | { ok: false; error: string };

/**
 * One MONITOR-equivalent refresh: builds a brand-new EmberWorldState (never reuses a prior
 * cycle's snapshot -- "fresh state per cycle" is the issue's own clause) and renders it through
 * the exact same panel + receipts-tail composition commands/world-state.ts's "monitor" turn uses.
 *
 * Never throws. A failed refresh (missing board receipt, unreadable goalforge tree, a transient
 * fs error) resolves to `{ ok: false, error }` instead of propagating -- the caller (runAmbientWatch)
 * is what turns that into "log it and try again next cycle" resilience; a single bad cycle must
 * never take the whole ambient loop down.
 */
export async function runWatchCycle(deps: WatchCycleDeps): Promise<WatchCycleResult> {
  try {
    const state = await deps.buildState({ goalforgeRoot: deps.goalforgeRoot });
    const receipts = await deps.findReceipts(deps.goalforgeRoot, 3);
    const nowMs = deps.now();
    const lines = [
      ...deps.renderPanel(state, {
        colorEnabled: deps.colorEnabled,
        width: deps.width,
        boardTs: state.monitor.boardTs,
        nowMs,
      }),
      ...deps.renderTail(receipts, nowMs),
    ];
    return { ok: true, lines };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, error: message };
  }
}

// ---------------------------------------------------------------------------
// runAmbientWatch — the repeat/SIGINT/error-resilience lifecycle around runWatchCycle
// ---------------------------------------------------------------------------

export interface RunAmbientWatchOptions {
  goalforgeRoot: string;
  intervalMs: number;
  colorEnabled: boolean;
  width: number;
  /** Writes one rendered cycle (or one error line) to the real output surface. Always called with
   * a single already-newline-terminated string. */
  write: (text: string) => void;
  now: () => number;
  /** Resolves after `ms`, or immediately if `signal` is already/becomes aborted -- this is what
   * lets a SIGINT mid-sleep end the loop promptly instead of waiting out the full interval. */
  sleep: (ms: number, signal: AbortSignal) => Promise<void>;
  /** Registers `handler` to run on the ambient-mode termination signal (real SIGINT in
   * production); returns an unregister function. Called exactly once per runAmbientWatch call, and
   * always unregistered in a `finally` so a test (or a future caller) never leaks a listener. */
  registerSigint: (handler: () => void) => () => void;
  buildState?: WatchCycleDeps["buildState"];
  findReceipts?: WatchCycleDeps["findReceipts"];
  renderPanel?: WatchCycleDeps["renderPanel"];
  renderTail?: WatchCycleDeps["renderTail"];
  /** Test-only escape hatch: stop after this many cycles even without a signal, so a test never
   * depends on a real (or even a fake-but-unbounded) infinite loop. Production callers never set
   * this -- the real lifecycle end is always SIGINT. */
  maxCycles?: number;
}

export interface RunAmbientWatchResult {
  cycles: number;
  stoppedBySignal: boolean;
}

export async function runAmbientWatch(opts: RunAmbientWatchOptions): Promise<RunAmbientWatchResult> {
  const controller = new AbortController();
  const unregister = opts.registerSigint(() => controller.abort());
  let cycles = 0;
  try {
    while (!controller.signal.aborted) {
      const result = await runWatchCycle({
        buildState: opts.buildState ?? buildEmberWorldState,
        findReceipts: opts.findReceipts ?? findNewestReceipts,
        renderPanel: opts.renderPanel ?? renderMonitorPanel,
        renderTail: opts.renderTail ?? renderReceiptsTail,
        goalforgeRoot: opts.goalforgeRoot,
        colorEnabled: opts.colorEnabled,
        width: opts.width,
        now: opts.now,
      });
      cycles++;
      if (result.ok) {
        opts.write(`${result.lines.join("\n")}\n`);
      } else {
        // Refresh-error resilience: a bad cycle is reported and the loop continues -- it is NEVER
        // allowed to crash the ambient process (the operator watching this pane should see a
        // named error, not a dead terminal).
        opts.write(`[watch] refresh error: ${result.error}\n`);
      }

      if (opts.maxCycles !== undefined && cycles >= opts.maxCycles) break;
      if (controller.signal.aborted) break;
      await opts.sleep(opts.intervalMs, controller.signal);
    }
  } finally {
    unregister();
  }
  return { cycles, stoppedBySignal: controller.signal.aborted };
}

// ---------------------------------------------------------------------------
// Real (production) IO primitives -- kept tiny and separate from the pure loop above so
// dispatchFastPath wires production behavior with zero extra logic of its own.
// ---------------------------------------------------------------------------

/** Resolves after `ms`, or immediately if `signal` is (or becomes) aborted. */
export function realSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Registers `handler` on the process's real SIGINT; returns the matching unregister. */
export function registerRealSigint(handler: () => void): () => void {
  process.on("SIGINT", handler);
  return () => {
    process.off("SIGINT", handler);
  };
}
