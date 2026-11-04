// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #2378 regression tests, through main(): closing ember stops the model server it SPAWNED and the
// one it ADOPTED, a server shared by two instances survives the first exit, a crash-stale lease is
// recovered, and the self-heal supervisor does not respawn once exit began.  No real model server,
// no real process: the machine is FakeWorld and "exit" is ServerLeases.releaseSync(), the function
// every real exit path (exit, SIGINT/SIGTERM/SIGHUP, the reaper) calls.

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { EventEmitter } from "node:events";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { _resetConfigHomeMemo } from "../utils/env-detection.ts";
import { _resetInitForTests } from "./session-init.ts";
import { FakeWorld } from "../services/server-lease.fakes.ts";
import { LeaseStore, ServerLeases } from "../services/server-lease.ts";
import { main, resolveServerPort, type ServerHandle, type ServerSpawnOptions } from "./process-entry.ts";
import type { LoopDeps } from "../query/query-loop-support.ts";

const ENV_KEYS = ["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME", "EMBER_OPEN_WEIGHTS", "EMBER_OPEN_WEIGHTS_ACTIVE"];

let tmpDir: string;
let leaseDir: string;
let saved: Record<string, string | undefined>;
let world: FakeWorld;
let store: LeaseStore;
let fakeBinary: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "pe-2378-"));
  leaseDir = join(tmpDir, "leases");
  saved = {};
  for (const k of ENV_KEYS) saved[k] = process.env[k];
  delete process.env["EMBER_MODEL_URL"];
  delete process.env["EMBER_MODEL_NAME"];
  delete process.env["EMBER_OPEN_WEIGHTS"];
  process.env["EMBER_HOME"] = tmpDir;
  _resetConfigHomeMemo();
  _resetInitForTests();
  // The bare preflight needs files that exist; absolute paths bypass the runtime directory.
  fakeBinary = join(tmpDir, "llama-server.exe");
  const fakeModel = join(tmpDir, "fake-model.gguf");
  writeFileSync(fakeBinary, "");
  writeFileSync(fakeModel, "");
  writeFileSync(join(tmpDir, "models.json"), JSON.stringify({ binary: fakeBinary, model: fakeModel }));
  world = new FakeWorld();
  store = new LeaseStore(leaseDir, () => {});
});

afterEach(() => {
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  _resetConfigHomeMemo();
  rmSync(tmpDir, { recursive: true, force: true });
});

function leasesFor(selfPid: number): { leases: ServerLeases; hooksInstalled: () => number } {
  world.addProcess(selfPid, "bun run main.ts");
  const leases = new ServerLeases({ ops: world.ops(selfPid), store });
  let installs = 0;
  // Never register handlers on the test runner itself; count the request instead.
  leases.installExitHooks = () => { installs++; };
  return { leases, hooksInstalled: () => installs };
}

function fakeDeps(): LoopDeps {
  return {
    callModel: async () => { throw new Error("not expected"); },
    microcompact: async (msgs) => msgs,
    autocompact: async () => {},
    generateUuid: () => "test-uuid",
    sleep: async () => {},
  };
}

function fakeServerHandle(pid: number, port: number): ServerHandle {
  const proc = Object.assign(new EventEmitter(), { pid });
  return { process: proc as unknown as ServerHandle["process"], port, kill() {} };
}

async function runMain(argv: string[], over: Parameters<typeof main>[0]): Promise<void> {
  await main({
    argv: ["node", "ember", ...argv, "-p", "hello"],
    waitReady: async () => {},
    initFn: async () => {},
    getLoopDepsFn: fakeDeps,
    headlessRunner: async () => ({ events: [], exitCode: 0 }),
    exitFn: () => {},
    ...over,
  });
}

