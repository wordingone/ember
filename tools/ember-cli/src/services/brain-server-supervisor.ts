// services/brain-server-supervisor.ts — ember-cli-owned supervision of the cbase brain
// server (issue #122, refreshed 2026-07-10). Four mechanisms:
//   1. Spawn-on-demand: health-probe :8083; if down, spawn scripts/serve_cbase_openai.py
//      (detached, explicit interpreter path, stdout/stderr to a rotating log), wait for
//      health-green (cap 30s), racing the child's own early exit so a crash-on-start
//      surfaces immediately instead of stalling the cap.
//   2. Single-instance guard: the serving registry (scripts/serving_registry.py's
//      state/serving-registry.json, NOT a bare PID file per the 2026-07-10 spec refresh) is
//      the source of truth. A live, cmdline-verified row is adopted, never double-spawned; a
//      stale row (dead pid or cmdline mismatch) is reclaimed with a log line before spawning.
//   3. Teardown tether (issue #110 semantics, unchanged by the refresh): only the CLI
//      instance that spawned the server may shut it down. An adopted server -- whether
//      registered by an earlier ember-cli instance, the operator, or the :8082 watchdog
//      contract (#464/#611) -- is NEVER killed by this instance. Ownership lives in
//      in-process module state, exactly like services/model-lifecycle.ts's trackedPid.
//   4. Receipts: every spawn/adopt/reclaim/shutdown/spawn_failed event is appended to
//      tools/ember-cli/state/brain-server-events.jsonl.
//
// Device policy (spec refresh, inherits the GPU-lease clause + #588/#602/#614): a cuda spawn
// is only legal when no training window/lease is live (the SAME planned-outage.json marker
// outage-banner-poller.ts/activity-feed.ts already parse) and EMBER_GPU_FREE is unset, AND the
// :8082 27B reference server (serve_cbase_openai.py's own one-model-at-a-time guard target) is
// down. Any of those conditions -- outage active, GPU-free requested, or :8082 answering --
// forces --device cpu; this module never attempts a cuda spawn the body doesn't have room for.
//
// All OS-facing effects (health probe, process spawn, pid liveness, cmdline lookup, registry
// I/O, event-log append) are injectable via BrainServerSupervisorDeps so the orchestration
// functions (ensureBrainServer / teardownBrainServer) can be exercised for real -- same
// injected-leaf-function pattern entrypoints/process-entry.ts's main() already uses for its
// own managed-spawn boot matrix (spawnServer/waitReady/probeExisting) -- without ever spawning
// a real GPU-touching process in a test.

import { spawn, type ChildProcess } from "node:child_process";
import { openSync, closeSync } from "node:fs";
import fs from "node:fs";
import path from "node:path";
import { readFile, stat } from "node:fs/promises";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { parseOutageMarker, computeEffectiveMarker } from "./activity-feed.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** scripts/serve_cbase_openai.py's own PORT_DEFAULT (L63) -- ground truth per the 2026-07-10
 *  spec refresh, superseding the issue's original :8080 target and the 2026-07-09 comment's
 *  stale :8084 reference. */
export const BRAIN_SERVER_PORT = 8083;

/** The 27B reference server serve_cbase_openai.py's own VRAM guard checks (its L17/L274
 *  `check_reference_server`) -- this module mirrors that same guard on the CLI side so a
 *  doomed `--device cuda` spawn (one the child would itself refuse) is never attempted. */
export const BRAIN_SERVER_REFERENCE_PORT = 8082;

export const BRAIN_SERVER_HEALTH_PROBE_TIMEOUT_MS = 1000;
export const BRAIN_SERVER_SPAWN_HEALTH_CAP_MS = 30_000;
export const BRAIN_SERVER_HEALTH_POLL_INTERVAL_MS = 1000;

const LOG_MAX_BYTES = 50 * 1024 * 1024; // 50 MB -- mirrors process-entry.ts's rotation policy
const LOG_KEEP_BYTES = 10 * 1024 * 1024; // 10 MB

const LAUNCHED_BY = "ember-cli";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BrainServerDevice = "cpu" | "cuda";
export type BrainServerHealthStatus = "ready" | "loading" | "down";

