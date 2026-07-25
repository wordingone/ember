// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Fix #51 PR #948 repair: `selectedModelContract` (entrypoints/model-seat.ts)
// existed with zero production call sites -- every prior test called it
// directly against a hand-built ModelSeatDecision, never through main()'s
// real seat-construction path. These tests are execution-binding: they
// prove the PRODUCTION entrypoint (`main()` in process-entry.ts) itself
// calls `selectedModelContract` exactly once per seat construction, and
// that its result -- never a second ad-hoc reconstruction -- is what ends
// up in EMBER_MODEL_NAME. The named negative proves a missing contract for
// a seat that is supposed to carry a model identity fails loudly instead
// of silently falling back to a hardcoded/raw name.

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { main } from "./process-entry.ts";
import { selectedModelContract } from "./model-seat.ts";
import type { ModelSeatDecision, SelectedModelContract } from "./model-seat.ts";
import { _resetConfigHomeMemo } from "../utils/env-detection.ts";
import type { LoopDeps } from "../query/query-loop-support.ts";
import type { ServerHandle } from "./process-entry.ts";

function makeFakeHandle(port = 29910): ServerHandle {
  return {
    process: {} as ReturnType<typeof import("node:child_process").spawn>,
    port,
    kill() {},
  };
}

function fakeDeps(): LoopDeps {
  return {
    callModel: async () => { throw new Error("model call is not exercised"); },
    microcompact: async (messages) => messages,
    autocompact: async () => {},
    generateUuid: () => "contract-wiring-test",
    sleep: async () => {},
  };
}

describe("process-entry — selectedModelContract production wiring (PR #948 repair)", () => {
  let savedEnv: Record<string, string | undefined>;
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = join(
      tmpdir(),
      "ember-contract-wiring-" + Date.now() + "-" + Math.random().toString(36).slice(2),
    );
    await mkdir(tmpDir, { recursive: true });
    savedEnv = {};
    for (const key of [
      "EMBER_HOME",
      "EMBER_GPU_FREE",
      "EMBER_MODEL_NAME",
      "EMBER_MODEL_SEAT",
      "EMBER_MODEL_URL",
      "EMBER_REFERENCE_SEAT",
    ]) {
      savedEnv[key] = process.env[key];
      delete process.env[key];
    }
    // Isolated home so no real models.json on this machine leaks a model
    // name/endpoint into these tests -- otherwise the contract's identity
    // is indistinguishable from a real operator config.
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    for (const [key, value] of Object.entries(savedEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("calls selectedModelContract exactly once while constructing a REFERENCE_ONLY seat, and EMBER_MODEL_NAME comes from its result", async () => {
    // Isolated: an explicit endpoint avoids the managed-spawn binary-detection
    // path entirely -- this test is about seat/contract wiring, not launch.
    process.env["EMBER_MODEL_URL"] = "http://127.0.0.1:8082";

    let callCount = 0;
    const countingContractFn = (decision: ModelSeatDecision): SelectedModelContract | undefined => {
      callCount += 1;
      return selectedModelContract(decision);
    };

    let exitCode = -1;
    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      selectedModelContractFn: countingContractFn,
      spawnServer: async () => makeFakeHandle(29911),
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: fakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: (code: number) => { exitCode = code; },
    });

    expect(exitCode).toBe(0);
    // Exactly once per seat construction -- not zero (dead code), not
    // called again downstream for the same decision.
    expect(callCount).toBe(1);
    expect(process.env["EMBER_MODEL_NAME"]).toBe("REFERENCE_ONLY: unidentified-model");
  });

  it("threads an explicit reference model identity through seatInput into the produced contract's modelName", async () => {
    process.env["EMBER_MODEL_NAME"] = "Qwen2.5-72B-Instruct";
    process.env["EMBER_MODEL_URL"] = "http://127.0.0.1:8082";
    let exitCode = -1;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      spawnServer: async () => makeFakeHandle(29912),
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: fakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: (code: number) => { exitCode = code; },
    });

    expect(exitCode).toBe(0);
    expect(process.env["EMBER_MODEL_NAME"]).toBe("REFERENCE_ONLY: Qwen2.5-72B-Instruct");
  });

  it("NEGATIVE: a missing contract for an owned seat fails loudly, never a silent fallback to a hardcoded/raw name", async () => {
    let stderr = "";
    const originalStderr = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((chunk: string) => {
      stderr += chunk;
      return true;
    }) as typeof process.stderr.write;

    let exitCode = -1;
    let headlessCalled = false;

    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        // Seat resolution succeeds (an owned identity is admitted)...
        loadOwnedIdentityFn: () => ({
          checkpointSha256: "a".repeat(64),
          endpointUrl: "http://127.0.0.1:9",
          identityUrl: "http://127.0.0.1:9/v1/models",
          modelConfigSha256: "b".repeat(64),
          modelName: "ember-owned:" + "a".repeat(12),
          serverSourceSha256: "c".repeat(64),
          tokenizerSha256: "d".repeat(64),
        }),
        handshakeEmberLabFn: async () => {},
        ensureOwnedServerFn: async () => ({
          outcome: "spawned",
          port: 9,
          handle: { process: { pid: 1 }, port: 9, kill: () => {} } as never,
        }),
        verifyOwnedEndpointFn: async () => {},
        // ...but the contract derivation for that same decision fails
        // (simulating a bug: e.g. an owned decision that lost its identity
        // between resolution and contract derivation).
        selectedModelContractFn: () => undefined,
        initFn: async () => {},
        getLoopDepsFn: fakeDeps,
        headlessRunner: async () => {
          headlessCalled = true;
          return { events: [], exitCode: 0 };
        },
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = originalStderr;
    }

    expect(exitCode).toBe(1);
    expect(headlessCalled).toBe(false);
    expect(stderr).toContain("no contract");
    // The failure must never silently fall back to the raw ownedIdentity
    // modelName as if nothing were wrong.
    expect(process.env["EMBER_MODEL_NAME"]).not.toBe("ember-owned:" + "a".repeat(12));
  });
});
