// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #2378: closing ember frees the GPU whether ember spawned the model server or adopted it, and a
// shared server survives until its last holder is gone.  All scenarios run on a fake machine.

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { FakeWorld } from "./server-lease.fakes.ts";
import {
  LeaseStore, makeStopReceiptSink, ServerLeases, splitCommandLine, verifyServerCmdline,
  type LeaseProcess, type StopReceipt,
} from "./server-lease.ts";

const PORT = 8123;
const EXE = "C:\\llama\\llama-server.exe";

let dir: string;
let world: FakeWorld;
let store: LeaseStore;
let receipts: StopReceipt[];

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ember-lease-test-"));
  world = new FakeWorld();
  store = new LeaseStore(dir, () => {});
  receipts = [];
});
afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

/** An ember instance with PID `selfPid` on the shared fake machine. */
function ember(selfPid: number, opts: { reaperPid?: number } = {}): ServerLeases {
  world.addProcess(selfPid, "bun run main.ts");
  return new ServerLeases({
    ops: world.ops(selfPid),
    store,
    receipt: (r) => { receipts.push(r); world.events.push(`receipt:${r.pid}`); },
    spawnReaper: opts.reaperPid === undefined ? undefined : () => {
      world.addProcess(opts.reaperPid!, "bun run server-reaper-main.ts");
      return { pid: opts.reaperPid!, startTime: world.ops(0).identify(opts.reaperPid!)!.startTime };
    },
  });
}

describe("verifyServerCmdline: the only way a server is ever selected", () => {
  it("accepts a llama-server on the right port, quoted or not, --port N or --port=N", () => {
    expect(verifyServerCmdline(`"${EXE}" --model m.gguf --port 8123`, 8123)).toBe(true);
    expect(verifyServerCmdline("C:\\x\\llama-server --port=8123 --jinja", 8123)).toBe(true);
    expect(verifyServerCmdline('"C:\\Program Files\\llama\\llama-server.exe" --port 8123', 8123)).toBe(true);
  });
  it("rejects another port, another program, and a name that merely mentions llama-server", () => {
    expect(verifyServerCmdline(`"${EXE}" --port 8124`, 8123)).toBe(false);
    expect(verifyServerCmdline("notepad.exe --port 8123", 8123)).toBe(false);
    expect(verifyServerCmdline("C:\\x\\llama-cli.exe --port 8123", 8123)).toBe(false);
    expect(verifyServerCmdline("C:\\tools\\llama-server\\other.exe --port 8123", 8123)).toBe(false);
    expect(verifyServerCmdline("", 8123)).toBe(false);
  });
  it("a server started without --port is on 8080, and only 8080", () => {
    expect(verifyServerCmdline(`${EXE} --model m.gguf`, 8080)).toBe(true);
    expect(verifyServerCmdline(`${EXE} --model m.gguf`, 8123)).toBe(false);
  });
  it("when ember spawned it, the executable must be exactly the one spawned", () => {
    expect(verifyServerCmdline('"C:\\b\\engine-x.exe" --port 8123', 8123, "C:\\b\\engine-x.exe")).toBe(true);
    expect(verifyServerCmdline('"C:\\b\\llama-server.exe" --port 8123', 8123, "C:\\b\\engine-x.exe")).toBe(false);
  });
  it("splitCommandLine groups quoted arguments", () => {
    expect(splitCommandLine('"a b\\c.exe" --x  "" y')).toEqual(["a b\\c.exe", "--x", "", "y"]);
  });
});

