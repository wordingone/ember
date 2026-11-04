// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #2378: the detached reaper that backstops hard kills.  The loop and the command are unit-tested;
// one end-to-end test runs the REAL reaper process against stand-in processes it spawns itself: a
// "holder" (stands for an ember instance) and a "server" (stands for llama-server), proving that
// when the holder dies by a hard kill, with no exit handler running, the server is still stopped.

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createWin32ProcessOps } from "./process-ops.ts";
import { LeaseStore, ServerLeases } from "./server-lease.ts";
import { reaperCommand, REAPER_SUBCOMMAND, runReaper, spawnReaperProcess } from "./server-reaper.ts";

describe("reaperCommand", () => {
  it("runs the reaper script with the port and lease directory when the script is on disk", () => {
    expect(reaperCommand(8123, "C:\\leases", { execPath: "C:\\bun\\bun.exe", scriptPath: "C:\\src\\server-reaper-main.ts" }))
      .toEqual({ command: "C:\\bun\\bun.exe", args: ["C:\\src\\server-reaper-main.ts", "8123", "C:\\leases"] });
  });
  it("falls back to the hidden subcommand of the executable for a compiled binary", () => {
    expect(reaperCommand(8123, "C:\\leases", { execPath: "C:\\ember.exe", scriptPath: null }))
      .toEqual({ command: "C:\\ember.exe", args: [REAPER_SUBCOMMAND, "8123", "C:\\leases"] });
  });
  it("the default resolves to the script beside the module (it exists in the source tree)", () => {
    const { args } = reaperCommand(8123, "C:\\leases");
    expect(existsSync(args[0]!)).toBe(true);
    expect(args[0]!.endsWith("server-reaper-main.ts")).toBe(true);
  });
});

describe("runReaper", () => {
  function leasesReturning(results: Array<"wait" | "done" | Error>) {
    let i = 0;
    return {
      calls: () => i,
      leases: { reapOnce: () => { const r = results[i++]!; if (r instanceof Error) throw r; return r; } } as unknown as ServerLeases,
    };
  }
  it("polls until the lease is settled, then stops", async () => {
    const f = leasesReturning(["wait", "wait", "done"]);
    const sleeps: number[] = [];
    await runReaper({ port: 1, leases: f.leases, intervalMs: 2000, sleep: async (ms) => { sleeps.push(ms); } });
    expect(f.calls()).toBe(3);
    expect(sleeps).toEqual([2000, 2000]);
  });
  it("survives a transient failure but gives up on a persistent one instead of spinning", async () => {
    const transient = leasesReturning([new Error("EBUSY"), "wait", "done"]);
    await runReaper({ port: 1, leases: transient.leases, sleep: async () => {} });
    expect(transient.calls()).toBe(3);

    const persistent = leasesReturning(Array.from({ length: 10 }, () => new Error("EPERM")));
    await runReaper({ port: 1, leases: persistent.leases, maxErrors: 3, sleep: async () => {} });
    expect(persistent.calls()).toBe(3);
  });
});

const live = process.platform === "win32" ? describe : describe.skip;

live("the real reaper process (end to end, stand-in processes)", () => {
  let dir: string;
  const children: ChildProcess[] = [];
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), "ember-reaper-e2e-")); });
  afterEach(() => {
    for (const c of children.splice(0)) { try { c.kill(); } catch { /* already gone */ } } // this test's own children
    rmSync(dir, { recursive: true, force: true });
  });

  it("stops the server within seconds after the last holder is hard-killed, then exits itself", async () => {
    const ops = createWin32ProcessOps()!;
    const script = join(dir, "idler.ts");
    writeFileSync(script, "setTimeout(() => {}, 120000);\n"); // exits by itself even if the test fails
    const port = 18_000 + Math.floor(Math.random() * 1000);
    const idle = (...extra: string[]) => {
      const c = spawn(process.execPath, [script, ...extra], { stdio: "ignore", windowsHide: true });
      children.push(c);
      return c;
    };
    const holder = idle("stand-in-for-ember");
    const server = idle("--port", String(port)); // "<bun> <script> --port N" verifies as the spawned executable
    await new Promise((r) => setTimeout(r, 400));
    const serverExit = new Promise<void>((r) => server.once("exit", () => r()));

    // The lease is written as the holder would: the holder is the process the lease depends on.
    const store = new LeaseStore(dir);
    const holderId = ops.identify(holder.pid!)!;
    const asHolder = { ...ops, self: () => holderId };
    const leases = new ServerLeases({ ops: asHolder, store, spawnReaper: (p) => spawnReaperProcess(ops, p, dir) });
    expect(leases.recordSpawned(port, server.pid!, process.execPath).kind).toBe("held");
    const lease = store.read(port)!;
    expect(lease.reaper).not.toBeNull();
    const reaperPid = lease.reaper!.pid;
    expect(ops.identify(reaperPid)).not.toBeNull(); // the detached reaper is running

    // Nothing runs on a hard kill: only the reaper can notice.
    const t0 = Date.now();
    holder.kill();
    await Promise.race([
      serverExit,
      new Promise((_, rej) => setTimeout(() => rej(new Error("server was not stopped within 15 s")), 15_000)),
    ]);
    const elapsedMs = Date.now() - t0;
    expect(elapsedMs).toBeLessThan(10_000);

    // The reaper kills first and deletes the lease right after: wait for the deletion.
    const gone = Date.now() + 5000;
    while (store.read(port) !== null && Date.now() < gone) await new Promise((r) => setTimeout(r, 50));
    expect(store.read(port)).toBeNull(); // lease deleted
    const stops = readFileSync(join(dir, "stops.jsonl"), "utf-8").trim().split("\n").map((l) => JSON.parse(l));
    expect(stops).toHaveLength(1);
    expect(stops[0]).toMatchObject({ port, pid: server.pid, outcome: "terminated" });
    expect(readFileSync(join(dir, "kill-receipts.jsonl"), "utf-8")).toContain(`"pids":[${server.pid}]`);

    // ...and the reaper itself is gone shortly after (it has nothing left to watch).
    const end = Date.now() + 8000;
    while (ops.identify(reaperPid) !== null && Date.now() < end) await new Promise((r) => setTimeout(r, 100));
    expect(ops.identify(reaperPid)).toBeNull();
  }, 40_000);
});
