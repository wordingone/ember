// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// issue1455-idle-soak-harness.ts — spawns a real, compiled-from-source cockpit under node-pty
// and samples its own process.memoryUsage() plus bun:jsc-forced-GC heap floors over a live CDP
// session. Extracted from the #1455 investigation's diagnostic driver
// (scratchpad/handle-census-1455.ts, three overnight soak legs) down to the mechanics that a
// permanent regression test needs: spawn, sample, floor-read, clean up. The Windows-only
// VirtualQueryEx region census and the OS-level handle/thread census from that investigation stay
// diagnostic-only (out of this module) — they answered "which subsystem accumulates memory," a
// question this harness does not need to re-ask on every run.
//
// Env config reproduces the exact configuration the investigation's own legs measured (see
// screens/repl.ts's EMBER_DIAGNOSTIC_FORCE_POLLERS_LIVE comment): headlessCaptureEnv() is always
// set (this process is an instrument, not the operator's cockpit — see services/headless-capture.ts
// for why that matters even in an isolated CI checkout), with the memory-footprint and
// serving-topology pollers forced live on top of it so the soak measures the same "cockpit
// actually polling" state as every leg that established the cured/residual verdict on issue #1455.

import { spawn as spawnPty } from "node-pty";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { headlessCaptureEnv } from "./headless-capture.ts";
import { READY_OSC } from "../cli/ready-sentinel.ts";

// Deliberately NOT resolveEmberRepoRoot({}) here: that resolver worktree-canonicalizes by
// design (a worktree checkout resolves to the main repo root), which is correct for consumers
// that want one stable identity across worktrees but wrong for this harness — it must spawn the
// cockpit out of the checkout this test is actually running from, or a worktree PR's changes
// (including this very scaffold) silently test against a different, unrelated tree. Resolve the
// checkout root from this file's own location instead.
function resolveCheckoutRoot(): string {
  const result = spawnSync("git", ["rev-parse", "--show-toplevel"], {
    encoding: "utf8",
    cwd: import.meta.dir,
    windowsHide: true,
  });
  const root = (result.stdout ?? "").trim();
  if (result.status !== 0 || !root) {
    throw new Error(`git rev-parse --show-toplevel failed from ${import.meta.dir}: ${result.stderr}`);
  }
  return root;
}

function resolveBunExecutable(): string {
  const result = spawnSync("where.exe", ["bun"], { encoding: "utf8", windowsHide: true });
  if (result.status !== 0) throw new Error("where.exe bun failed");
  const located = (result.stdout ?? "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const exe = located.find((l) => l.toLowerCase().endsWith(".exe"));
  if (exe) return exe;
  const cmdShim = located.find((l) => l.toLowerCase().endsWith(".cmd"));
  if (cmdShim) {
    const candidate = join(dirname(cmdShim), "node_modules", "bun", "bin", "bun.exe");
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(`no directly-spawnable bun.exe found from: ${JSON.stringify(located)}`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

class CdpSession {
  private ws: WebSocket;
  private id = 1;
  private pending = new Map<number, { resolve: (r: any) => void; reject: (e: unknown) => void }>();
  readonly opened: Promise<void>;

  constructor(url: string) {
    this.ws = new WebSocket(url);
    this.opened = new Promise((resolve, reject) => {
      this.ws.addEventListener("open", () => resolve());
      this.ws.addEventListener("error", (e) => reject(e));
    });
    this.ws.addEventListener("message", (ev) => {
      const data = JSON.parse(ev.data as string);
      if (typeof data.id !== "number") return;
      const waiter = this.pending.get(data.id);
      if (waiter) { this.pending.delete(data.id); waiter.resolve(data); }
    });
  }

  async send(method: string, params: Record<string, unknown> = {}): Promise<any> {
    await this.opened;
    const id = this.id++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("CDP_TIMEOUT:" + method)); }, 15000);
      this.pending.set(id, { resolve: (r) => { clearTimeout(timer); resolve(r); }, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression: string, awaitPromise = false): Promise<{ value: unknown; wasThrown: boolean; raw: unknown }> {
    const data = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise });
    const outer = data.result ?? {};
    const inner = outer.result ?? {};
    return { value: inner.value, wasThrown: Boolean(outer.wasThrown) || Boolean(outer.exceptionDetails), raw: data };
  }

  close(): void { this.ws.close(); }
}

async function connectCdpWithRetry(wsUrl: string, attempts: number, delayMs: number): Promise<CdpSession> {
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const session = new CdpSession(wsUrl);
    try {
      await session.opened;
      return session;
    } catch (err) {
      lastError = err;
      session.close();
      await sleep(delayMs);
    }
  }
  throw new Error(`CDP connect to ${wsUrl} failed after ${attempts} attempts: ${String(lastError)}`);
}

const MEMORY_USAGE_EXPR = "JSON.stringify(process.memoryUsage())";
const FORCE_GC_AND_READ_FLOOR_EXPR =
  "(() => { globalThis.__jscMod.fullGC(); return globalThis.__jscMod.heapSize(); })()";
const IMPORT_JSC_EXPR =
  '(async()=>{ if (!globalThis.__jscMod) { globalThis.__jscMod = await import("bun:jsc"); } })()';

export interface RssSample {
  /** ms since epoch */
  t: number;
  rss: number;
  heapUsed: number;
  heapTotal: number;
  external: number;
  arrayBuffers: number;
}

export interface IdleSoakOptions {
  /** Wall-clock ms to wait after the cockpit reports ready before the measured window starts.
   *  Precautionary, not calibration-justified — see the regression test's own docstring. */
  settleMs: number;
  /** Wall-clock ms of the measured window (RSS sampling + the JS-heap floor delta both span it). */
  durationMs: number;
  /** Cadence between RSS samples inside the measured window. */
  sampleIntervalMs: number;
}

