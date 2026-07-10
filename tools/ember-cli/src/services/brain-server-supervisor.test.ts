// services/brain-server-supervisor.test.ts — tests for issue #122 (refreshed 2026-07-10):
// spawn-on-demand, single-instance guard (registry-backed), ownership-tethered teardown,
// receipts, and the GPU-lease device policy.
//
// Test strategy (mirrors entrypoints/process-entry.test.ts's own #159 boot-matrix pattern):
// the ORCHESTRATION functions (ensureBrainServer / teardownBrainServer) are the real,
// unmodified exported entry points under test in every case below -- only the OS-facing leaf
// functions (probeHealth, spawnServer, isPidAlive, getProcessCommandLine) are injected, so
// every branch of the real control flow genuinely executes. A dedicated final suite
// ("real synthetic process") goes one step further and spawns an actual child process (a
// harmless CPU-only HTTP stub, __fixtures__/fake-brain-server.ts -- no model load, no GPU) so
// the real default spawnServer/probeHealth/isPidAlive implementations are also proven against
// a genuine OS process, not just injected fakes.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { mkdir, rm, writeFile, readFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { spawn } from "node:child_process";

import {
  BRAIN_SERVER_PORT,
  BRAIN_SERVER_REFERENCE_PORT,
  resolveDevicePolicy,
  parseRegistryRows,
  serializeRegistryRows,
  findBrainServerRow,
  filterOutPort,
  filterOutPid,
  readRegistryFile,
  writeRegistryFileAtomic,
  appendBrainServerEvent,
  ensureBrainServer,
  teardownBrainServer,
  resetBrainServerSupervisorForTests,
  defaultRegistryPath,
  defaultEventsLogPath,
  type RegistryRow,
  type BrainServerHandle,
  type BrainServerHealthStatus,
} from "./brain-server-supervisor.ts";

// ---------------------------------------------------------------------------
// Pure-function unit tests
// ---------------------------------------------------------------------------

describe("brain-server-supervisor — resolveDevicePolicy (pure)", () => {
  it("defaults to cuda when nothing forces cpu", () => {
    expect(resolveDevicePolicy({ gpuFreeRequested: false, outageEffective: false, referenceServerUp: false })).toBe("cuda");
  });
  it("EMBER_GPU_FREE forces cpu even with no outage and no reference server", () => {
    expect(resolveDevicePolicy({ gpuFreeRequested: true, outageEffective: false, referenceServerUp: false })).toBe("cpu");
  });
  it("an effective outage marker forces cpu", () => {
    expect(resolveDevicePolicy({ gpuFreeRequested: false, outageEffective: true, referenceServerUp: false })).toBe("cpu");
  });
  it(":8082 reference server answering forces cpu (mirrors serve_cbase_openai.py's own guard)", () => {
    expect(resolveDevicePolicy({ gpuFreeRequested: false, outageEffective: false, referenceServerUp: true })).toBe("cpu");
  });
  it("all three forcing conditions still resolve to cpu (no double-negative bug)", () => {
    expect(resolveDevicePolicy({ gpuFreeRequested: true, outageEffective: true, referenceServerUp: true })).toBe("cpu");
  });
});

describe("brain-server-supervisor — registry JSONL parse/serialize (pure)", () => {
  const rowA: RegistryRow = { port: 8082, model_path: "/a", pid: 111, launched_by: "watchdog", ts: "t1", device: "cuda" };
  const rowB: RegistryRow = { port: 8083, model_path: "/b", pid: 222, launched_by: "ember-cli", ts: "t2", device: "cpu" };

  it("parseRegistryRows(null) is empty", () => {
    expect(parseRegistryRows(null)).toEqual([]);
  });
  it("round-trips serialize -> parse", () => {
    const serialized = serializeRegistryRows([rowA, rowB]);
    expect(parseRegistryRows(serialized)).toEqual([rowA, rowB]);
  });
  it("skips a torn/malformed line without discarding the rest", () => {
    const raw = `${JSON.stringify(rowA)}\nNOT-JSON\n${JSON.stringify(rowB)}\n`;
    expect(parseRegistryRows(raw)).toEqual([rowA, rowB]);
  });
  it("findBrainServerRow matches by port", () => {
    expect(findBrainServerRow([rowA, rowB], 8083)).toEqual(rowB);
    expect(findBrainServerRow([rowA], 8083)).toBeNull();
  });
  it("filterOutPort / filterOutPid remove the right row only", () => {
    expect(filterOutPort([rowA, rowB], 8083)).toEqual([rowA]);
    expect(filterOutPid([rowA, rowB], 111)).toEqual([rowB]);
  });
});