/** Row schema mirrors scripts/serving_registry.py's register() exactly (port, model_path,
 *  pid, launched_by, ts, device) -- both languages read/write the same JSONL file. */
export interface RegistryRow {
  port: number;
  model_path: string;
  pid: number;
  launched_by: string;
  ts: string;
  device: BrainServerDevice;
}

export type BrainServerEventKind = "spawn" | "adopt" | "reclaim" | "shutdown" | "spawn_failed";

export interface BrainServerEventRow {
  ts: string;
  event: BrainServerEventKind;
  port: number;
  pid?: number;
  device?: BrainServerDevice;
  detail?: string;
}

export interface BrainServerHandle {
  process: ChildProcess;
  pid: number;
}

export type EnsureBrainServerResult =
  | { outcome: "adopted"; port: number }
  | { outcome: "spawned"; port: number; pid: number; device: BrainServerDevice }
  | { outcome: "failed"; reason: string };

export type TeardownBrainServerResult =
  | { outcome: "killed"; pid: number }
  | { outcome: "not-owner" }
  | { outcome: "pid-mismatch"; expectedPid: number };

export interface BrainServerSupervisorDeps {
  repoRoot: string;
  registryPath?: string;
  eventsLogPath?: string;
  env?: NodeJS.ProcessEnv;
  now?: () => Date;

  /** GET http://127.0.0.1:<port>/health with a `timeoutMs` abort. Real default below; tests
   *  inject a fake to avoid real network I/O (or point it at a real synthetic stub server). */
  probeHealth?: (port: number, timeoutMs?: number) => Promise<BrainServerHealthStatus>;
  /** Liveness only (no cmdline detail) -- default `process.kill(pid, 0)`. */
  isPidAlive?: (pid: number) => boolean;
  /** Best-effort full command line for a pid, or null if it can't be determined (dead pid,
   *  permission denied, non-Windows fallback unavailable). Default shells PowerShell's
   *  Get-CimInstance Win32_Process, the same technique this repo already uses for Windows
   *  process identity verification (2026-07-03 brain-server-durable-form receipt). */
  getProcessCommandLine?: (pid: number) => Promise<string | null>;
  /** Substring the resolved cmdline must contain to count as "this is our brain server", not
   *  an unrelated process that happens to reuse the registered pid. Defaults to the real
   *  script's basename; tests targeting a synthetic stub override this. */
  cmdlineMatchSubstring?: string;

  spawnServer?: (opts: BrainServerSpawnOptions) => BrainServerHandle;
  resolveInterpreter?: (env: NodeJS.ProcessEnv) => string;
  resolveScriptPath?: (repoRoot: string) => string;
  resolveModelPath?: (repoRoot: string) => string;
  resolveLogPath?: (repoRoot: string) => string;

  spawnHealthCapMs?: number;
  healthPollIntervalMs?: number;
}

export interface BrainServerSpawnOptions {
  interpreter: string;
  scriptPath: string;
  port: number;
  device: BrainServerDevice;
  logPath: string;
}

// ---------------------------------------------------------------------------
// Pure helpers -- device policy
// ---------------------------------------------------------------------------

export interface DevicePolicyInput {
  gpuFreeRequested: boolean;
  outageEffective: boolean;
  referenceServerUp: boolean;
}

/** Pure decision: cpu unless NONE of (GPU-free requested, an outage window is effective,
 *  the :8082 reference server answers) hold. Mirrors serve_cbase_openai.py's own
 *  check_reference_server guard so the CLI never attempts a spawn the child would refuse. */
export function resolveDevicePolicy(input: DevicePolicyInput): BrainServerDevice {
  if (input.gpuFreeRequested) return "cpu";
  if (input.outageEffective) return "cpu";
  if (input.referenceServerUp) return "cpu";
  return "cuda";
}

// ---------------------------------------------------------------------------
// Pure helpers -- registry JSONL (mirrors scripts/serving_registry.py's shape exactly)
// ---------------------------------------------------------------------------

/** Tolerant JSONL parse -- a malformed line is skipped, never thrown on (mirrors the python
 *  reader's try/except-per-file, degraded to per-line here since a single torn line should
 *  not discard every other server's row). */
