// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { EventEmitter } from "node:events";

import { contextFallbacks, markSessionShuttingDown, resetSessionShutdownForTests, startHealing, superviseServer, type ReadyOutcome } from "./server-supervisor.ts";

interface Opts { nCtx: number; mmproj?: string }

class FakeHandle {
  process = Object.assign(new EventEmitter(), { pid: Math.floor(Math.random() * 1e6) });
  killed = false;
  constructor(public opts: Opts) {}
  kill(): void { this.killed = true; }
  die(code = 1): void { this.process.emit("exit", code); }
}

import { beforeEach } from "bun:test";
beforeEach(() => resetSessionShutdownForTests());

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("contextFallbacks", () => {
  it("halves down to 8192 and never below", () => {
    expect(contextFallbacks(65536)).toEqual([32768, 16384, 8192]);
    expect(contextFallbacks(24576)).toEqual([12288, 8192]);
    expect(contextFallbacks(8192)).toEqual([]);
  });
});

describe("startHealing", () => {
  it("steps the context down until the server loads", async () => {
    const spawned: Opts[] = [];
    const logs: string[] = [];
    const r = await startHealing<Opts, FakeHandle>({ nCtx: 65536 }, {
      spawn: async (o) => { spawned.push(o); return new FakeHandle(o); },
      waitReady: async (h): Promise<ReadyOutcome> => (h.opts.nCtx > 16384 ? { kind: "exited", code: 1 } : { kind: "ready" }),
      log: (l) => logs.push(l),
    });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.opts.nCtx).toBe(16384);
    expect(spawned.map((o) => o.nCtx)).toEqual([65536, 32768, 16384]);
    expect(logs.length).toBe(2);
  });

  it("drops the vision projector as the last step", async () => {
    const r = await startHealing<Opts, FakeHandle>({ nCtx: 16384, mmproj: "p.gguf" }, {
      spawn: async (o) => new FakeHandle(o),
      waitReady: async (h): Promise<ReadyOutcome> => (h.opts.mmproj ? { kind: "exited", code: 1 } : { kind: "ready" }),
      log: () => {},
    });
    expect(r.ok && r.opts.mmproj).toBe(undefined);
  });

  it("reports failure after every attempt, without looping", async () => {
    let n = 0;
    const r = await startHealing<Opts, FakeHandle>({ nCtx: 32768 }, {
      spawn: async (o) => { n++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "exited", code: 3 }),
      log: () => {},
    });
    expect(r.ok).toBe(false);
    expect(n).toBe(3);
  });
});

describe("startHealing on an unsupported model", () => {
  it("stops the context ladder at once and points at ember pull", async () => {
    let n = 0;
    const logs: string[] = [];
    const r = await startHealing<Opts, FakeHandle>({ nCtx: 65536 }, {
      spawn: async (o) => { n++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "exited", code: 1 }),
      log: (l) => logs.push(l),
      classifyFailure: () => "runtime-too-old",
    });
    expect(r.ok).toBe(false);
    expect(n).toBe(1);
    expect(logs.join(" ")).toContain("ember pull");
  });
});

describe("superviseServer", () => {
  it("respawns a server that dies mid-session", async () => {
    const first = new FakeHandle({ nCtx: 16384 });
    const handles: FakeHandle[] = [];
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { const h = new FakeHandle(o); handles.push(h); return h; },
      waitReady: async () => ({ kind: "ready" }),
      log: () => {},
    });
    first.die();
    await tick(); await tick();
    expect(s.restarts()).toBe(1);
    expect(s.current()).toBe(handles[0]!);
    s.stop();
    expect(handles[0]!.killed).toBe(true);
  });

  it("gives up after the restart cap inside the window", async () => {
    let t = 0;
    const first = new FakeHandle({ nCtx: 8192 });
    const logs: string[] = [];
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => new FakeHandle(o),
      waitReady: async () => ({ kind: "ready" }),
      log: (l) => logs.push(l),
      now: () => t,
      maxRestarts: 2,
      windowMs: 1000,
    });
    for (let i = 0; i < 3; i++) { s.current().die(); await tick(); await tick(); t += 10; }
    expect(s.restarts()).toBe(2);
    expect(logs.some((l) => l.includes("giving up"))).toBe(true);
  });

  it("does not respawn after stop()", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    let spawns = 0;
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { spawns++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "ready" }),
      log: () => {},
    });
    s.stop();
    first.die();
    await tick();
    expect(spawns).toBe(0);
    expect(first.killed).toBe(true);
  });
});