describe("adopt-then-exit", () => {
  it("records the adopted server (PID, start time, command line) and stops exactly that PID on exit", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);

    const r = a.attachAdopted(PORT);
    expect(r.kind).toBe("held");
    if (r.kind === "held") { expect(r.origin).toBe("adopted"); expect(r.server.pid).toBe(500); expect(r.holders).toBe(1); }
    const lease = store.read(PORT)!;
    expect(lease.server).toMatchObject({ pid: 500, origin: "adopted" });
    expect(lease.server!.cmdline).toContain("--port 8123");
    expect(lease.holders.map((h) => h.pid)).toEqual([100]);

    a.releaseSync();
    expect(world.killed).toEqual([500]);
    expect(store.read(PORT)).toBeNull();
    expect(world.isAlive(500)).toBe(false);
  });

  it("writes the kill receipt BEFORE the stop", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    a.releaseSync();
    expect(world.events.filter((e) => e.startsWith("receipt") || e.startsWith("terminate")))
      .toEqual(["receipt:500", "terminate:500:terminated"]);
    expect(receipts[0]).toMatchObject({ port: PORT, pid: 500 });
  });

  it("does not own a listener that is not a llama-server on that port", () => {
    world.addProcess(500, `"C:\\apps\\someserver.exe" --port ${PORT}`);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    expect(a.attachAdopted(PORT).kind).toBe("unverified");
    expect(a.holding(PORT)).toBe(false);
    a.releaseSync();
    expect(world.killed).toEqual([]);
    expect(world.isAlive(500)).toBe(true);
  });

  it("refuses to own a port with several listeners, and reports no listener", () => {
    const a = ember(100);
    world.listeners.set(PORT, "ambiguous");
    expect(a.attachAdopted(PORT).kind).toBe("ambiguous");
    world.listeners.delete(PORT);
    expect(a.attachAdopted(PORT).kind).toBe("no-listener");
    a.releaseSync();
    expect(world.killed).toEqual([]);
  });

  it("never kills a recycled PID: same PID, different creation time and command line", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    world.reuse(500, "C:\\Windows\\notepad.exe readme.txt"); // server died, PID recycled
    a.releaseSync();
    expect(world.killed).toEqual([]);
    expect(world.isAlive(500)).toBe(true);
    expect(receipts).toEqual([]); // no receipt for a stop that was refused
    expect(store.read(PORT)).toBeNull();
  });

  it("never kills a PID reused by another llama-server (same command line, new creation time)", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    world.reuse(500, `"${EXE}" --model m.gguf --port ${PORT}`);
    a.releaseSync();
    expect(world.killed).toEqual([]);
  });

  it("is idempotent: exit hooks and signal hooks may both call release", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    a.releaseSync();
    a.releaseSync();
    expect(world.terminateCalls).toHaveLength(1);
  });
});

describe("spawn-then-exit", () => {
  it("records the spawned server and stops exactly that PID on exit", () => {
    world.llamaServer(600, PORT, "C:\\bin\\llama-server.exe");
    const a = ember(100);
    const r = a.recordSpawned(PORT, 600, "C:\\bin\\llama-server.exe");
    expect(r.kind).toBe("held");
    if (r.kind === "held") expect(r.origin).toBe("spawned");
    expect(a.holding(PORT)).toBe(true);
    a.releaseSync();
    expect(world.killed).toEqual([600]);
    expect(store.read(PORT)).toBeNull();
  });

  it("does not record a process that is not the executable that was spawned", () => {
    world.addProcess(600, `C:\\other\\thing.exe --port ${PORT}`);
    const a = ember(100);
    expect(a.recordSpawned(PORT, 600, "C:\\bin\\llama-server.exe").kind).toBe("unverified");
    expect(a.holding(PORT)).toBe(false);
  });

  it("after a supervisor respawn only the live (new) server is stopped", () => {
    world.llamaServer(600, PORT);
    const a = ember(100);
    a.recordSpawned(PORT, 600, EXE);
    world.die(600);
    world.llamaServer(601, PORT);
    a.recordSpawned(PORT, 601, EXE);
    expect(store.read(PORT)!.server!.pid).toBe(601);
    a.releaseSync();
    expect(world.killed).toEqual([601]);
  });

  it("runs onBeforeRelease hooks before touching the server (the supervisor stops respawning first)", () => {
    world.llamaServer(600, PORT);
    const a = ember(100);
    a.recordSpawned(PORT, 600, EXE);
    a.onBeforeRelease(() => world.events.push("supervisor-detached"));
    a.releaseSync();
    expect(world.events.indexOf("supervisor-detached")).toBeLessThan(world.events.indexOf("terminate:600:terminated"));
  });
});

describe("two holders on one server", () => {
  it("the first exit keeps the server; the last exit stops it", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    const b = ember(101);
    a.attachAdopted(PORT);
    const rb = b.attachAdopted(PORT);
    expect(rb.kind === "held" && rb.holders).toBe(2);

    a.releaseSync();
    expect(world.killed).toEqual([]);
    expect(world.isAlive(500)).toBe(true);
    expect(store.read(PORT)!.holders.map((h) => h.pid)).toEqual([101]);

    b.releaseSync();
    expect(world.killed).toEqual([500]);
    expect(store.read(PORT)).toBeNull();
  });

  it("works when the first holder SPAWNED the server and the second adopted it", () => {
    world.llamaServer(600, PORT);
    world.listeners.set(PORT, 600);
    const a = ember(100);
    const b = ember(101);
    a.recordSpawned(PORT, 600, EXE);
    b.attachAdopted(PORT);
    a.releaseSync(); // the spawner leaves first
    expect(world.isAlive(600)).toBe(true);
    b.releaseSync();
    expect(world.killed).toEqual([600]);
  });
});