describe("adopt-then-exit (#2378): a server ember attached to is stopped on exit", () => {
  it("records the adopted server as owned and stops that verified PID when the instance exits", async () => {
    let askedPort = 0;
    world.addProcess(500, () => `"C:\\llama\\llama-server.exe" --model m.gguf --port ${askedPort}`);
    world.anyPortListener = 500;
    const ops = world.ops(100);
    const real = ops.listenerPid;
    ops.listenerPid = (p) => { askedPort = p; return real(p); };
    world.addProcess(100, "bun run main.ts");
    const leases = new ServerLeases({ ops, store });
    let hooks = 0;
    leases.installExitHooks = () => { hooks++; };

    await runMain(["--reference-seat"], {
      probeExisting: async () => true,
      spawnServer: async () => { throw new Error("an already-running server must be adopted, not spawned over"); },
      serverLeases: leases,
    });

    const lease = store.read(askedPort)!;
    expect(lease.server).toMatchObject({ pid: 500, origin: "adopted" });
    expect(lease.holders.map((h) => h.pid)).toEqual([100]);
    expect(hooks).toBe(1);
    expect(world.killed).toEqual([]); // still running while ember runs

    leases.releaseSync(); // what every exit path calls
    expect(world.killed).toEqual([500]);
    expect(store.read(askedPort)).toBeNull();
  });

  it("leaves a listener alone when it is not a llama-server on that port (never stops by guess)", async () => {
    world.addProcess(500, "C:\\apps\\some-other-server.exe --port 9");
    world.anyPortListener = 500;
    const { leases, hooksInstalled } = leasesFor(100);
    await runMain(["--reference-seat"], {
      probeExisting: async () => true,
      spawnServer: async () => { throw new Error("must not spawn"); },
      serverLeases: leases,
    });
    expect(hooksInstalled()).toBe(0);
    leases.releaseSync();
    expect(world.killed).toEqual([]);
    expect(world.isAlive(500)).toBe(true);
  });
});

describe("spawn-then-exit (#2378): a server ember started is stopped on exit", () => {
  it("records every spawn and stops the live one when the instance exits", async () => {
    const { leases, hooksInstalled } = leasesFor(100);
    let spawnedPort = 0;
    await runMain(["--reference-seat"], {
      probeExisting: async () => false,
      spawnServer: async (so: ServerSpawnOptions) => {
        spawnedPort = so.port;
        world.llamaServer(600, so.port, so.binaryPath);
        return fakeServerHandle(600, so.port);
      },
      serverLeases: leases,
    });
    expect(store.read(spawnedPort)!.server).toMatchObject({ pid: 600, origin: "spawned" });
    expect(hooksInstalled()).toBe(1);
    leases.releaseSync();
    expect(world.killed).toEqual([600]);
    expect(store.read(spawnedPort)).toBeNull();
  });

  it("the self-heal supervisor does not respawn after exit began, and exit stops the server", async () => {
    const { leases } = leasesFor(100);
    let spawns = 0;
    let handle!: ServerHandle;
    await runMain(["--open-weights"], {
      probeExisting: async () => false,
      spawnServer: async (so: ServerSpawnOptions) => {
        spawns++;
        world.llamaServer(600 + spawns, so.port, so.binaryPath);
        handle = fakeServerHandle(600 + spawns, so.port);
        return handle;
      },
      serverLeases: leases,
    });
    expect(spawns).toBe(1);

    leases.releaseSync(); // exit began: supervisor detached first, then the server is stopped
    expect(world.killed).toEqual([601]);
    handle.process.emit("exit", 1); // the stop makes the server's exit event fire
    await new Promise((r) => setTimeout(r, 20));
    expect(spawns).toBe(1); // no respawn
  });

  it("without exit, a server that dies mid-session is still respawned and the NEW one is the one stopped", async () => {
    const { leases } = leasesFor(100);
    let spawns = 0;
    let first!: ServerHandle;
    await runMain(["--open-weights"], {
      probeExisting: async () => false,
      spawnServer: async (so: ServerSpawnOptions) => {
        spawns++;
        world.llamaServer(600 + spawns, so.port, so.binaryPath);
        const h = fakeServerHandle(600 + spawns, so.port);
        if (spawns === 1) first = h;
        return h;
      },
      serverLeases: leases,
    });
    world.die(601);
    first.process.emit("exit", 1);
    await new Promise((r) => setTimeout(r, 50));
    expect(spawns).toBe(2);
    leases.releaseSync();
    expect(world.killed).toEqual([602]);
  });
});