export interface IdleSoakResult {
  rssSamples: RssSample[];
  /** bytes, immediately after a forced full GC, taken at the measured window's start. */
  jsHeapFloorStartBytes: number;
  /** bytes, immediately after a forced full GC, taken at the measured window's end. */
  jsHeapFloorEndBytes: number;
  windowStartMs: number;
  windowEndMs: number;
}

/**
 * Spawns a real ember-cli cockpit (node-pty, real bun.exe, no mocks) with the exact env
 * configuration measured by the #1455 investigation's soak legs, samples it for
 * `opts.durationMs` after an `opts.settleMs` settle period, and returns the raw samples plus a
 * forced-GC JS heap floor read at both ends of the window. Callers own the assertions.
 */
export async function runIdleSoak(opts: IdleSoakOptions): Promise<IdleSoakResult> {
  const repoRoot = resolveCheckoutRoot();
  const sourceRoot = join(repoRoot, "tools", "ember-cli", "src");
  const bunExe = resolveBunExecutable();
  const home = mkdtempSync(join(tmpdir(), "issue1455-idle-soak-"));
  const inspectPort = 6779 + Math.floor(process.pid % 1000);

  const raw: string[] = [];
  let exitObserved = false;

  const child = spawnPty(bunExe, [`--inspect=${inspectPort}`, "./entrypoints/main.ts"], {
    name: "xterm-256color",
    cols: 160,
    rows: 32,
    cwd: sourceRoot,
    env: {
      ...process.env,
      EMBER_HOME: home,
      EMBER_REPO_ROOT: repoRoot,
      EMBER_SOURCE_ROOT: repoRoot,
      EMBER_GPU_FREE: "1",
      EMBER_DISABLE_TERMINAL_TITLE: "1",
      // Leg 6's measured configuration (issue #1455): pollers forced live, activity-feed left
      // enabled (not bisected off) — see screens/repl.ts's own comment on this var.
      EMBER_DIAGNOSTIC_FORCE_POLLERS_LIVE: "1",
      ...headlessCaptureEnv(),
    },
  });
  child.onData((d) => { raw.push(d); });
  child.onExit(() => { exitObserved = true; });

  try {
    let wsUrl: string | null = null;
    const wsDeadline = Date.now() + 10_000;
    while (Date.now() < wsDeadline && wsUrl === null) {
      // Broad terminator set (whitespace/quote/ESC), not [A-Za-z0-9]+ for the token: a narrower
      // character class risks truncating the token at a PTY line-wrap or an adjacent ANSI
      // sequence, producing a syntactically valid but wrong URL that fails to connect.
      const m = raw.join("").match(/ws:\/\/localhost:\d+\/[^\s"'\x1b]+/);
      if (m) wsUrl = m[0]!;
      if (exitObserved) throw new Error("child exited before inspector banner: " + raw.join("").slice(-2000));
      await sleep(100);
    }
    if (!wsUrl) throw new Error("inspector URL never observed. raw tail: " + raw.join("").slice(-2000));

    // The inspector banner can print a moment before the WebSocket listener actually accepts
    // connections (observed empirically: a bare `new WebSocket(wsUrl)` right after the banner
    // match fails with "Failed to connect" on the first attempt, even across ten retries with a
    // 300ms backoff between them; a single flat 500ms settle before the FIRST attempt was what
    // actually made the difference in isolation). Settle once, then retry the connect itself as
    // a second line of defense.
    await sleep(500);
    const session = await connectCdpWithRetry(wsUrl, 10, 300);
    try {
      await session.send("Runtime.enable");

      const readyDeadline = Date.now() + 20_000;
      while (Date.now() < readyDeadline) {
        if (raw.join("").includes(READY_OSC)) break;
        if (exitObserved) throw new Error("child exited: " + raw.join("").slice(-2000));
        await sleep(200);
      }

      await session.evaluate(IMPORT_JSC_EXPR, true);

      await sleep(opts.settleMs);

      const windowStartMs = Date.now();
      const floorStart = await session.evaluate(FORCE_GC_AND_READ_FLOOR_EXPR);
      if (floorStart.wasThrown || typeof floorStart.value !== "number") {
        throw new Error("forced-GC floor read (start) failed: " + JSON.stringify(floorStart.raw).slice(0, 500));
      }

      const rssSamples: RssSample[] = [];
      const windowDeadline = windowStartMs + opts.durationMs;
      while (Date.now() < windowDeadline) {
        const r = await session.evaluate(MEMORY_USAGE_EXPR);
        if (!r.wasThrown && typeof r.value === "string") {
          const mem = JSON.parse(r.value);
          rssSamples.push({ t: Date.now(), ...mem });
        }
        const remaining = windowDeadline - Date.now();
        if (remaining <= 0) break;
        await sleep(Math.min(opts.sampleIntervalMs, remaining));
      }

      const floorEnd = await session.evaluate(FORCE_GC_AND_READ_FLOOR_EXPR);
      if (floorEnd.wasThrown || typeof floorEnd.value !== "number") {
        throw new Error("forced-GC floor read (end) failed: " + JSON.stringify(floorEnd.raw).slice(0, 500));
      }
      const windowEndMs = Date.now();

      return {
        rssSamples,
        jsHeapFloorStartBytes: floorStart.value,
        jsHeapFloorEndBytes: floorEnd.value,
        windowStartMs,
        windowEndMs,
      };
    } finally {
      session.close();
    }
  } finally {
    if (child.pid) {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    }
    rmSync(home, { recursive: true, force: true });
  }
}