describe("crashes and stale leases", () => {
  it("a holder that crashed (no exit hook ran) is pruned when the next ember attaches", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    world.die(100); // hard kill
    const b = ember(101);
    const r = b.attachAdopted(PORT);
    expect(r.kind === "held" && r.holders).toBe(1);
    expect(store.read(PORT)!.holders.map((h) => h.pid)).toEqual([101]);
    b.releaseSync();
    expect(world.killed).toEqual([500]);
  });

  it("a recycled holder PID does not count as a live holder", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    world.reuse(100, "C:\\Windows\\explorer.exe"); // crashed; PID given to something else
    expect(ember(101).reapOnce(PORT)).toBe("done");
    expect(world.killed).toEqual([500]);
  });

  it("the reaper stops the server once every holder is dead, and waits while one is alive", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    const b = ember(101);
    a.attachAdopted(PORT);
    b.attachAdopted(PORT);
    const reaper = ember(900);
    expect(reaper.reapOnce(PORT)).toBe("wait");
    world.die(100);
    expect(reaper.reapOnce(PORT)).toBe("wait");
    expect(store.read(PORT)!.holders.map((h) => h.pid)).toEqual([101]);
    world.die(101);
    expect(reaper.reapOnce(PORT)).toBe("done");
    expect(world.killed).toEqual([500]);
    expect(store.read(PORT)).toBeNull();
    expect(reaper.reapOnce(PORT)).toBe("done"); // lease gone: nothing left to do
  });

  it("startup recovery: dead holders + a live verified server that is not answering -> stopped", () => {
    world.llamaServer(500, PORT);
    store.write(PORT, {
      version: 1, port: PORT, reaper: null,
      server: { pid: 500, startTime: "1500", cmdline: world.ops(0).identify(500)!.cmdline, origin: "adopted" },
      holders: [{ pid: 77, startTime: "1" }], // long dead
    });
    expect(ember(101).reapOnce(PORT)).toBe("done");
    expect(world.killed).toEqual([500]);
  });

  it("startup recovery: dead holders + a dead server -> the lease is just deleted", () => {
    store.write(PORT, {
      version: 1, port: PORT, reaper: null,
      server: { pid: 500, startTime: "1500", cmdline: `"${EXE}" --port ${PORT}`, origin: "adopted" },
      holders: [{ pid: 77, startTime: "1" }],
    });
    expect(ember(101).reapOnce(PORT)).toBe("done");
    expect(world.terminateCalls).toEqual([]);
    expect(store.read(PORT)).toBeNull();
  });

  it("an orphaned server that IS answering is adopted and owned, so the next exit frees it", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    store.write(PORT, {
      version: 1, port: PORT, reaper: null,
      server: { pid: 500, startTime: "1500", cmdline: world.ops(0).identify(500)!.cmdline, origin: "spawned", exe: EXE },
      holders: [{ pid: 77, startTime: "1" }],
    });
    const b = ember(101);
    const r = b.attachAdopted(PORT);
    expect(r.kind === "held" && r.holders).toBe(1);
    b.releaseSync();
    expect(world.killed).toEqual([500]);
  });

  it("recovery leaves a server alone while any holder is alive", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    expect(ember(101).reapOnce(PORT)).toBe("wait");
    expect(world.killed).toEqual([]);
  });

  it("a corrupt lease file is treated as absent", () => {
    writeFileSync(store.leasePath(PORT), "{not json");
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    expect(a.attachAdopted(PORT).kind).toBe("held");
  });
});