export function parseRegistryRows(raw: string | null): RegistryRow[] {
  if (!raw) return [];
  const rows: RegistryRow[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      rows.push(JSON.parse(trimmed) as RegistryRow);
    } catch {
      // torn/partial line -- skip, matches the python reader's tolerant-reader contract
    }
  }
  return rows;
}

export function serializeRegistryRows(rows: RegistryRow[]): string {
  return rows.map((r) => JSON.stringify(r)).join("\n") + (rows.length > 0 ? "\n" : "");
}

export function findBrainServerRow(rows: RegistryRow[], port: number = BRAIN_SERVER_PORT): RegistryRow | null {
  return rows.find((r) => r.port === port) ?? null;
}

export function filterOutPort(rows: RegistryRow[], port: number): RegistryRow[] {
  return rows.filter((r) => r.port !== port);
}

export function filterOutPid(rows: RegistryRow[], pid: number): RegistryRow[] {
  return rows.filter((r) => r.pid !== pid);
}

// ---------------------------------------------------------------------------
// Path resolvers (defaults; all overridable via deps for tests)
// ---------------------------------------------------------------------------

export function defaultRegistryPath(repoRoot: string): string {
  return path.join(repoRoot, "state", "serving-registry.json");
}

export function defaultEventsLogPath(repoRoot: string): string {
  return path.join(repoRoot, "tools", "ember-cli", "state", "brain-server-events.jsonl");
}

export function defaultScriptPath(repoRoot: string): string {
  return path.join(repoRoot, "scripts", "serve_cbase_openai.py");
}

/** Mirrors serve_cbase_openai.py's own CHECKPOINT_PATH_DEFAULT computation -- used only as the
 *  registry row's informational model_path field (the CLI never overrides --checkpoint; the
 *  child resolves and validates the real path itself at argparse time, see spawnBrainServer's
 *  comment on the bad-model-path defect class). */
export function defaultModelPath(repoRoot: string): string {
  return path.join(
    repoRoot, "models", "cbase-grow-rung", "rung2-event-grow-rung2-20260708-real", "b1-snapshot", "model.pt",
  );
}

export function defaultLogPath(repoRoot: string): string {
  return path.join(repoRoot, "tools", "ember-cli", "state", "brain_server_stderr.log");
}

/** "Explicit interpreter path" per the frozen spec -- EMBER_PYTHON_BIN is the override point;
 *  production deployments should set it to an absolute interpreter path rather than relying on
 *  PATH resolution. Defaults to "python" for portability when unset. */
export function resolvePythonInterpreterDefault(env: NodeJS.ProcessEnv): string {
  return env["EMBER_PYTHON_BIN"] ?? "python";
}

// ---------------------------------------------------------------------------
// I/O leaves -- real defaults (all injectable)
// ---------------------------------------------------------------------------

