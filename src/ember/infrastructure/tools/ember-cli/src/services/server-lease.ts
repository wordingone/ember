// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/server-lease.ts -- one model server, any number of ember instances (#2378).
//
// Closing ember must free the GPU whether ember spawned the model server or adopted one that
// was already answering.  The server is shared: two ember instances may use one llama-server,
// so the rule is "the LAST holder out stops it", and a crash must not strand it.
//
// A lease file per port records the server (PID + creation time + full command line, so a
// recycled PID is never mistaken for it) and the ember processes holding it.  Stopping is
// always by that verified identity, never by process name.  Four writers share one
// implementation of the decision (reapOnce):
//   - the exit/signal hooks of each ember instance (fast path, synchronous),
//   - a detached reaper process (backstop for hard kills, where no handler runs),
//   - startup recovery (a stale lease left by a crash),
//   - the supervisor respawn (recordSpawned replaces the server record).
//
// The lease lives in a machine-wide per-user directory, NOT in EMBER_HOME: ports are
// machine-wide, and testers/instances with different EMBER_HOMEs share one server.
//
// Everything here is synchronous: the exit paths cannot await.

import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { markSessionShuttingDown } from "./server-supervisor.ts";
import type { ProcessIdentity, ProcessOps, TerminateOutcome } from "./process-ops.ts";

/** llama-server listens here when started without --port. */
const LLAMA_SERVER_BUILTIN_PORT = 8080;

export interface ServerRecord {
  pid: number;
  startTime: string;
  cmdline: string;
  origin: "spawned" | "adopted";
  /** Executable ember spawned (spawned origin only); an adopted server is recognized as llama-server. */
  exe?: string;
}

export interface HolderRecord {
  pid: number;
  startTime: string;
}

export interface LeaseFile {
  version: 1;
  port: number;
  server: ServerRecord | null;
  holders: HolderRecord[];
  reaper: HolderRecord | null;
}

export interface StopReceipt {
  port: number;
  pid: number;
  cmdline: string;
  why: string;
}

// ---------------------------------------------------------------------------
// Command-line verification (the only way a server is ever selected)
// ---------------------------------------------------------------------------

/** Split a Windows command line into arguments (double quotes group, no escapes needed here). */
export function splitCommandLine(cmdline: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuote = false;
  let started = false;
  for (const ch of cmdline) {
    if (ch === '"') { inQuote = !inQuote; started = true; continue; }
    if (!inQuote && /\s/.test(ch)) {
      if (started) { out.push(cur); cur = ""; started = false; }
      continue;
    }
    cur += ch;
    started = true;
  }
  if (started) out.push(cur);
  return out;
}

function exeStem(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? path;
  return base.toLowerCase().replace(/\.exe$/, "");
}

/** True when `cmdline` is a llama-server serving `port`.  `exe`, when given (ember spawned it),
 *  must be the executable; otherwise the executable's name must contain "llama-server". */
export function verifyServerCmdline(cmdline: string, port: number, exe?: string): boolean {
  const tokens = splitCommandLine(cmdline);
  if (tokens.length === 0) return false;
  const stem = exeStem(tokens[0]!);
  if (exe ? stem !== exeStem(exe) : !stem.includes("llama-server")) return false;
  let sawPort = false;
  for (let i = 1; i < tokens.length; i++) {
    const t = tokens[i]!;
    if (t === "--port" || t.startsWith("--port=")) {
      sawPort = true;
      const value = t === "--port" ? tokens[i + 1] : t.slice("--port=".length);
      if (value === String(port)) return true;
    }
  }
  return !sawPort && port === LLAMA_SERVER_BUILTIN_PORT;
}

// ---------------------------------------------------------------------------
// Lease store: one JSON file per port, atomic writes, a short lock file
// ---------------------------------------------------------------------------

export function defaultLeaseDir(env: Record<string, string | undefined> = process.env): string {
  return env["EMBER_SERVER_LEASE_DIR"] || join(env["LOCALAPPDATA"] || tmpdir(), "ember", "server-leases");
}

function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

export class LeaseStore {
  constructor(
    readonly dir: string,
    private readonly sleep: (ms: number) => void = sleepSync,
  ) {}

  leasePath(port: number): string { return join(this.dir, `${port}.json`); }

  /** Cheap, lock-free: no lease file means nothing to settle (and nothing is created on disk). */
  exists(port: number): boolean { return existsSync(this.leasePath(port)); }
  private lockPath(port: number): string { return join(this.dir, `${port}.lock`); }

