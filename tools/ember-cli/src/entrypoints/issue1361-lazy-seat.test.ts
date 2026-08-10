// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue #1361: production lazy model-seat contract

import { describe, expect, test } from "bun:test";
import { buildLazyOwnedCallModel, getModelSeatState, _resetInitForTests } from "./session-init.ts";
import { main } from "./process-entry.ts";
import type { OwnedModelIdentity } from "./model-seat.ts";

const PROCESS_ENTRY = new URL("./process-entry.ts", import.meta.url);
const SESSION_INIT = new URL("./session-init.ts", import.meta.url);
const REPL = new URL("../screens/repl.ts", import.meta.url);
const STATUS_BAR = new URL("../components/status-bar.ts", import.meta.url);

async function source(path: string | URL): Promise<string> {
  return Bun.file(path).text();
}

describe("#1361 production lazy model-seat contract", () => {
  test("ordinary no-env boot does not refuse before session initialization", async () => {
    const text = await source(PROCESS_ENTRY);
    const offline = text.indexOf("let ordinaryOfflineBoot = false");
    const refusal = text.indexOf("// Invalid interactive seats refuse before session initialization");
    expect(offline).toBeGreaterThan(0);
    expect(refusal).toBeGreaterThan(offline);
  });

  test("ordinary OFFLINE boot cannot fall through to the local spawn path", async () => {
    const text = await source(PROCESS_ENTRY);
    const localPath = text.indexOf("No direct launcher path may become");
    const spawn = text.indexOf("const exeDir", localPath);
    expect(spawn).toBeGreaterThan(0);
    const beforeSpawn = text.slice(Math.max(0, spawn - 1200), spawn);
    expect(beforeSpawn).toMatch(/seatDecision\.seat\s*===\s*[\"']OFFLINE[\"']/);
    expect(beforeSpawn).toMatch(/serverUrl\s*=\s*null/);
  });

  test("invalid interactive seats refuse before session initialization", async () => {
    const text = await source(PROCESS_ENTRY);
    const refusal = text.indexOf("// Invalid interactive seats refuse before session initialization");
    const session = text.indexOf("const sessionMod");
    expect(refusal).toBeGreaterThan(0);
    expect(refusal).toBeLessThan(session);
    expect(text.slice(refusal, session)).toMatch(/doExitMain\(1\)/);
  });

  test("ordinary boot passes a first-call lazy starter into session initialization", async () => {
    const text = await source(PROCESS_ENTRY);
    const initCall = text.indexOf("const doInit");
    expect(initCall).toBeGreaterThanOrEqual(0);
    expect(text.slice(initCall, initCall + 1600)).toMatch(/lazy(?:Owned)?(?:Seat|Server)|lazyStarter|startOwnedServer/);
  });

  test("ordinary absent boot cannot inherit a persisted endpoint", async () => {
    const text = await source(PROCESS_ENTRY);
    const external = text.indexOf("const externalUrl");
    expect(text.slice(external, external + 280)).toMatch(/ordinaryOfflineBoot/);
  });

  test("headless lease demotion preserves the existing effective GPU-free gate", async () => {
    const text = await source(PROCESS_ENTRY);
    const refusal = text.indexOf("headless launch refuses an unbound seat");
    expect(refusal).toBeGreaterThan(0);
    expect(text.slice(Math.max(0, refusal - 420), refusal)).toMatch(/!gpuFreeRequested/);
  });

  test("lazy owned boot passes an explicit offline init signal until interaction", async () => {
    const text = await source(PROCESS_ENTRY);
    const lazy = text.indexOf("const lazyOwnedServerStarter");
    expect(lazy).toBeGreaterThan(0);
    const init = text.indexOf("await doInit({", lazy);
    expect(init).toBeGreaterThan(lazy);
    expect(text.slice(lazy, init + 900)).toMatch(/serverUrl\s*=\s*null/);
    expect(text.slice(lazy, init + 900)).toMatch(/lazyOwnedServerStarter/);
  });

  test("owned supervision is deferred until after session initialization", async () => {
    const text = await source(PROCESS_ENTRY);
    const lazy = text.indexOf("const lazyOwnedServerStarter");
    const init = text.indexOf("await doInit");
    expect(lazy).toBeGreaterThan(0);
    expect(text.slice(lazy, init)).toMatch(/(?:ensureOwnedServerFn|ensureOwnedServer)\(identity/);
    expect(init).toBeGreaterThan(lazy);
  });

  test("session-init options expose a lazy seat starter", async () => {
    const text = await source(SESSION_INIT);
    expect(text).toMatch(/lazy(?:Owned)?Seat|lazyStarter|startOwnedServer/);
    expect(text).toMatch(/serverUrl\?:\s*string\s*\|\s*null/);
  });

  test("session-init defers model-client construction until first call", async () => {
    const text = await source(SESSION_INIT);
    expect(text).toMatch(/callModel[\s\S]{0,1400}(ensureOwnedServer|startOwnedServer|lazy)/);
    expect(text).not.toMatch(/_circuitBreakerHandle\s*=\s*!serverUrl\s*\n\s*\?\s*buildOfflineCallModel/);
  });

  test("status-bar declares absent/loading/resident seat state", async () => {
    const text = await source(STATUS_BAR);
    expect(text).toMatch(/ModelSeatState|SeatPhase|ABSENT|LOADING|RESIDENT/);
    expect(text).toMatch(/owner|vramBytes|vr[aA][mM]/);
    expect(text).toMatch(/vram=unknown/);
    expect(text).toMatch(/const modelSeatText = modelSeat != null/);
  });

  test("REPL passes seat state and first-call starter to StatusLine", async () => {
    const text = await source(REPL);
    expect(text).toMatch(/ModelSeatState|seatState|modelSeat/);
    expect(text).toMatch(/StatusLine[\s\S]{0,1800}(seatState|modelSeat|lazy)/);
  });

  test("first model interaction starts the owned seat once and records absence", async () => {
    let starts = 0;
    const states: string[] = [];
    const lazy = buildLazyOwnedCallModel(
      { serverUrl: "", nCtx: 4096, modelCapabilities: null, servedModelConfigSha256: null },
      async () => { starts += 1; return null; },
      (state) => { states.push(state.phase); },
    );
    await expect(lazy.callModel({} as never)).rejects.toThrow("absent");
    await expect(lazy.callModel({} as never)).rejects.toThrow("absent");
    expect(starts).toBe(1);
    expect(states).toEqual(["LOADING", "ABSENT"]);
  });

  test("successful first interaction publishes a resident owner and endpoint", async () => {
    const states: Array<{ phase: string; owner?: string; endpoint?: string; vramBytes?: number }> = [];
    const lazy = buildLazyOwnedCallModel(
      { serverUrl: "", nCtx: 4096, modelCapabilities: null, servedModelConfigSha256: null },
      async () => ({ endpoint: "http://127.0.0.1:1", owner: "ember-owned:test", vramBytes: 456_789 }),
      (state) => { states.push({ phase: state.phase, owner: state.owner, endpoint: state.endpoint, vramBytes: state.vramBytes }); },
      "ember-owned:test",
    );
    const circuit = lazy.getCircuitState();
    expect(circuit.endpoint).toBeNull();
    await expect(lazy.callModel({ abortSignal: AbortSignal.abort() } as never)).rejects.toBeDefined();
    expect(states).toEqual([
      { phase: "LOADING", owner: "ember-owned:test", endpoint: undefined, vramBytes: undefined },
      { phase: "RESIDENT", owner: "ember-owned:test", endpoint: "http://127.0.0.1:1", vramBytes: 456_789 },
    ]);
    expect(states[1]?.endpoint).toBe("http://127.0.0.1:1");
    expect(states[1]?.vramBytes).toBe(456_789);
  });

  test("concurrent first interactions share one governed handoff", async () => {
    let starts = 0;
    let release!: (endpoint: string | null) => void;
    const lazy = buildLazyOwnedCallModel(
      { serverUrl: "", nCtx: 4096, modelCapabilities: null, servedModelConfigSha256: null },
      () => {
        starts += 1;
        return new Promise<string | null>((resolve) => { release = resolve; });
      },
      undefined,
      "ember-owned:concurrent",
    );
    const first = lazy.callModel({ abortSignal: AbortSignal.abort() } as never);
    const second = lazy.callModel({ abortSignal: AbortSignal.abort() } as never);
    await Promise.resolve();
    expect(starts).toBe(1);
    release(null);
    const results = await Promise.allSettled([first, second]);
    expect(results.every((result) => result.status === "rejected")).toBe(true);
  });

  test("failed handoff resets to ABSENT and permits one governed retry", async () => {
    let starts = 0;
    const lazy = buildLazyOwnedCallModel(
      { serverUrl: "", nCtx: 4096, modelCapabilities: null, servedModelConfigSha256: null },
      async () => {
        starts += 1;
        if (starts === 1) throw new Error("owned handoff failed");
        return null;
      },
      undefined,
      "ember-owned:retry",
    );
    await expect(lazy.callModel({ abortSignal: AbortSignal.abort() } as never))
      .rejects.toThrow("owned handoff failed");
    await expect(lazy.callModel({ abortSignal: AbortSignal.abort() } as never))
      .rejects.toThrow("absent");
    expect(starts).toBe(2);
  });

  test("ordinary main boot does not spawn, then admits exactly one first-call owned handoff", async () => {
    const saved = {
      EMBER_MODEL_URL: process.env["EMBER_MODEL_URL"],
      EMBER_GPU_FREE: process.env["EMBER_GPU_FREE"],
      EMBER_REFERENCE_SEAT: process.env["EMBER_REFERENCE_SEAT"],
      EMBER_MODEL_NAME: process.env["EMBER_MODEL_NAME"],
      EMBER_MODEL_SEAT_STATE: process.env["EMBER_MODEL_SEAT_STATE"],
    };
    for (const key of Object.keys(saved)) delete process.env[key];
    const identity: OwnedModelIdentity = {
      seat: "OWNED_ADMITTED",
      checkpointSha256: "a".repeat(64),
      endpointUrl: "http://127.0.0.1:29771",
      identityUrl: "https://example.invalid/owned.json",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:1361",
      serverSourceSha256: "c".repeat(64),
      tokenizerSha256: "d".repeat(64),
    };
    let loaderCalls = 0;
    let spawnCalls = 0;
    let handshakeCalls = 0;
    let ensureCalls = 0;
    let readinessCalls = 0;
    let verifyCalls = 0;
    _resetInitForTests();
    try {
      await main({
        argv: ["node", "ember"],
        checkGpuLease: async () => null,
        loadOwnedIdentityFn: () => {
          loaderCalls += 1;
          return loaderCalls === 1 ? undefined : identity;
        },
        loadOwnedDevelopmentIdentityFn: () => undefined,
        handshakeEmberLabFn: async () => { handshakeCalls += 1; },
        ensureOwnedServerFn: async (_owned) => {
          ensureCalls += 1;
          readinessCalls += 1;
          return { outcome: "dispatched", port: 29771, pid: 1361, vramBytes: 12_345_678_901 };
        },
        verifyOwnedEndpointFn: async () => {
          verifyCalls += 1;
          return { ...identity, vramBytes: 12_345_678_901 };
        },
        spawnServer: async () => {
          spawnCalls += 1;
          throw new Error("ordinary boot must not call spawnServer");
        },
        interactiveRunner: async (deps) => {
          await expect(deps.callModel({ abortSignal: AbortSignal.abort() } as never)).rejects.toBeDefined();
        },
      });
      expect(spawnCalls).toBe(0);
      expect(loaderCalls).toBe(2);
      expect(handshakeCalls).toBe(1);
      expect(ensureCalls).toBe(1);
      expect(readinessCalls).toBe(1);
      expect(verifyCalls).toBe(1);
      expect(process.env["EMBER_MODEL_SEAT_STATE"]).toBe("RESIDENT");
      expect(getModelSeatState()).toMatchObject({
        phase: "RESIDENT",
        owner: "ember-owned:1361",
        vramBytes: 12_345_678_901,
      });
    } finally {
      _resetInitForTests();
      for (const [key, value] of Object.entries(saved)) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
    }
  });
});