async function defaultProbeHealth(port: number, timeoutMs = BRAIN_SERVER_HEALTH_PROBE_TIMEOUT_MS): Promise<BrainServerHealthStatus> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`, { signal: ctrl.signal });
      if (!res.ok) return "down";
      const body = (await res.json()) as { status?: string };
      if (body.status === "ready") return "ready";
      if (body.status === "loading") return "loading";
      return "down";
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return "down";
  }
}

function defaultIsPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** Real default: PowerShell Get-CimInstance Win32_Process, the same identity-verification
 *  technique already established in this repo for exactly this purpose (2026-07-03
 *  brain-server-durable-form receipt: "Get-CimInstance Win32_Process (NOT msys ps, per frozen
 *  spec note -- msys ps cannot see Windows cmdlines)"). Fails open to null -- a lookup failure
 *  is treated as "cannot verify", never as a false match. */
async function defaultGetProcessCommandLine(pid: number): Promise<string | null> {
  try {
    const { execFile } = await import("node:child_process");
    const cmdline = await new Promise<string>((resolvePromise, reject) => {
      execFile(
        "powershell.exe",
        [
          "-NoProfile", "-NonInteractive", "-Command",
          `(Get-CimInstance Win32_Process -Filter "ProcessId=${pid}").CommandLine`,
        ],
        { timeout: 5000 },
        (err, stdout) => {
          if (err) { reject(err); return; }
          resolvePromise(stdout ?? "");
        },
      );
    });
    const trimmed = cmdline.trim();
    return trimmed.length > 0 ? trimmed : null;
  } catch {
    return null;
  }
}

async function rotateLogFile(logPath: string): Promise<void> {
  try {
    const info = await stat(logPath);
    if (info.size > LOG_MAX_BYTES) {
      const fullData = await readFile(logPath);
      const kept = fullData.slice(fullData.length - LOG_KEEP_BYTES);
      await Bun.write(logPath, kept);
    }
  } catch {
    // not present or unreadable -- no-op, matches process-entry.ts's rotateLlamaStderrLog
  }
}

function defaultSpawnServer(opts: BrainServerSpawnOptions): BrainServerHandle {
  const logFd = openSync(opts.logPath, "a");
  const child = spawn(
    opts.interpreter,
    [opts.scriptPath, "--port", String(opts.port), "--device", opts.device],
    { stdio: ["ignore", "ignore", logFd], detached: true },
  );
  child.on("exit", () => { try { closeSync(logFd); } catch {} });
  child.unref();
  if (typeof child.pid !== "number") {
    throw new Error("spawn did not return a pid");
  }
  return { process: child, pid: child.pid };
}

// ---------------------------------------------------------------------------
// Registry I/O (real: atomic tmp+rename, mirrors scripts/serving_registry.py's _write_atomic)
// ---------------------------------------------------------------------------

export async function readRegistryFile(registryPath: string): Promise<RegistryRow[]> {
  try {
    const raw = await readFile(registryPath, "utf-8");
    return parseRegistryRows(raw);
  } catch {
    return []; // missing file = empty registry, matches the python reader's contract
  }
}

export async function writeRegistryFileAtomic(rows: RegistryRow[], registryPath: string): Promise<void> {
  await fs.promises.mkdir(path.dirname(registryPath), { recursive: true });
  const tmpPath = registryPath + ".tmp";
  await fs.promises.writeFile(tmpPath, serializeRegistryRows(rows), "utf-8");
  await fs.promises.rename(tmpPath, registryPath);
}

// ---------------------------------------------------------------------------
// Events log (fail-open append, mirrors services/operator-receipts.ts's idiom exactly)
// ---------------------------------------------------------------------------

export function appendBrainServerEvent(row: BrainServerEventRow, eventsLogPath: string): void {
  try {
    fs.mkdirSync(path.dirname(eventsLogPath), { recursive: true });
    fs.appendFileSync(eventsLogPath, JSON.stringify(row) + "\n", "utf8");
  } catch (err) {
    console.warn(
      `[brain-server-supervisor] event append failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}

// ---------------------------------------------------------------------------
// Resolved deps (fills in every default, once, per call)
// ---------------------------------------------------------------------------

interface ResolvedDeps {
  repoRoot: string;
  registryPath: string;
  eventsLogPath: string;
  env: NodeJS.ProcessEnv;
  now: () => Date;
  probeHealth: (port: number, timeoutMs?: number) => Promise<BrainServerHealthStatus>;
  isPidAlive: (pid: number) => boolean;
  getProcessCommandLine: (pid: number) => Promise<string | null>;
  cmdlineMatchSubstring: string;
  spawnServer: (opts: BrainServerSpawnOptions) => BrainServerHandle;
  interpreter: string;
  scriptPath: string;
  modelPath: string;
  logPath: string;
  spawnHealthCapMs: number;
  healthPollIntervalMs: number;
}