  read(port: number): LeaseFile | null {
    let raw: unknown;
    try { raw = JSON.parse(readFileSync(this.leasePath(port), "utf-8")); } catch { return null; }
    const o = raw as Partial<LeaseFile> | null;
    if (!o || o.version !== 1 || o.port !== port || !Array.isArray(o.holders)) return null;
    const holders = o.holders.filter((h): h is HolderRecord =>
      !!h && typeof h.pid === "number" && typeof h.startTime === "string");
    const s = o.server;
    const server = s && typeof s.pid === "number" && typeof s.startTime === "string" && typeof s.cmdline === "string"
      ? s : null;
    const r = o.reaper;
    const reaper = r && typeof r.pid === "number" && typeof r.startTime === "string" ? r : null;
    return { version: 1, port, server, holders, reaper };
  }

  write(port: number, lease: LeaseFile): void {
    mkdirSync(this.dir, { recursive: true });
    const tmp = `${this.leasePath(port)}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(lease, null, 2), "utf-8");
    renameSync(tmp, this.leasePath(port));
  }

  remove(port: number): void {
    try { unlinkSync(this.leasePath(port)); } catch { /* already gone */ }
  }

  /** Run `fn` holding the port's lock.  A lock older than 10 s, or still held after ~3 s, belongs to
   *  a stuck or dead process and is stolen: failing to settle at exit would strand the server, which
   *  is the defect being fixed, so the lock is advisory, never a reason to give up. */
  withLock<T>(port: number, fn: () => T): T {
    mkdirSync(this.dir, { recursive: true });
    const lock = this.lockPath(port);
    let held = false;
    for (let attempt = 0; attempt < 200 && !held; attempt++) {
      try {
        closeSync(openSync(lock, "wx"));
        held = true;
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "EEXIST") break; // cannot lock here: proceed unlocked
        try { if (Date.now() - statSync(lock).mtimeMs > 10_000) unlinkSync(lock); } catch { /* raced */ }
        this.sleep(15);
      }
    }
    if (!held) {
      try { unlinkSync(lock); } catch { /* raced */ }
      try { closeSync(openSync(lock, "wx")); held = true; } catch { /* proceed unlocked */ }
    }
    try {
      return fn();
    } finally {
      if (held) { try { unlinkSync(lock); } catch { /* already gone */ } }
    }
  }

  /** Append one JSON row to a file in the lease directory (stop log, receipts). */
  appendRow(file: string, row: Record<string, unknown>): void {
    mkdirSync(this.dir, { recursive: true });
    appendFileSync(join(this.dir, file), JSON.stringify(row) + "\n", "utf-8");
  }
}

// ---------------------------------------------------------------------------
// The lease manager
// ---------------------------------------------------------------------------

export type AttachResult =
  | { kind: "held"; origin: "spawned" | "adopted"; server: ServerRecord; holders: number }
  | { kind: "unsupported" }
  | { kind: "no-listener" }
  | { kind: "ambiguous" }
  | { kind: "unverified"; reason: string };

export interface ServerLeasesDeps {
  ops: ProcessOps;
  store: LeaseStore;
  /** Start the detached reaper for `port`; returns its identity (null: could not start). */
  spawnReaper?: (port: number) => HolderRecord | null;
  /** Called BEFORE every stop (kill-discipline: receipt first). */
  receipt?: (rec: StopReceipt) => void;
  log?: (line: string) => void;
}

/** The process surface the exit hooks need (the global `process` satisfies it). */
export interface LeaseProcess {
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  exit(code?: number): void;
  listenerCount?(event: string): number;
}

const SIGNAL_EXIT_CODES: Record<string, number> = { SIGHUP: 129, SIGINT: 130, SIGTERM: 143, SIGBREAK: 149 };

export class ServerLeases {
  private readonly ops: ProcessOps;
  private readonly store: LeaseStore;
  private readonly held = new Set<number>();
  private readonly beforeRelease: Array<() => void> = [];
  private selfRec: HolderRecord | null = null;
  private released = false;
  private hooked = false;

  constructor(private readonly deps: ServerLeasesDeps) {
    this.ops = deps.ops;
    this.store = deps.store;
  }

  private log(line: string): void { try { this.deps.log?.(line); } catch { /* logging never fails a stop */ } }

  holding(port: number): boolean { return this.held.has(port); }

  /** Run `fn` first thing on release, before the server is touched (the supervisor uses this to
   *  stop respawning). */
  onBeforeRelease(fn: () => void): void { this.beforeRelease.push(fn); }

  private holderAlive(h: HolderRecord): boolean {
    const id = this.ops.identify(h.pid);
    return id !== null && id.startTime === h.startTime;
  }

  private serverAlive(s: ServerRecord, port: number): boolean {
    const id = this.ops.identify(s.pid);
    return id !== null && id.startTime === s.startTime && id.cmdline === s.cmdline && verifyServerCmdline(id.cmdline, port, s.exe);
  }

  private withLiveHolders(holders: HolderRecord[]): HolderRecord[] {
    return holders.filter((h) => this.holderAlive(h));
  }

  private ensureReaper(lease: LeaseFile): void {
    if (lease.reaper && this.holderAlive(lease.reaper)) return;
    lease.reaper = null;
    try { lease.reaper = this.deps.spawnReaper?.(lease.port) ?? null; } catch (e) { this.log(`reaper start failed: ${String(e)}`); }
  }

  private addSelf(holders: HolderRecord[], self: HolderRecord): HolderRecord[] {
    return [...holders.filter((h) => !(h.pid === self.pid)), self];
  }

  /** Join the lease for a server that is already answering on `port`: record it as owned, with its
   *  PID and command line checked, so this instance's exit can stop it. */
  attachAdopted(port: number): AttachResult {
    const me = this.ops.self();
    if (!me) return { kind: "unsupported" };
    const self: HolderRecord = { pid: me.pid, startTime: me.startTime };
    let result: AttachResult = { kind: "no-listener" };
    this.store.withLock(port, () => {
      const existing = this.store.read(port);
      let server: ServerRecord | null = existing?.server && this.serverAlive(existing.server, port) ? existing.server : null;
      if (!server) {
        const pid = this.ops.listenerPid(port);
        if (pid === null) { result = { kind: "no-listener" }; return; }
        if (pid === "ambiguous") { result = { kind: "ambiguous" }; return; }
        const id = this.ops.identify(pid);
        if (!id) { result = { kind: "unverified", reason: `cannot read process ${pid}` }; return; }
        if (!verifyServerCmdline(id.cmdline, port)) {
          result = { kind: "unverified", reason: `process ${pid} is not a llama-server on port ${port}` };
          return;
        }
        server = { pid: id.pid, startTime: id.startTime, cmdline: id.cmdline, origin: "adopted" };
      }
      const lease: LeaseFile = {
        version: 1, port, server,
        holders: this.addSelf(this.withLiveHolders(existing?.holders ?? []), self),
        reaper: existing?.reaper ?? null,
      };
      this.ensureReaper(lease);
      this.store.write(port, lease);
      this.held.add(port);
      this.selfRec = self;
      result = { kind: "held", origin: server.origin, server, holders: lease.holders.length };
    });
    return result;
  }

  /** Record a server this process just spawned (also called again after each supervisor respawn). */
  recordSpawned(port: number, pid: number, exe: string): AttachResult {
    const me = this.ops.self();
    if (!me) return { kind: "unsupported" };
    const self: HolderRecord = { pid: me.pid, startTime: me.startTime };
    const id = this.ops.identify(pid);
    if (!id) return { kind: "unverified", reason: `cannot read spawned process ${pid}` };
    if (!verifyServerCmdline(id.cmdline, port, exe)) {
      return { kind: "unverified", reason: `spawned process ${pid} is not ${exe} on port ${port}` };
    }
    let result: AttachResult = { kind: "unsupported" };
    this.store.withLock(port, () => {
      const existing = this.store.read(port);
      const server: ServerRecord = { pid: id.pid, startTime: id.startTime, cmdline: id.cmdline, origin: "spawned", exe };
      const lease: LeaseFile = {
        version: 1, port, server,
        holders: this.addSelf(this.withLiveHolders(existing?.holders ?? []), self),
        reaper: existing?.reaper ?? null,
      };
      this.ensureReaper(lease);
      this.store.write(port, lease);
      this.held.add(port);
      this.selfRec = self;
      result = { kind: "held", origin: "spawned", server, holders: lease.holders.length };
    });
    return result;
  }

  /** Stop the lease's server if, and only if, it is still the recorded process. */
  private stopServer(port: number, server: ServerRecord, why: string): TerminateOutcome {
    // Nothing to stop, or a different process now holds the PID: no receipt, no kill.
    const live = this.ops.identify(server.pid);
    if (live === null) return "gone";
    if (live.startTime !== server.startTime || live.cmdline !== server.cmdline) {
      this.log(`not stopping pid ${server.pid} on port ${port}: it is no longer the recorded server`);
      return "mismatch";
    }
    try {
      this.deps.receipt?.({ port, pid: server.pid, cmdline: server.cmdline, why });
    } catch (e) {
      this.log(`stop receipt failed: ${String(e)}`); // a ledger fault must not strand the GPU
    }
    const outcome = this.ops.terminate(server, (live: ProcessIdentity) => verifyServerCmdline(live.cmdline, port, server.exe));
    this.log(`stopped model server pid ${server.pid} on port ${port}: ${outcome} (${why})`);
    try {
      this.store.appendRow("stops.jsonl", {
        ts: new Date().toISOString(), port, pid: server.pid, origin: server.origin, outcome, why,
      });
    } catch { /* best effort */ }
    return outcome;
  }

  /** Settle one port: drop dead holders; with none left, stop the server and delete the lease.
   *  Returns "done" when the lease is gone, "wait" while a live holder remains.  `me` is the calling
   *  reaper: a lease already served by another live reaper makes this one redundant. */
  reapOnce(port: number, me?: HolderRecord): "wait" | "done" {
    if (!this.store.exists(port)) return "done";
    let out: "wait" | "done" = "wait";
    this.store.withLock(port, () => {
      const lease = this.store.read(port);
      if (!lease) { out = "done"; return; }
      if (me && lease.reaper && lease.reaper.pid !== me.pid && this.holderAlive(lease.reaper)) { out = "done"; return; }
      const live = this.withLiveHolders(lease.holders);
      if (live.length > 0) {
        if (live.length !== lease.holders.length) this.store.write(port, { ...lease, holders: live });
        return;
      }
      if (lease.server) this.stopServer(port, lease.server, "no live ember holder remains");
      this.store.remove(port);
      out = "done";
    });
    return out;
  }

  /** Remove this process from every lease it holds; stop each server no live holder still needs.
   *  Idempotent, synchronous, never throws. */
  releaseSync(): void {
    if (this.released) return;
    this.released = true;
    for (const fn of this.beforeRelease) { try { fn(); } catch { /* keep releasing */ } }
    const self = this.selfRec;
    if (!self) return;
    for (const port of this.held) {
      try {
        this.store.withLock(port, () => {
          const lease = this.store.read(port);
          if (!lease) return;
          const others = lease.holders.filter((h) => !(h.pid === self.pid && h.startTime === self.startTime));
          const live = this.withLiveHolders(others);
          if (live.length > 0) { this.store.write(port, { ...lease, holders: live }); return; }
          if (lease.server) this.stopServer(port, lease.server, "last ember holder exited");
          this.store.remove(port);
        });
      } catch (e) {
        this.log(`release of port ${port} failed: ${String(e)}`);
      }
    }
  }

  /** Release on every exit path this process can observe: normal exit, process.exit(), uncaught
   *  error (main.ts routes it to exit(1)), Ctrl+C, SIGTERM, and console-window close (SIGHUP /
   *  SIGBREAK).  A hard kill runs none of these; the reaper covers that. */
  installExitHooks(proc: LeaseProcess = process): void {
    if (this.hooked) return;
    this.hooked = true;
    proc.on("exit", () => { markSessionShuttingDown(); this.releaseSync(); });
    for (const sig of Object.keys(SIGNAL_EXIT_CODES)) {
      proc.on(sig, () => {
        markSessionShuttingDown();
        this.releaseSync();
        // Another listener (graceful shutdown) owns the exit; otherwise exit now.
        if ((proc.listenerCount?.(sig) ?? 1) <= 1) proc.exit(SIGNAL_EXIT_CODES[sig]);
      });
    }
  }
}

/** Kill-receipt sink: appends to EMBER_KILL_RECEIPTS_PATH (or KILL_RECEIPTS_PATH) when set, and always
 *  to the lease directory's own kill-receipts.jsonl.  Row shape matches the fleet ledger. */
export function makeStopReceiptSink(store: LeaseStore, env: Record<string, string | undefined> = process.env): (rec: StopReceipt) => void {
  return (rec) => {
    const row = {
      ts: new Date().toISOString(),
      script: "ember-cli server-lease",
      pids: [rec.pid],
      match_rule: `model server pid ${rec.pid} on port ${rec.port}, creation time and command line verified against the lease (${rec.why})`,
      survivors_expected: "none",
    };
    const shared = env["EMBER_KILL_RECEIPTS_PATH"] ?? env["KILL_RECEIPTS_PATH"];
    if (shared) {
      try { appendFileSync(shared, JSON.stringify(row) + "\n", "utf-8"); } catch { /* the local copy below still lands */ }
    }
    store.appendRow("kill-receipts.jsonl", row);
  };
}
