// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/server-reaper.ts -- the out-of-process half of the model-server lease (#2378).
//
// A hard kill of ember (Task Manager, taskkill /f, a native crash, or a console window closed
// before the runtime delivers its handlers) runs no exit handler, so in-process cleanup alone can
// strand the server on the GPU.  The reaper is a tiny detached process that outlives ember: every
// ~2 s it drops dead holders from the lease, and when none is left it stops the verified server and
// deletes the lease.  It carries no state of its own; the lease file is the state, so a lost reaper
// is simply replaced by the next ember that attaches.
//
// A Windows job object with KILL_ON_JOB_CLOSE was considered and rejected: it fires when the
// assigning process dies, so with two ember instances sharing one server the FIRST to exit would
// kill it.  "Last holder out" needs the holders list this module reads.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { healLog } from "./server-supervisor.ts";
import { createWin32ProcessOps, type ProcessOps } from "./process-ops.ts";
import {
  defaultLeaseDir, LeaseStore, makeStopReceiptSink, ServerLeases,
  type HolderRecord,
} from "./server-lease.ts";

/** Hidden subcommand for a compiled binary, where the reaper script is not a file on disk. */
export const REAPER_SUBCOMMAND = "__ember-server-reaper";

export const REAPER_POLL_MS = 2000;

/** How to start the reaper: the script beside this module when it exists on disk (bun run), else
 *  this executable with the hidden subcommand (compiled binary). */
export function reaperCommand(
  port: number,
  leaseDir: string,
  opts: { execPath?: string; scriptPath?: string | null } = {},
): { command: string; args: string[] } {
  const execPath = opts.execPath ?? process.execPath;
  const scriptPath = opts.scriptPath === undefined ? defaultReaperScript() : opts.scriptPath;
  return scriptPath
    ? { command: execPath, args: [scriptPath, String(port), leaseDir] }
    : { command: execPath, args: [REAPER_SUBCOMMAND, String(port), leaseDir] };
}

function defaultReaperScript(): string | null {
  try {
    const p = fileURLToPath(new URL("./server-reaper-main.ts", import.meta.url));
    return existsSync(p) ? p : null;
  } catch {
    return null;
  }
}

/** Start the detached, windowless reaper and return its identity (null: could not start). */
export function spawnReaperProcess(ops: ProcessOps, port: number, leaseDir: string): HolderRecord | null {
  const { command, args } = reaperCommand(port, leaseDir);
  const child = spawn(command, args, {
    detached: true,       // no console: the window closing must not take the reaper with it
    windowsHide: true,
    stdio: "ignore",
    env: { ...process.env, EMBER_SERVER_LEASE_DIR: leaseDir },
  });
  child.on("error", (e) => healLog(`lease: reaper failed to start: ${String(e)}`));
  child.unref();
  if (!child.pid) return null;
  const id = ops.identify(child.pid);
  return id ? { pid: id.pid, startTime: id.startTime } : null;
}

/** The production lease manager, or null where this platform cannot provide one (the caller then
 *  keeps the previous exit behavior). */
export function createProductionServerLeases(
  opts: { env?: Record<string, string | undefined>; ops?: ProcessOps | null; store?: LeaseStore } = {},
): ServerLeases | null {
  const env = opts.env ?? process.env;
  const ops = opts.ops === undefined ? createWin32ProcessOps() : opts.ops;
  if (!ops) return null;
  const store = opts.store ?? new LeaseStore(defaultLeaseDir(env));
  return new ServerLeases({
    ops,
    store,
    receipt: makeStopReceiptSink(store, env),
    log: (line) => healLog(`lease: ${line}`),
    spawnReaper: (port) => spawnReaperProcess(ops, port, store.dir),
  });
}

export interface ReaperLoopOptions {
  port: number;
  leases: ServerLeases;
  me?: HolderRecord;
  intervalMs?: number;
  sleep?: (ms: number) => Promise<void>;
  /** Consecutive failures after which the reaper gives up (a persistent fault must not spin forever). */
  maxErrors?: number;
}

/** Poll until the lease is settled.  Resolves when the lease is gone (server stopped or already
 *  dead), another reaper took over, or the loop keeps failing. */
export async function runReaper(o: ReaperLoopOptions): Promise<void> {
  const sleep = o.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const maxErrors = o.maxErrors ?? 5;
  let errors = 0;
  for (;;) {
    try {
      if (o.leases.reapOnce(o.port, o.me) === "done") return;
      errors = 0;
    } catch (e) {
      healLog(`lease: reaper tick failed: ${String(e)}`);
      if (++errors >= maxErrors) return;
    }
    await sleep(o.intervalMs ?? REAPER_POLL_MS);
  }
}

/** Entry for both the script and the compiled subcommand. */
export async function reaperMain(port: number, leaseDir: string): Promise<void> {
  if (!Number.isInteger(port) || port <= 0 || !leaseDir) return;
  const ops = createWin32ProcessOps();
  if (!ops) return;
  const store = new LeaseStore(leaseDir);
  const leases = new ServerLeases({
    ops,
    store,
    receipt: makeStopReceiptSink(store, process.env),
    log: (line) => { try { store.appendRow("reaper.log", { ts: new Date().toISOString(), port, line }); } catch { /* best effort */ } },
  });
  const self = ops.self();
  await runReaper({ port, leases, me: self ? { pid: self.pid, startTime: self.startTime } : undefined });
}