describe("two ember instances on one server (#2378)", () => {
  it("the first exit keeps the server; the last exit stops it", async () => {
    const a = leasesFor(100);
    const b = leasesFor(101);
    let port = 0;
    await runMain(["--reference-seat"], {
      probeExisting: async () => false,
      spawnServer: async (so: ServerSpawnOptions) => {
        port = so.port;
        world.llamaServer(600, so.port, so.binaryPath);
        return fakeServerHandle(600, so.port);
      },
      serverLeases: a.leases,
    });
    world.listeners.set(port, 600);
    delete process.env["EMBER_MODEL_URL"]; // main() of the first instance exported it; a second process would not inherit it
    await runMain(["--reference-seat"], {
      probeExisting: async () => true,
      spawnServer: async () => { throw new Error("second instance must adopt"); },
      serverLeases: b.leases,
    });
    expect(store.read(port)!.holders.map((h) => h.pid).sort()).toEqual([100, 101]);

    a.leases.releaseSync(); // the instance that SPAWNED it leaves first
    expect(world.isAlive(600)).toBe(true);
    expect(world.killed).toEqual([]);

    b.leases.releaseSync();
    expect(world.killed).toEqual([600]);
    expect(store.read(port)).toBeNull();
  });
});

describe("crash recovery on next start (#2378)", () => {
  it("a stale lease whose holders are dead and whose server is not answering is stopped before spawning", async () => {
    const port = await resolveServerPort(dirname(process.execPath));
    world.llamaServer(500, port);
    store.write(port, {
      version: 1, port, reaper: null,
      server: { pid: 500, startTime: world.ops(0).identify(500)!.startTime, cmdline: world.ops(0).identify(500)!.cmdline, origin: "adopted" },
      holders: [{ pid: 77, startTime: "5" }], // the crashed instance
    });
    const { leases } = leasesFor(100);
    await runMain(["--reference-seat"], {
      probeExisting: async () => false,
      spawnServer: async (so: ServerSpawnOptions) => {
        // the orphan was stopped BEFORE this spawn, so the port is free to bind
        expect(world.killed).toEqual([500]);
        world.llamaServer(600, so.port, so.binaryPath);
        return fakeServerHandle(600, so.port);
      },
      serverLeases: leases,
    });
    leases.releaseSync();
    expect(world.killed).toEqual([500, 600]);
  });

  it("a stale lease whose server DOES answer is adopted and owned, so this instance's exit frees it", async () => {
    const port = await resolveServerPort(dirname(process.execPath));
    world.llamaServer(500, port);
    world.listeners.set(port, 500);
    const id = world.ops(0).identify(500)!;
    store.write(port, {
      version: 1, port, reaper: null,
      server: { pid: 500, startTime: id.startTime, cmdline: id.cmdline, origin: "spawned", exe: "C:\\llama\\llama-server.exe" },
      holders: [{ pid: 77, startTime: "5" }],
    });
    const { leases } = leasesFor(100);
    await runMain(["--reference-seat"], {
      probeExisting: async () => true,
      spawnServer: async () => { throw new Error("must adopt"); },
      serverLeases: leases,
    });
    expect(store.read(port)!.holders.map((h) => h.pid)).toEqual([100]);
    leases.releaseSync();
    expect(world.killed).toEqual([500]);
  });
});

describe("a disabled lease keeps the previous exit behavior", () => {
  it("serverLeases: null spawns without recording anything", async () => {
    let spawns = 0;
    await runMain(["--reference-seat"], {
      probeExisting: async () => false,
      spawnServer: async (so: ServerSpawnOptions) => { spawns++; return fakeServerHandle(600, so.port); },
      serverLeases: null,
    });
    expect(spawns).toBe(1);
    expect(world.killed).toEqual([]);
  });
});