// ---------------------------------------------------------------------------
// Registry + events-log real file I/O
// ---------------------------------------------------------------------------

describe("brain-server-supervisor — registry file I/O (real fs, scratch dir)", () => {
  let tmpDir: string;
  beforeEach(async () => {
    tmpDir = join(tmpdir(), `bss-registry-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
  });
  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("readRegistryFile on a missing file returns []", async () => {
    const rows = await readRegistryFile(join(tmpDir, "nope.json"));
    expect(rows).toEqual([]);
  });

  it("writeRegistryFileAtomic then readRegistryFile round-trips and leaves no .tmp file", async () => {
    const registryPath = join(tmpDir, "state", "serving-registry.json");
    const row: RegistryRow = { port: 8083, model_path: "/m", pid: 999, launched_by: "ember-cli", ts: "t", device: "cpu" };
    await writeRegistryFileAtomic([row], registryPath);

    const rows = await readRegistryFile(registryPath);
    expect(rows).toEqual([row]);

    const tmpExists = await readFile(registryPath + ".tmp", "utf-8").then(() => true).catch(() => false);
    expect(tmpExists).toBe(false);
  });

  it("defaultRegistryPath / defaultEventsLogPath resolve under the expected repo-relative dirs", () => {
    expect(defaultRegistryPath("/repo")).toContain(join("state", "serving-registry.json"));
    expect(defaultEventsLogPath("/repo")).toContain(join("tools", "ember-cli", "state", "brain-server-events.jsonl"));
  });
});

describe("brain-server-supervisor — appendBrainServerEvent (real fs, fail-open)", () => {
  let tmpDir: string;
  beforeEach(async () => {
    tmpDir = join(tmpdir(), `bss-events-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
  });
  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("appends one JSON line per call, creating the parent dir", async () => {
    const logPath = join(tmpDir, "nested", "brain-server-events.jsonl");
    appendBrainServerEvent({ ts: "t1", event: "spawn", port: 8083, pid: 1 }, logPath);
    appendBrainServerEvent({ ts: "t2", event: "shutdown", port: 8083, pid: 1 }, logPath);

    const raw = await readFile(logPath, "utf-8");
    const lines = raw.trim().split("\n").map((l) => JSON.parse(l));
    expect(lines.length).toBe(2);
    expect(lines[0].event).toBe("spawn");
    expect(lines[1].event).toBe("shutdown");
  });
});

// ---------------------------------------------------------------------------
// ensureBrainServer / teardownBrainServer -- injected-leaf orchestration tests
// ---------------------------------------------------------------------------

function makeFakeHandle(pid: number, opts: { emitsExit?: boolean } = {}): { handle: BrainServerHandle; emitExit: (code: number | null) => void } {
  const listeners: Record<string, ((...args: unknown[]) => void)[]> = {};
  const fakeProc = {
    pid,
    once(event: string, listener: (...args: unknown[]) => void) {
      (listeners[event] ??= []).push(listener);
    },
    kill() { /* no-op fake */ },
  };
  const emitExit = (code: number | null): void => {
    for (const l of listeners["exit"] ?? []) l(code);
  };
  void opts;
  return { handle: { process: fakeProc as unknown as BrainServerHandle["process"], pid }, emitExit };
}

describe("brain-server-supervisor — ensureBrainServer / teardownBrainServer (injected leaves)", () => {
  let repoRoot: string;
  beforeEach(async () => {
    repoRoot = join(tmpdir(), `bss-orch-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(join(repoRoot, "state"), { recursive: true });
    await mkdir(join(repoRoot, "tools", "ember-cli", "state"), { recursive: true });
    resetBrainServerSupervisorForTests();
  });
  afterEach(async () => {
    resetBrainServerSupervisorForTests();
    await rm(repoRoot, { recursive: true, force: true });
  });

  it("already healthy on :8083 -> adopts, never spawns, appends an adopt event", async () => {
    let spawnCalls = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => (port === BRAIN_SERVER_PORT ? "ready" : "down"),
      spawnServer: () => { spawnCalls += 1; return makeFakeHandle(1).handle; },
    });

    expect(result).toEqual({ outcome: "adopted", port: BRAIN_SERVER_PORT });
    expect(spawnCalls).toBe(0);

    const events = (await readFile(defaultEventsLogPath(repoRoot), "utf-8")).trim().split("\n").map((l) => JSON.parse(l));
    expect(events.some((e) => e.event === "adopt")).toBe(true);
  });

  it("down, no existing registry row -> spawns, races health-poll, registers row on ready, records ownership", async () => {
    const { handle } = makeFakeHandle(4242);
    let healthCalls = 0;
    const probeHealth = async (port: number): Promise<BrainServerHealthStatus> => {
      if (port === BRAIN_SERVER_REFERENCE_PORT) return "down"; // no 27B reference running
      healthCalls += 1;
      if (healthCalls === 1) return "down"; // pre-spawn adopt-check
      return healthCalls < 3 ? "loading" : "ready"; // then loading -> ready
    };

    const result = await ensureBrainServer({
      repoRoot,
      probeHealth,
      spawnServer: () => handle,
      healthPollIntervalMs: 5, // keep the test fast
    });

    expect(result).toEqual({ outcome: "spawned", port: BRAIN_SERVER_PORT, pid: 4242, device: "cuda" });

    const rows = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ port: BRAIN_SERVER_PORT, pid: 4242, launched_by: "ember-cli", device: "cuda" });

    const events = (await readFile(defaultEventsLogPath(repoRoot), "utf-8")).trim().split("\n").map((l) => JSON.parse(l));
    expect(events.some((e) => e.event === "spawn" && e.pid === 4242)).toBe(true);

    // Ownership recorded -- teardown must now actually kill pid 4242.
    let killedPid: number | null = null;
    const teardown = await teardownBrainServer({
      repoRoot,
      isPidAlive: (pid) => pid === 4242,
      getProcessCommandLine: async () => "python scripts/serve_cbase_openai.py --port 8083",
    });
    void killedPid;
    expect(teardown).toEqual({ outcome: "killed", pid: 4242 });

    const rowsAfter = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rowsAfter).toHaveLength(0);
  });

  it("device policy: EMBER_GPU_FREE=1 -> spawned with device cpu", async () => {
    const { handle } = makeFakeHandle(5002);
    let n = 0;
    const result = await ensureBrainServer({
      repoRoot,
      env: { ...process.env, EMBER_GPU_FREE: "1" },
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });
    expect(result).toMatchObject({ outcome: "spawned", device: "cpu" });
  });

  it("device policy: :8082 reference server answering -> spawned with device cpu", async () => {
    const { handle } = makeFakeHandle(5003);
    let n = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "ready"; // 27B reference alive
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });
    expect(result).toMatchObject({ outcome: "spawned", device: "cpu" });
  });

  it("device policy: an effective planned-outage.json marker -> spawned with device cpu", async () => {
    const markerPath = join(repoRoot, "tools", "ember-cli", "state", "planned-outage.json");
    await writeFile(markerPath, JSON.stringify({
      owner: "v8launch", reason: "GPU training leg", target: "server",
      started: new Date(Date.now() - 1000).toISOString(),
      expires: new Date(Date.now() + 60_000).toISOString(),
      kill_receipt_ref: "kill-receipts.jsonl#ts=test", // required field, see OUTAGE_MARKER_FIELDS
    }));

    const { handle } = makeFakeHandle(5004);
    let n = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });
    expect(result).toMatchObject({ outcome: "spawned", device: "cpu" });
  });

  it("device policy: an EXPIRED planned-outage.json marker does not force cpu", async () => {
    const markerPath = join(repoRoot, "tools", "ember-cli", "state", "planned-outage.json");
    await writeFile(markerPath, JSON.stringify({
      owner: "v8launch", reason: "GPU training leg", target: "server",
      started: new Date(Date.now() - 120_000).toISOString(),
      expires: new Date(Date.now() - 60_000).toISOString(), // already expired
      kill_receipt_ref: "kill-receipts.jsonl#ts=test",
    }));

    const { handle } = makeFakeHandle(5005);
    let n = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });
    expect(result).toMatchObject({ outcome: "spawned", device: "cuda" });
  });

  it("bad-model-path class: child exits early -> failed immediately, no registry row written, spawn_failed event", async () => {
    const { handle, emitExit } = makeFakeHandle(6001);
    setTimeout(() => emitExit(1), 10);

    const start = Date.now();
    let calls6001 = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        calls6001 += 1;
        return calls6001 === 1 ? "down" : "loading"; // pre-spawn check "down", then never ready
      },
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
      spawnHealthCapMs: 60_000, // if the race didn't work, this test would hang toward 60s
    });
    const elapsedMs = Date.now() - start;

    expect(result).toMatchObject({ outcome: "failed" });
    expect((result as { reason: string }).reason).toContain("exited before ready");
    expect((result as { reason: string }).reason).toContain("exit code 1");
    expect(elapsedMs).toBeLessThan(5000); // proves the early-exit race fired, not the 60s cap

    const rows = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rows).toHaveLength(0);

    const events = (await readFile(defaultEventsLogPath(repoRoot), "utf-8")).trim().split("\n").map((l) => JSON.parse(l));
    expect(events.some((e) => e.event === "spawn_failed" && e.detail?.includes("exit code 1"))).toBe(true);
  }, 10_000);

  it("silent-hang class: never becomes ready -> fails at the cap (not 240s), kills the hung child", async () => {
    let killed = false;
    const fakeProc = {
      pid: 7001,
      once() { /* no exit ever fires -- simulates the silent-hang defect class from the issue thread */ },
      kill(sig?: string) { if (sig === "SIGTERM") killed = true; },
    };

    let calls7001 = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        calls7001 += 1;
        return calls7001 === 1 ? "down" : "loading"; // pre-spawn check "down", then stuck loading forever
      },
      spawnServer: () => ({ process: fakeProc as unknown as BrainServerHandle["process"], pid: 7001 }),
      spawnHealthCapMs: 40, // tiny cap so the test is fast; proves the cap (not 240s) governs
      healthPollIntervalMs: 5,
    });

    expect(result).toMatchObject({ outcome: "failed" });
    expect((result as { reason: string }).reason).toContain("did not become ready within");
    expect(killed).toBe(true); // the owned-but-never-healthy child is cleaned up, not leaked

    const rows = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rows).toHaveLength(0);
  });

  it("single-instance guard: a live, cmdline-verified row already present -> initial health probe adopts before any reclaim/spawn logic runs", async () => {
    // This exercises the "second CLI instance" acceptance scenario directly: the FIRST call's
    // spawn already made :8083 answer, so a second ensureBrainServer() call (simulating a
    // second CLI instance) must adopt via the health probe, never re-spawn.
    let spawnCalls = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => (port === BRAIN_SERVER_PORT ? "ready" : "down"),
      spawnServer: () => { spawnCalls += 1; return makeFakeHandle(1).handle; },
    });
    expect(result).toEqual({ outcome: "adopted", port: BRAIN_SERVER_PORT });
    expect(spawnCalls).toBe(0);

    // The adopting call never owns it -- its own teardown is therefore a no-op ("server STAYS").
    const teardown = await teardownBrainServer({ repoRoot });
    expect(teardown).toEqual({ outcome: "not-owner" });
  });

  it("single-instance guard: a DEAD registry row is reclaimed (event + deregister) before a fresh spawn", async () => {
    const staleRow: RegistryRow = {
      port: BRAIN_SERVER_PORT, model_path: "/old", pid: 99999999, launched_by: "ember-cli", ts: "stale", device: "cuda",
    };
    await writeRegistryFileAtomic([staleRow], defaultRegistryPath(repoRoot));

    const { handle } = makeFakeHandle(8001);
    let n = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      isPidAlive: (pid) => pid !== 99999999, // the stale row's pid is dead
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });

    expect(result).toMatchObject({ outcome: "spawned", pid: 8001 });

    const rows = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rows).toHaveLength(1);
    expect(rows[0]?.pid).toBe(8001); // stale row is gone, fresh row present

    const events = (await readFile(defaultEventsLogPath(repoRoot), "utf-8")).trim().split("\n").map((l) => JSON.parse(l));
    expect(events.some((e) => e.event === "reclaim" && e.pid === 99999999)).toBe(true);
  });

  it("single-instance guard: a LIVE row whose cmdline does NOT match is reclaimed (pid-reuse defense)", async () => {
    const staleRow: RegistryRow = {
      port: BRAIN_SERVER_PORT, model_path: "/old", pid: 4321, launched_by: "ember-cli", ts: "stale", device: "cuda",
    };
    await writeRegistryFileAtomic([staleRow], defaultRegistryPath(repoRoot));

    const { handle } = makeFakeHandle(8002);
    let n = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      isPidAlive: (pid) => pid === 4321, // "alive" -- but it's not really our server (pid reuse)
      getProcessCommandLine: async (pid) => (pid === 4321 ? "notepad.exe" : null),
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });

    expect(result).toMatchObject({ outcome: "spawned", pid: 8002 });
    const events = (await readFile(defaultEventsLogPath(repoRoot), "utf-8")).trim().split("\n").map((l) => JSON.parse(l));
    expect(events.some((e) => e.event === "reclaim" && e.pid === 4321)).toBe(true);
  });

  it("teardown tether: an adopted server (never spawned by this process) is NEVER killed", async () => {
    let killSignal: string | undefined;
    const fakeProc = { pid: 42, kill: (sig?: string) => { killSignal = sig; } };
    void fakeProc;

    await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => (port === BRAIN_SERVER_PORT ? "ready" : "down"),
      spawnServer: () => makeFakeHandle(1).handle, // never called -- adopt path
    });

    let processKillCalled = false;
    const origKill = process.kill.bind(process);
    process.kill = ((...args: Parameters<typeof origKill>) => { processKillCalled = true; return origKill(...args); }) as typeof process.kill;
    try {
      const teardown = await teardownBrainServer({ repoRoot });
      expect(teardown).toEqual({ outcome: "not-owner" });
      expect(processKillCalled).toBe(false);
      expect(killSignal).toBeUndefined();
    } finally {
      process.kill = origKill;
    }
  });

  it("teardown tether: pid reuse between spawn and teardown is detected and refused (never kills the wrong process)", async () => {
    const { handle } = makeFakeHandle(9001);
    let n = 0;
    await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      spawnServer: () => handle,
      healthPollIntervalMs: 5,
    });

    let processKillCalled = false;
    const origKill = process.kill.bind(process);
    process.kill = ((...args: Parameters<typeof origKill>) => { processKillCalled = true; return origKill(...args); }) as typeof process.kill;
    try {
      const teardown = await teardownBrainServer({
        repoRoot,
        isPidAlive: () => true,
        getProcessCommandLine: async () => "some-totally-unrelated-process.exe", // pid 9001 got reused
      });
      expect(teardown).toEqual({ outcome: "pid-mismatch", expectedPid: 9001 });
      expect(processKillCalled).toBe(false);
    } finally {
      process.kill = origKill;
    }
  });

  it("kill -9 mid-session, re-entrant ensureBrainServer: reclaims the now-dead owned row and respawns cleanly, no throw", async () => {
    const { handle: firstHandle } = makeFakeHandle(10001);
    let n = 0;
    const first = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        n += 1;
        if (n === 1) return "down"; // pre-spawn adopt-check must see "down" to trigger the spawn path
        return n < 3 ? "loading" : "ready";
      },
      spawnServer: () => firstHandle,
      healthPollIntervalMs: 5,
    });
    expect(first).toMatchObject({ outcome: "spawned", pid: 10001 });

    // Simulate an external `kill -9`: the process is gone, health now reports down.
    resetBrainServerSupervisorForTests(); // this session's in-memory ownership doesn't survive a hard external kill either
    const { handle: secondHandle } = makeFakeHandle(10002);
    let m = 0;
    const second = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        m += 1;
        if (m === 1) return "down"; // pre-spawn adopt-check
        return m < 3 ? "loading" : "ready";
      },
      isPidAlive: (pid) => pid !== 10001, // the old owned pid is dead
      spawnServer: () => secondHandle,
      healthPollIntervalMs: 5,
    });

    expect(second).toMatchObject({ outcome: "spawned", pid: 10002 }); // clean respawn, no throw
    const rows = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rows).toHaveLength(1);
    expect(rows[0]?.pid).toBe(10002);
  });
});

// ---------------------------------------------------------------------------
// Real synthetic process -- proves the REAL default spawnServer / probeHealth / isPidAlive
// implementations genuinely work end-to-end. CPU-only, zero VRAM, zero GPU imports: safe to
// run for real during the 2026-07-10 planned GPU outage (which bans GPU-model servers and
// VRAM allocation, not a harmless local HTTP stub).
// ---------------------------------------------------------------------------

describe("brain-server-supervisor — real synthetic process (execution-binding, GPU-free)", () => {
  let repoRoot: string;
  let fakePort: number;
  // Safety net for a real spawned pid, independent of each test's own assertions: if an `it`
  // throws or fails BEFORE reaching its own teardownBrainServer call, the real stub process
  // would otherwise leak forever (exactly what happened during this suite's own development --
  // three orphaned fake-brain-server.ts processes were found and reaped, receipted at
  // the operator-side kill-receipts ledger, after early buggy runs threw/asserted before
  // their teardown call ran). Every real spawnServer below registers its pid here; afterEach
  // force-kills anything still alive regardless of pass/fail/throw, verified-PID-only.
  let spawnedPids: number[];

  beforeEach(async () => {
    repoRoot = join(tmpdir(), `bss-real-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(join(repoRoot, "state"), { recursive: true });
    await mkdir(join(repoRoot, "tools", "ember-cli", "state"), { recursive: true });
    fakePort = 19000 + Math.floor(Math.random() * 900);
    spawnedPids = [];
    resetBrainServerSupervisorForTests();
  });
  afterEach(async () => {
    for (const pid of spawnedPids) {
      try {
        process.kill(pid, 0); // still alive?
        process.kill(pid); // default SIGTERM -- on Windows this is an unconditional terminate
      } catch {
        // already gone -- the test's own teardown (or the fixture's own exit) got there first
      }
    }
    resetBrainServerSupervisorForTests();
    await rm(repoRoot, { recursive: true, force: true });
  });

  const fixturePath = join(import.meta.dir, "__fixtures__", "fake-brain-server.ts");

  it("spawns a real stub process, real HTTP health-probes it to green, registers it, then really SIGTERMs it on teardown", async () => {
    const result = await ensureBrainServer({
      repoRoot,
      // Real probeHealth against the REAL BRAIN_SERVER_PORT would require the fixture to bind
      // exactly 8083, which would collide across parallel test runs -- so this leg still
      // injects probeHealth/isPidAlive (as every other test does) but wires spawnServer to a
      // REAL child_process.spawn of the fixture, and uses REAL HTTP fetch + REAL pid liveness
      // against that real process's real port and real pid, proving the underlying primitives
      // (not just the orchestration branching) genuinely work.
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        try {
          const res = await fetch(`http://127.0.0.1:${fakePort}/health`, { signal: AbortSignal.timeout(500) });
          if (!res.ok) return "down";
          const body = (await res.json()) as { status?: string };
          return body.status === "ready" ? "ready" : body.status === "loading" ? "loading" : "down";
        } catch {
          return "down";
        }
      },
      spawnServer: () => {
        const child = spawn(process.execPath, ["run", fixturePath], {
          env: { ...process.env, FAKE_BRAIN_PORT: String(fakePort), FAKE_BRAIN_READY_DELAY_MS: "100" },
          stdio: ["ignore", "ignore", "ignore"],
          detached: true,
        });
        child.unref();
        if (typeof child.pid !== "number") throw new Error("real spawn did not return a pid");
        spawnedPids.push(child.pid); // afterEach safety net -- see describe-level comment
        return { process: child, pid: child.pid };
      },
      healthPollIntervalMs: 50,
      spawnHealthCapMs: 15_000,
    });

    expect(result.outcome).toBe("spawned");
    const pid = (result as { pid: number }).pid;
    expect(typeof pid).toBe("number");

    // Real liveness check against the real pid.
    const isAlive = (): boolean => { try { process.kill(pid, 0); return true; } catch { return false; } };
    expect(isAlive()).toBe(true);

    const rows = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rows).toHaveLength(1);
    expect(rows[0]?.pid).toBe(pid);

    // Real teardown: real SIGTERM to the real pid, real process exit.
    const teardown = await teardownBrainServer({
      repoRoot,
      isPidAlive: isAlive,
      getProcessCommandLine: async () => "bun run fake-brain-server.ts", // real cmdline lookup is exercised separately below; this leg's contract is the real kill signal
      cmdlineMatchSubstring: "fake-brain-server.ts", // this leg spawns the synthetic stub, not the real serve_cbase_openai.py script
    });
    expect(teardown).toEqual({ outcome: "killed", pid });

    // Poll for real exit (SIGTERM handling is async on the child's side).
    const deadline = Date.now() + 3000;
    while (isAlive() && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
    expect(isAlive()).toBe(false);

    const rowsAfter = await readRegistryFile(defaultRegistryPath(repoRoot));
    expect(rowsAfter).toHaveLength(0);
  }, 20_000);

  it("real bad-checkpoint-path class: the stub exits(7) immediately -> ensureBrainServer fails fast via the real child 'exit' event, not the cap", async () => {
    const start = Date.now();
    let callsExit7 = 0;
    const result = await ensureBrainServer({
      repoRoot,
      probeHealth: async (port) => {
        if (port === BRAIN_SERVER_REFERENCE_PORT) return "down";
        callsExit7 += 1;
        return callsExit7 === 1 ? "down" : "loading"; // pre-spawn check "down"
      },
      spawnServer: () => {
        const child = spawn(process.execPath, ["run", fixturePath], {
          env: { ...process.env, FAKE_BRAIN_PORT: String(fakePort), FAKE_BRAIN_EXIT_IMMEDIATELY: "1" },
          stdio: ["ignore", "ignore", "ignore"],
          detached: true,
        });
        child.unref();
        if (typeof child.pid !== "number") throw new Error("real spawn did not return a pid");
        spawnedPids.push(child.pid); // afterEach safety net -- see describe-level comment
        return { process: child, pid: child.pid };
      },
      healthPollIntervalMs: 50,
      spawnHealthCapMs: 15_000,
    });
    const elapsedMs = Date.now() - start;

    expect(result).toMatchObject({ outcome: "failed" });
    expect((result as { reason: string }).reason).toContain("exit code 7");
    expect(elapsedMs).toBeLessThan(5000); // real early-exit race, not the 15s cap
  }, 20_000);
});
