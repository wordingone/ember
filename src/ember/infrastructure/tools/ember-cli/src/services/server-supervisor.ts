// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/server-supervisor.ts -- self-healing for the managed llama-server
// of the OPEN_WEIGHTS / REFERENCE_ONLY seats.
//
// Two heals, both bounded and both logged to EMBER_HOME/heal.log:
//   1. startHealing: if the server dies before it is ready (typically CUDA
//      out-of-memory for the requested context), retry with a smaller context,
//      and as a last step without the vision projector, instead of exiting.
//   2. superviseServer: if a ready server dies mid-session, respawn it with the
//      settings that last worked. The query engine's transport retry (10
//      attempts, ~55 s of backoff on ECONNREFUSED) carries the in-flight request
//      across the restart. Restarts are capped per time window, so a server
//      that crashes on every load stops being respawned and the failure is
//      reported, never looped.

import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";

export interface HealSpawnOptions {
  nCtx: number;
  mmproj?: string;
}

export interface HealHandle {
  process: { pid?: number; once?: (event: string, listener: (...args: unknown[]) => void) => unknown };
  kill(): void;
}

export type ReadyOutcome = { kind: "ready" } | { kind: "exited"; code: number | null } | { kind: "timeout" };

export function healLog(line: string): void {
  try {
    const dir = getEmberConfigHomeDir();
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, "heal.log"), `${new Date().toISOString()} ${line}\n`);
  } catch {
    // healing must never fail because its log could not be written
  }
}

/** Context sizes to try after a failed load, largest first, never below 8192. */
export function contextFallbacks(nCtx: number): number[] {
  const out: number[] = [];
  for (let c = Math.floor(nCtx / 2); c >= 8192; c = Math.floor(c / 2)) out.push(c);
  if (nCtx > 8192 && !out.includes(8192)) out.push(8192);
  return out;
}

export interface StartHealingDeps<O extends HealSpawnOptions, H extends HealHandle> {
  spawn: (opts: O) => Promise<H>;
  waitReady: (handle: H) => Promise<ReadyOutcome>;
  log?: (line: string) => void;
  /** Reads the server log after a failed load; "runtime-too-old" stops the context
   * ladder, since no context size makes an unsupported model loadable. */
  classifyFailure?: () => "runtime-too-old" | "out-of-memory" | "other";
  /** True once the session is ending (#2378): no further load attempt may be spawned. */
  aborted?: () => boolean;
}

/** Spawn, and on an early exit step the context down (then drop mmproj) until
 * the server comes up.  Returns the handle and the options that worked, or the
 * last failure. */
export async function startHealing<O extends HealSpawnOptions, H extends HealHandle>(
  opts: O,
  deps: StartHealingDeps<O, H>,
): Promise<{ ok: true; handle: H; opts: O; outcome: ReadyOutcome } | { ok: false; outcome: ReadyOutcome; attempts: number }> {
  const log = deps.log ?? healLog;
  const attempts: O[] = [opts, ...contextFallbacks(opts.nCtx).map((nCtx) => ({ ...opts, nCtx }))];
  if (opts.mmproj) attempts.push({ ...opts, nCtx: Math.min(opts.nCtx, 16384), mmproj: undefined });
  let last: ReadyOutcome = { kind: "timeout" };
  for (let i = 0; i < attempts.length; i++) {
    const a = attempts[i]!;
    if (deps.aborted?.()) return { ok: false, outcome: last, attempts: i };
    if (i > 0) log(`heal: model server exited during load; retrying with context ${a.nCtx}${a.mmproj ? "" : " and no vision projector"}`);
    const handle = await deps.spawn(a);
    last = await deps.waitReady(handle);
    if (last.kind !== "exited") return { ok: true, handle, opts: a, outcome: last };
    if (deps.classifyFailure?.() === "runtime-too-old") {
      log("heal: this llama-server build cannot load the model (unsupported tensors/architecture); " +
        "run `ember pull` to fetch a current llama.cpp, or set EMBER_LLAMA_SERVER");
      return { ok: false, outcome: last, attempts: i + 1 };
    }
  }
  log(`heal: model server failed to load after ${attempts.length} attempts`);
  return { ok: false, outcome: last, attempts: attempts.length };
}