function resolveDeps(deps: BrainServerSupervisorDeps): ResolvedDeps {
  const env = deps.env ?? process.env;
  const scriptPath = (deps.resolveScriptPath ?? defaultScriptPath)(deps.repoRoot);
  return {
    repoRoot: deps.repoRoot,
    registryPath: deps.registryPath ?? defaultRegistryPath(deps.repoRoot),
    eventsLogPath: deps.eventsLogPath ?? defaultEventsLogPath(deps.repoRoot),
    env,
    now: deps.now ?? (() => new Date()),
    probeHealth: deps.probeHealth ?? defaultProbeHealth,
    isPidAlive: deps.isPidAlive ?? defaultIsPidAlive,
    getProcessCommandLine: deps.getProcessCommandLine ?? defaultGetProcessCommandLine,
    cmdlineMatchSubstring: deps.cmdlineMatchSubstring ?? path.basename(scriptPath),
    spawnServer: deps.spawnServer ?? defaultSpawnServer,
    interpreter: (deps.resolveInterpreter ?? resolvePythonInterpreterDefault)(env),
    scriptPath,
    modelPath: (deps.resolveModelPath ?? defaultModelPath)(deps.repoRoot),
    logPath: (deps.resolveLogPath ?? defaultLogPath)(deps.repoRoot),
    spawnHealthCapMs: deps.spawnHealthCapMs ?? BRAIN_SERVER_SPAWN_HEALTH_CAP_MS,
    healthPollIntervalMs: deps.healthPollIntervalMs ?? BRAIN_SERVER_HEALTH_POLL_INTERVAL_MS,
  };
}

function isoNow(now: () => Date): string {
  return now().toISOString();
}

// ---------------------------------------------------------------------------
// Module-level ownership state (mirrors services/model-lifecycle.ts's trackedPid pattern) --
// teardown tether semantics (#110) live here: only a spawn recorded by THIS module instance
// (this process) is ever killed. Adoption -- of either a foreign server or another ember-cli
// instance's own registered row -- never sets this, so teardownBrainServer is a no-op for it.
// ---------------------------------------------------------------------------

let ownedHandle: { pid: number; port: number } | null = null;

export function resetBrainServerSupervisorForTests(): void {
  ownedHandle = null;
}

// ---------------------------------------------------------------------------
// Single-instance guard -- reclaim a stale registry row (dead pid or cmdline mismatch)
// ---------------------------------------------------------------------------

async function reclaimStaleRow(resolved: ResolvedDeps, row: RegistryRow): Promise<void> {
  const rows = await readRegistryFile(resolved.registryPath);
  await writeRegistryFileAtomic(filterOutPort(rows, row.port), resolved.registryPath);
  appendBrainServerEvent(
    {
      ts: isoNow(resolved.now), event: "reclaim", port: row.port, pid: row.pid,
      detail: `stale registry row reclaimed (dead pid or cmdline mismatch): ${JSON.stringify(row)}`,
    },
    resolved.eventsLogPath,
  );
}

/** True iff `row`'s pid is both alive AND its cmdline contains the expected script substring
 *  -- both checks required (kill-discipline's "verified PID cmdline match", not liveness
 *  alone: a reused pid that happens to be alive but is a totally unrelated process must never
 *  be adopted as "our" brain server). */
async function rowIsLiveAndVerified(resolved: ResolvedDeps, row: RegistryRow): Promise<boolean> {
  if (!resolved.isPidAlive(row.pid)) return false;
  const cmdline = await resolved.getProcessCommandLine(row.pid);
  if (cmdline === null) return false; // cannot verify -- never adopt on an unverifiable pid
  return cmdline.includes(resolved.cmdlineMatchSubstring);
}

// ---------------------------------------------------------------------------
// Device policy wiring (reads the same planned-outage.json marker outage-banner-poller.ts /
// activity-feed.ts already parse, plus EMBER_GPU_FREE, plus a live :8082 probe)
// ---------------------------------------------------------------------------

async function resolveDeviceForSpawn(resolved: ResolvedDeps): Promise<BrainServerDevice> {
  const gpuFreeRequested = Boolean(resolved.env["EMBER_GPU_FREE"]);

  let outageEffective = false;
  try {
    const markerPath = path.join(resolved.repoRoot, "tools", "ember-cli", "state", "planned-outage.json");
    const raw = await readFile(markerPath, "utf-8");
    const parsed = parseOutageMarker(raw);
    outageEffective = computeEffectiveMarker(parsed, resolved.now().getTime()) !== null;
  } catch {
    outageEffective = false; // absent/unreadable/malformed marker = no outage, matches the banner's fail-open contract
  }

  const referenceHealth = await resolved.probeHealth(BRAIN_SERVER_REFERENCE_PORT, BRAIN_SERVER_HEALTH_PROBE_TIMEOUT_MS);
  const referenceServerUp = referenceHealth !== "down";

  return resolveDevicePolicy({ gpuFreeRequested, outageEffective, referenceServerUp });
}