describe("superviseServer: exit began (#2378)", () => {
  it("detach() stops supervising without killing the server another ember may still use", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    let spawns = 0;
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { spawns++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "ready" }),
      log: () => {},
    });
    s.detach();
    expect(first.killed).toBe(false);
    first.die(); // the lease stops the server at exit; its death must not trigger a respawn
    await tick(); await tick();
    expect(spawns).toBe(0);
    expect(s.restarts()).toBe(0);
  });

  it("a respawn already in flight when detach() is called is not installed and not killed (the lease owns it)", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    const spawned: FakeHandle[] = [];
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { await gate; const h = new FakeHandle(o); spawned.push(h); return h; },
      waitReady: async () => ({ kind: "ready" }),
      log: () => {},
    });
    first.die();
    await tick();
    s.detach();
    release();
    await tick(); await tick();
    expect(spawned).toHaveLength(1);
    expect(spawned[0]!.killed).toBe(false);
    expect(s.current()).toBe(first); // the new handle was not installed
  });

  it("a respawn already in flight when stop() is called is killed", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    const spawned: FakeHandle[] = [];
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { await gate; const h = new FakeHandle(o); spawned.push(h); return h; },
      waitReady: async () => ({ kind: "ready" }),
      log: () => {},
    });
    first.die();
    await tick();
    s.stop();
    release();
    await tick(); await tick();
    expect(spawned[0]!.killed).toBe(true);
  });

  it("a heal ladder abandons its remaining attempts once the session is ending", async () => {
    let ending = false;
    const spawned: number[] = [];
    const r = await startHealing<Opts, FakeHandle>({ nCtx: 65536 }, {
      spawn: async (o) => { spawned.push(o.nCtx); ending = true; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "exited", code: 1 }),
      log: () => {},
      aborted: () => ending,
    });
    expect(r.ok).toBe(false);
    expect(spawned).toEqual([65536]);
  });
});

describe("superviseServer: session shutdown is not a crash (#2381)", () => {
  it("a server exit after the shutdown mark neither restarts nor logs", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    let spawns = 0;
    const logs: string[] = [];
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { spawns++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "ready" }),
      log: (l) => logs.push(l),
    });
    markSessionShuttingDown();
    first.die(58);
    await tick(); await tick();
    expect(spawns).toBe(0);
    expect(s.restarts()).toBe(0);
    expect(logs).toEqual([]);
  });

  it("the server exit arriving BEFORE the shutdown signal handler is still claimed by it (grace)", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    let spawns = 0;
    const logs: string[] = [];
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { spawns++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "ready" }),
      log: (l) => logs.push(l),
      exitGraceMs: 30,
    });
    first.die(58);            // console close: the server dies first ...
    markSessionShuttingDown(); // ... then SIGHUP reaches ember
    await new Promise((r) => setTimeout(r, 80));
    expect(spawns).toBe(0);
    expect(s.restarts()).toBe(0);
    expect(logs).toEqual([]);
  });

  it("a real crash with no shutdown still restarts after the grace", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    let spawns = 0;
    const s = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => { spawns++; return new FakeHandle(o); },
      waitReady: async () => ({ kind: "ready" }),
      log: () => {},
      exitGraceMs: 20,
    });
    first.die(1);
    await new Promise((r) => setTimeout(r, 80));
    expect(s.restarts()).toBe(1);
    expect(spawns).toBe(1);
  });
});

describe("superviseServer: operator events (#2381 R1/R3)", () => {
  it("emits restarted n/max after a successful restart and gave-up when the cap opens the circuit", async () => {
    let t = 0;
    const first = new FakeHandle({ nCtx: 8192 });
    const events: unknown[] = [];
    const sup = superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => new FakeHandle(o),
      waitReady: async () => ({ kind: "ready" }),
      log: () => {}, now: () => t, maxRestarts: 2, windowMs: 1000,
      onEvent: (e) => events.push(e),
    });
    for (let i = 0; i < 3; i++) { sup.current().die(1); await tick(); await tick(); await tick(); t += 10; }
    expect(events).toEqual([
      { kind: "restarted", n: 1, max: 2 },
      { kind: "restarted", n: 2, max: 2 },
      { kind: "gave-up", max: 2, reason: "cap" },
    ]);
  });

  it("a restart that cannot bring the server back emits gave-up", async () => {
    const first = new FakeHandle({ nCtx: 8192 });
    const events: Array<{ kind: string }> = [];
    superviseServer<Opts, FakeHandle>(first, first.opts, {
      spawn: async (o) => new FakeHandle(o),
      waitReady: async () => ({ kind: "exited", code: 1 }),
      log: () => {}, onEvent: (e) => events.push(e),
    });
    first.die(1);
    await new Promise((r) => setTimeout(r, 30));
    expect(events.map((e) => e.kind)).toEqual(["gave-up"]);
  });
});