// Session shutdown (console close = SIGHUP/SIGBREAK, Ctrl+C, exit): the model server dies WITH the
// console, and its exit event can reach us before our own signal handler runs.  Every exit path
// calls markSessionShuttingDown() first; a server exit seen after that (or within exitGraceMs of
// an exit that is then followed by the mark) is a shutdown, not a crash: no restart, no log.
let sessionShuttingDown = false;
export function markSessionShuttingDown(): void { sessionShuttingDown = true; }
export function isSessionShuttingDown(): boolean { return sessionShuttingDown; }
export function resetSessionShutdownForTests(): void { sessionShuttingDown = false; }

export interface SuperviseDeps<O extends HealSpawnOptions, H extends HealHandle> {
  spawn: (opts: O) => Promise<H>;
  waitReady: (handle: H) => Promise<ReadyOutcome>;
  log?: (line: string) => void;
  now?: () => number;
  maxRestarts?: number;
  windowMs?: number;
  /** How long to wait after a server exit before deciding it was a crash, so a shutdown signal that
   *  is already on its way can claim it.  Default 0 (decide at once). */
  exitGraceMs?: number;
  /** Operator-facing lifecycle events (#2381): a restart that worked, or the circuit opening. */
  onEvent?: (e: SuperviseEvent) => void;
}

export type SuperviseEvent =
  | { kind: "restarted"; n: number; max: number }
  | { kind: "gave-up"; max: number; reason: "cap" | "restart-failed" };

export interface Supervisor<H> {
  current(): H;
  restarts(): number;
  /** Stop supervising and kill the current server (operator unload). */
  stop(): void;
  /** Stop supervising WITHOUT touching any server (exit, #2378): the server lease decides whether
   *  it is stopped, because another ember instance may still be using it.  After this no respawn
   *  or further load attempt happens, including one already in flight. */
  detach(): void;
}

export function superviseServer<O extends HealSpawnOptions, H extends HealHandle>(
  initial: H,
  opts: O,
  deps: SuperviseDeps<O, H>,
): Supervisor<H> {
  const log = deps.log ?? healLog;
  const now = deps.now ?? Date.now;
  const maxRestarts = deps.maxRestarts ?? 3;
  const windowMs = deps.windowMs ?? 10 * 60_000;
  let current = initial;
  let stopped = false;
  let detached = false;
  let total = 0;
  const recent: number[] = [];

  const watch = (h: H): void => {
    h.process.once?.("exit", (code: unknown) => {
      if (stopped || h !== current || sessionShuttingDown) return;
      const grace = deps.exitGraceMs ?? 0;
      if (grace > 0) {
        const timer = setTimeout(() => onExit(h, code), grace);
        (timer as { unref?: () => void }).unref?.();
        return;
      }
      onExit(h, code);
    });
  };

  const onExit = (h: H, code: unknown): void => {
    {
      if (stopped || h !== current || sessionShuttingDown) return;
      const t = now();
      while (recent.length && t - recent[0]! > windowMs) recent.shift();
      if (recent.length >= maxRestarts) {
        log(`heal: model server exited (code ${String(code)}); ${maxRestarts} restarts in ${windowMs / 60_000} min, giving up`);
        deps.onEvent?.({ kind: "gave-up", max: maxRestarts, reason: "cap" });
        return;
      }
      recent.push(t);
      total++;
      log(`heal: model server exited unexpectedly (code ${String(code)}); restart ${recent.length}/${maxRestarts}`);
      void (async () => {
        const healed = await startHealing(opts, { spawn: deps.spawn, waitReady: deps.waitReady, log, aborted: () => stopped });
        if (stopped) { if (healed.ok && !detached) healed.handle.kill(); return; }
        if (healed.ok) {
          current = healed.handle;
          opts = healed.opts;
          log(`heal: model server back (context ${healed.opts.nCtx})`);
          deps.onEvent?.({ kind: "restarted", n: recent.length, max: maxRestarts });
          watch(current);
        } else {
          deps.onEvent?.({ kind: "gave-up", max: maxRestarts, reason: "restart-failed" });
        }
      })();
    }
  };
  watch(initial);

  return {
    current: () => current,
    restarts: () => total,
    stop: () => { stopped = true; current.kill(); },
    detach: () => { stopped = true; detached = true; },
  };
}