// ---------------------------------------------------------------------------
// ensureBrainServer -- mechanism 1 + 2 + 4 (spawn-on-demand, single-instance, receipts)
// ---------------------------------------------------------------------------

export async function ensureBrainServer(deps: BrainServerSupervisorDeps): Promise<EnsureBrainServerResult> {
  const resolved = resolveDeps(deps);

  const initialHealth = await resolved.probeHealth(BRAIN_SERVER_PORT, BRAIN_SERVER_HEALTH_PROBE_TIMEOUT_MS);
  if (initialHealth !== "down") {
    // A server already answers -- adopt regardless of who started it (single-instance guard:
    // "never a second server"). Ownership for teardown purposes is NOT claimed here; only a
    // spawn performed by THIS call sets ownedHandle.
    appendBrainServerEvent({ ts: isoNow(resolved.now), event: "adopt", port: BRAIN_SERVER_PORT }, resolved.eventsLogPath);
    return { outcome: "adopted", port: BRAIN_SERVER_PORT };
  }

  // Down: reclaim a stale registry row before spawning, so a dead row never blocks single-
  // instance enforcement and never leaks in the registry once we know it's gone.
  const rows = await readRegistryFile(resolved.registryPath);
  const existingRow = findBrainServerRow(rows, BRAIN_SERVER_PORT);
  if (existingRow && !(await rowIsLiveAndVerified(resolved, existingRow))) {
    await reclaimStaleRow(resolved, existingRow);
  }

  const device = await resolveDeviceForSpawn(resolved);

  await rotateLogFile(resolved.logPath);
  await fs.promises.mkdir(path.dirname(resolved.logPath), { recursive: true });

  let handle: BrainServerHandle;
  try {
    handle = resolved.spawnServer({
      interpreter: resolved.interpreter,
      scriptPath: resolved.scriptPath,
      port: BRAIN_SERVER_PORT,
      device,
      logPath: resolved.logPath,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    appendBrainServerEvent(
      { ts: isoNow(resolved.now), event: "spawn_failed", port: BRAIN_SERVER_PORT, device, detail: msg },
      resolved.eventsLogPath,
    );
    return { outcome: "failed", reason: `could not start the brain server (${msg})` };
  }

  // Race health-green against the child exiting early (bad checkpoint path, port bind
  // failure, or any other fast crash) -- mirrors process-entry.ts's #159 boot-matrix pattern
  // (readyOutcome race) so a doomed spawn surfaces immediately instead of riding out the cap.
  type ReadyOutcome = { kind: "ready" } | { kind: "exited"; code: number | null } | { kind: "timeout" };

  const pollReady = async (): Promise<ReadyOutcome> => {
    const deadline = Date.now() + resolved.spawnHealthCapMs;
    while (Date.now() < deadline) {
      const status = await resolved.probeHealth(BRAIN_SERVER_PORT, BRAIN_SERVER_HEALTH_PROBE_TIMEOUT_MS);
      if (status === "ready") return { kind: "ready" };
      await new Promise((r) => setTimeout(r, resolved.healthPollIntervalMs));
    }
    return { kind: "timeout" };
  };

  const proc = handle.process as unknown as { once?: (event: string, listener: (...args: unknown[]) => void) => void };
  const earlyExit: Promise<ReadyOutcome> | null =
    typeof proc?.once === "function"
      ? new Promise<ReadyOutcome>((resolvePromise) => {
          proc.once!("exit", (code: unknown) => resolvePromise({ kind: "exited", code: typeof code === "number" ? code : null }));
        })
      : null;

  const outcome: ReadyOutcome = earlyExit ? await Promise.race([pollReady(), earlyExit]) : await pollReady();

  if (outcome.kind === "exited") {
    const codeText = outcome.code !== null ? ` (exit code ${outcome.code})` : "";
    appendBrainServerEvent(
      { ts: isoNow(resolved.now), event: "spawn_failed", port: BRAIN_SERVER_PORT, pid: handle.pid, device, detail: `exited before ready${codeText}` },
      resolved.eventsLogPath,
    );
    return { outcome: "failed", reason: `brain server exited before ready${codeText}. Check log at ${resolved.logPath}.` };
  }

  if (outcome.kind === "timeout") {
    // Never leak an owned-but-never-healthy child -- we spawned it, we clean it up.
    try { handle.process.kill("SIGTERM"); } catch {}
    appendBrainServerEvent(
      { ts: isoNow(resolved.now), event: "spawn_failed", port: BRAIN_SERVER_PORT, pid: handle.pid, device, detail: `did not become ready within ${resolved.spawnHealthCapMs}ms` },
      resolved.eventsLogPath,
    );
    return { outcome: "failed", reason: `brain server did not become ready within ${resolved.spawnHealthCapMs}ms` };
  }

  // Ready: register + record ownership for teardown.
  const freshRows = await readRegistryFile(resolved.registryPath);
  const nextRows = [...filterOutPort(freshRows, BRAIN_SERVER_PORT), {
    port: BRAIN_SERVER_PORT, model_path: resolved.modelPath, pid: handle.pid, launched_by: LAUNCHED_BY,
    ts: isoNow(resolved.now), device,
  }];
  await writeRegistryFileAtomic(nextRows, resolved.registryPath);
  appendBrainServerEvent(
    { ts: isoNow(resolved.now), event: "spawn", port: BRAIN_SERVER_PORT, pid: handle.pid, device },
    resolved.eventsLogPath,
  );
  ownedHandle = { pid: handle.pid, port: BRAIN_SERVER_PORT };

  return { outcome: "spawned", port: BRAIN_SERVER_PORT, pid: handle.pid, device };
}

// ---------------------------------------------------------------------------
// teardownBrainServer -- mechanism 3 (ownership-tethered teardown, issue #110 semantics)
// ---------------------------------------------------------------------------

export async function teardownBrainServer(deps: BrainServerSupervisorDeps): Promise<TeardownBrainServerResult> {
  const resolved = resolveDeps(deps);

  if (!ownedHandle) {
    return { outcome: "not-owner" }; // never spawned this session -- an adopted server STAYS
  }

  const { pid, port } = ownedHandle;

  // Defensive re-verification before kill (kill-discipline: verified-PID-only, never a bare
  // "we remember a number"): if this pid is no longer alive, or its cmdline no longer matches
  // our script, something external already reaped it or pid reuse occurred -- never signal an
  // unverified pid.
  if (!resolved.isPidAlive(pid)) {
    ownedHandle = null;
    const rows = await readRegistryFile(resolved.registryPath);
    await writeRegistryFileAtomic(filterOutPid(rows, pid), resolved.registryPath);
    appendBrainServerEvent(
      { ts: isoNow(resolved.now), event: "shutdown", port, pid, detail: "already dead at teardown time" },
      resolved.eventsLogPath,
    );
    return { outcome: "killed", pid };
  }

  const cmdline = await resolved.getProcessCommandLine(pid);
  if (cmdline !== null && !cmdline.includes(resolved.cmdlineMatchSubstring)) {
    // pid reuse: something else now holds this pid. Never kill it.
    return { outcome: "pid-mismatch", expectedPid: pid };
  }

  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // already gone between the liveness check and here -- fall through to receipt + cleanup
  }

  const rows = await readRegistryFile(resolved.registryPath);
  await writeRegistryFileAtomic(filterOutPid(rows, pid), resolved.registryPath);
  appendBrainServerEvent({ ts: isoNow(resolved.now), event: "shutdown", port, pid }, resolved.eventsLogPath);
  ownedHandle = null;

  return { outcome: "killed", pid };
}

/** Default repo-root resolver for callers that don't already have one (e.g. a future CLI
 *  subcommand). Exported so wiring code never re-derives its own resolution order. */
export function defaultBrainServerRepoRoot(): string {
  return resolveEmberRepoRootOrCwd({}, "[brain-server-supervisor]");
}