describe("the reaper process", () => {
  it("is started once, recorded in the lease, and a second reaper steps aside", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100, { reaperPid: 900 });
    const b = ember(101, { reaperPid: 901 });
    a.attachAdopted(PORT);
    b.attachAdopted(PORT);
    expect(store.read(PORT)!.reaper?.pid).toBe(900);
    expect(world.isAlive(901)).toBe(false); // b saw a live reaper and did not start another

    const me900 = { pid: 900, startTime: world.ops(0).identify(900)!.startTime };
    world.addProcess(950, "bun run server-reaper-main.ts"); // a stray duplicate reaper
    const stray = new ServerLeases({ ops: world.ops(950), store });
    const me950 = { pid: 950, startTime: world.ops(0).identify(950)!.startTime };
    expect(stray.reapOnce(PORT, me950)).toBe("done"); // 900 is live and is the recorded reaper
    expect(ember(902).reapOnce(PORT, me900)).toBe("wait");
    expect(world.killed).toEqual([]);
  });

  it("a dead recorded reaper is replaced by the next attach", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100, { reaperPid: 900 });
    a.attachAdopted(PORT);
    world.die(900);
    const b = ember(101, { reaperPid: 901 });
    b.attachAdopted(PORT);
    expect(store.read(PORT)!.reaper?.pid).toBe(901);
  });
});

describe("exit hooks", () => {
  function fakeProc(listeners: Record<string, number> = {}) {
    const handlers = new Map<string, () => void>();
    const exits: number[] = [];
    const proc: LeaseProcess = {
      on: (event, fn) => { handlers.set(event, fn as () => void); return proc; },
      exit: (code) => { exits.push(code ?? 0); },
      listenerCount: (event) => listeners[event] ?? 1,
    };
    return { proc, handlers, exits };
  }

  it("normal exit, console-window close (SIGHUP/SIGBREAK), Ctrl+C and SIGTERM all release", () => {
    for (const event of ["exit", "SIGHUP", "SIGBREAK", "SIGINT", "SIGTERM"]) {
      world = new FakeWorld();
      store.remove(PORT);
      world.llamaServer(500, PORT);
      world.listeners.set(PORT, 500);
      const a = ember(100);
      a.attachAdopted(PORT);
      const f = fakeProc();
      a.installExitHooks(f.proc);
      f.handlers.get(event)!();
      expect(world.killed).toEqual([500]);
    }
  });

  it("a signal exits the process unless another listener owns the shutdown", () => {
    world.llamaServer(500, PORT);
    world.listeners.set(PORT, 500);
    const a = ember(100);
    a.attachAdopted(PORT);
    const alone = fakeProc();
    a.installExitHooks(alone.proc);
    alone.handlers.get("SIGHUP")!();
    expect(alone.exits).toEqual([129]);

    world.llamaServer(501, PORT);
    world.listeners.set(PORT, 501);
    const b = ember(101);
    b.attachAdopted(PORT);
    const shared = fakeProc({ SIGINT: 2 });
    b.installExitHooks(shared.proc);
    shared.handlers.get("SIGINT")!();
    expect(shared.exits).toEqual([]);
    expect(world.killed).toContain(501);
  });

  it("installs once", () => {
    const a = ember(100);
    let registrations = 0;
    const proc: LeaseProcess = { on: () => { registrations++; return proc; }, exit: () => {} };
    a.installExitHooks(proc);
    a.installExitHooks(proc);
    expect(registrations).toBe(5);
  });
});

describe("store", () => {
  it("steals a stale lock instead of waiting forever", () => {
    const lock = join(dir, `${PORT}.lock`);
    writeFileSync(lock, "");
    const old = new Date(Date.now() - 60_000);
    utimesSync(lock, old, old);
    let ran = false;
    store.withLock(PORT, () => { ran = true; });
    expect(ran).toBe(true);
    expect(existsSync(lock)).toBe(false);
  });

  it("steals a live-looking lock after the wait budget rather than strand the server", () => {
    const lock = join(dir, `${PORT}.lock`);
    writeFileSync(lock, "");
    let slept = 0;
    const s = new LeaseStore(dir, (ms) => { slept += ms; });
    let ran = false;
    s.withLock(PORT, () => { ran = true; });
    expect(ran).toBe(true);
    expect(slept).toBeGreaterThanOrEqual(2000);
  });

  it("receipts land in the shared ledger when one is configured, and always locally", () => {
    const shared = join(dir, "shared-receipts.jsonl");
    const sink = makeStopReceiptSink(store, { EMBER_KILL_RECEIPTS_PATH: shared });
    sink({ port: PORT, pid: 500, cmdline: "x", why: "test" });
    const row = JSON.parse(readFileSync(shared, "utf-8").trim());
    expect(row.pids).toEqual([500]);
    expect(row.survivors_expected).toBe("none");
    expect(readFileSync(join(dir, "kill-receipts.jsonl"), "utf-8")).toContain('"pids":[500]');
  });
});
