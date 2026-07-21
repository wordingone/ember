// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/model.test.ts — unit tests for the /model command.

import { describe, it, expect, beforeEach } from "bun:test";
import { createModelCommand, _makeKillReceiptWriter, _resolveModelIdentity, type ResolvedModelIdentity } from "./model.ts";
import {
  resetModelLifecycleForTests,
  registerManagedModel,
  unloadModel,
  type ModelLifecycleDeps,
} from "../services/model-lifecycle.ts";
import type { CommandContext } from "../types/command-types.ts";
import type { OwnedModelIdentity } from "../entrypoints/model-seat.ts";
import type { EnsureOwnedServerResult } from "../entrypoints/owned-server-supervisor.ts";
// cond3 procreg: import the REAL verifier (never reimplement) so the new
// status-report binding is exercised against its actual comparison logic,
// with only the network fetch stubbed.
import { verifyOwnedEndpointIdentity as realVerifyOwnedEndpointIdentity } from "../entrypoints/owned-seat-loader.ts";
import { join } from "path";

const FIXTURE_DIR = join(import.meta.dir, "__fixtures__", "model-identity");
const FIXTURE_MANIFEST = join(FIXTURE_DIR, "manifest.json");
const FIXTURE_CHECKPOINT = join(FIXTURE_DIR, "checkpoint");
const FIXTURE_BYTE_SHA256 = "6f2e653556dc9162d1b22ec49e522334d6ed4127b1f9696a0f43ad61fcf4906f";
const FIXTURE_DISPOSITION = "OWNED_CANDIDATE";

/** Stand-in resolved identity for tests that don't exercise the real subprocess. */
const fakeIdentity: ResolvedModelIdentity = {
  byte_sha256: "a".repeat(64),
  disposition: "OWNED_CANDIDATE",
  data: {
    corpus_id: "fake-corpus",
    sha256: "b".repeat(64),
    ordering_sha256: "c".repeat(64),
    curriculum_sha256: "d".repeat(64),
    verifier_sha256: "e".repeat(64),
    clean_genesis: true,
    accepted_input: {
      input_id: "fake-input-id",
      authority_id: "fake-authority-id",
    },
  },
  tokenizer: {
    id: "fake-tokenizer",
    sha256: "f".repeat(64),
  },
};

/**
 * cond item4: a minimal owned model identity carrying the checkpoint/tokenizer/
 * authority the supervisor is expected to receive. Only the fields the wiring
 * forwards are populated; cast because the full OwnedModelIdentity is large and
 * the supervisor call is stubbed in these tests.
 */
const fakeOwnedIdentity = {
  checkpointSha256: "1".repeat(64),
  endpointUrl: "http://127.0.0.1:29777/",
  launch: {
    mode: "INTERACTIVE",
    authorityKind: "ADMISSION",
    checkpointDir: "/owned/ckpt",
    tokenizerPath: "/owned/tok.json",
  },
} as unknown as OwnedModelIdentity;

/** cond item4: a stubbed "spawned" supervisor result — no real process/server. */
function spawnedResult(pid: number): EnsureOwnedServerResult {
  return {
    outcome: "spawned",
    port: 29777,
    handle: { process: { pid }, port: 29777, kill: () => {} } as never,
  };
}

describe("model command", () => {
  const mockCtx: CommandContext = {
    sessionId: "test-session",
    mode: "test",
    cwd: "/test",
  };

  // =========================================================================
  // AC8: registered in registry as "model", no alias collision
  // =========================================================================
  describe("AC8: command registration", () => {
    it("has name 'model' and is enabled", () => {
      const cmd = createModelCommand();
      expect(cmd.name).toBe("model");
      expect(cmd.isEnabled()).toBe(true);
      expect(cmd.description).toContain("model");
    });
  });

  // =========================================================================
  // AC9: /model status returns current state + pid
  // =========================================================================
  describe("AC9: /model status", () => {
    it("returns the current model state", async () => {
      const mockState = "loaded";

      const cmd = createModelCommand({
        getModelState: () => mockState,
        resolveModelIdentity: async () => fakeIdentity,
        // cond3 procreg: "loaded" is now re-verified against the owned
        // endpoint identity on every status read; bind a passing stub so
        // this test keeps exercising the reported-state contract.
        loadOwnedIdentity: () => fakeOwnedIdentity,
        verifyOwnedEndpointIdentity: async () => {},
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("model:");
      expect(result?.message).toContain(mockState);
    });

    it("handles unloaded state", async () => {
      const cmd = createModelCommand({
        getModelState: () => "unloaded",
        resolveModelIdentity: async () => fakeIdentity,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("unloaded");
    });

    it("handles external state", async () => {
      const cmd = createModelCommand({
        getModelState: () => "external",
        resolveModelIdentity: async () => fakeIdentity,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("external");
    });

    it("treats empty args as status", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => fakeOwnedIdentity,
        verifyOwnedEndpointIdentity: async () => {},
      });

      const result = await cmd.execute("", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("model:");
    });
  });

  // =========================================================================
  // cond3 inc2a: /model status|load checkpoint-identity binding (fail-closed)
  // =========================================================================
  describe("cond3 inc2a: checkpoint identity binding", () => {
    it("(a) /model status with valid identity renders byte_sha256 and disposition", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async (manifestPath) => {
          expect(manifestPath).toBe(FIXTURE_MANIFEST);
          return { ...fakeIdentity, byte_sha256: FIXTURE_BYTE_SHA256, disposition: FIXTURE_DISPOSITION };
        },
        manifestPath: FIXTURE_MANIFEST,
        loadOwnedIdentity: () => fakeOwnedIdentity,
        verifyOwnedEndpointIdentity: async () => {},
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBeUndefined();
      expect(result?.message).toContain(FIXTURE_BYTE_SHA256);
      expect(result?.message).toContain(FIXTURE_DISPOSITION);
    });

    it("(b) /model status with missing/unresolvable manifest still reports state, but marks identity UNVERIFIED (never a false sha, never a hard error)", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async () => null,
        manifestPath: "/does/not/exist/model-identity.json",
        loadOwnedIdentity: () => fakeOwnedIdentity,
        verifyOwnedEndpointIdentity: async () => {},
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      // status is a read-only state query -- a missing manifest must NOT break it.
      expect(result?.exitCode).toBeUndefined();
      // Core job: report whether the model is loaded.
      expect(result?.message).toContain("model: loaded");
      // Fail-closed at the render level: explicit UNVERIFIED marker, never a
      // guessed/bare sha presented as if validated.
      expect(result?.message).toContain("UNVERIFIED");
      expect(result?.message).not.toMatch(/identity: [0-9a-f]{64}/);
    });

    it("(c) /model load rejects (fail-closed, non-zero exit) when validation fails, never spawning", async () => {
      let loadCalled = false;
      const cmd = createModelCommand({
        loadModel: async () => {
          loadCalled = true;
          return "model loaded (pid 1)";
        },
        resolveModelIdentity: async () => null,
        manifestPath: "/does/not/exist/model-identity.json",
      });

      const result = await cmd.execute("load", mockCtx);

      expect(loadCalled).toBe(false);
      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("error");
      expect(result?.message).toContain("checkpoint identity validation failed");
    });

    it("(c') /model load proceeds to the owned supervisor only after identity resolves", async () => {
      let loadCalled = false;
      const cmd = createModelCommand({
        loadModel: async (deps) => {
          loadCalled = true;
          expect(deps.manifestPath).toBe(FIXTURE_MANIFEST);
          return "model loaded (pid 42)";
        },
        resolveModelIdentity: async () => ({
          ...fakeIdentity,
          byte_sha256: FIXTURE_BYTE_SHA256,
          disposition: FIXTURE_DISPOSITION,
        }),
        // cond item4: the real serving path is now reached via ensureOwnedServer;
        // stub the owned-identity load + supervisor so no real process spawns.
        loadOwnedIdentity: () => fakeOwnedIdentity,
        ensureOwnedServer: async () => spawnedResult(42),
        registerManagedModel: () => {},
        manifestPath: FIXTURE_MANIFEST,
      });

      const result = await cmd.execute("load", mockCtx);

      expect(loadCalled).toBe(true);
      expect(result?.exitCode).toBeUndefined();
      expect(result?.message).toContain("loaded");
    });

    // -----------------------------------------------------------------------
    // cond item4: /model load routes to the REAL owned-server supervisor
    // (ensureOwnedServer) with the loaded checkpoint's identity, fail-closed.
    // The actual process spawn / server endpoint is STUBBED here -- no real
    // server, no GPU, no served capability.
    // -----------------------------------------------------------------------
    it("(item4-a) /model load invokes ensureOwnedServer with the loaded checkpoint/tokenizer/authority identity", async () => {
      let ensureCalls = 0;
      let receivedIdentity: OwnedModelIdentity | null = null;
      let registeredPid: number | null = null;
      const cmd = createModelCommand({
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => fakeOwnedIdentity,
        ensureOwnedServer: async (identity) => {
          ensureCalls += 1;
          receivedIdentity = identity;
          return spawnedResult(4242);
        },
        registerManagedModel: (handle) => {
          registeredPid = handle.pid;
        },
        manifestPath: FIXTURE_MANIFEST,
      });

      const result = await cmd.execute("load", mockCtx);

      // The command routed to the real supervisor exactly once, handing it the
      // loaded checkpoint's identity (its checkpoint dir, tokenizer path, and
      // authority kind) -- proving the wiring is real, not a pid:0 stub.
      expect(ensureCalls).toBe(1);
      // TS narrows these `let`s to their initial `null` literal at this read
      // point (control-flow analysis does not see the reassignment inside the
      // mocked callbacks above) -- the `as` casts restore the declared union
      // type; the assertions themselves are unchanged.
      expect(receivedIdentity as OwnedModelIdentity | null).toBe(fakeOwnedIdentity);
      expect(receivedIdentity!.launch?.checkpointDir).toBe("/owned/ckpt");
      expect(receivedIdentity!.launch?.tokenizerPath).toBe("/owned/tok.json");
      expect(receivedIdentity!.launch?.authorityKind).toBe("ADMISSION");
      // The supervisor-established child is tracked by the lifecycle panel.
      expect(registeredPid as number | null).toBe(4242);
      expect(result?.exitCode).toBeUndefined();
      expect(result?.message).toContain("loaded");
    });

    it("(item4-b) /model load is fail-closed: an identity/authority mismatch from the supervisor REJECTS the load, never registering a served model", async () => {
      let registerCalled = false;
      const cmd = createModelCommand({
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => fakeOwnedIdentity,
        // Simulates verifyOwnedEndpointIdentity throwing inside ensureOwnedServer
        // (a served endpoint whose identity/authority does not match the loaded
        // checkpoint) -- the exact fail-closed rejection init relies on.
        ensureOwnedServer: async () => {
          throw new Error("owned endpoint identity mismatch: refusing to bind");
        },
        registerManagedModel: () => {
          registerCalled = true;
        },
        manifestPath: FIXTURE_MANIFEST,
      });

      const result = await cmd.execute("load", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("error");
      expect(result?.message).toContain("identity mismatch");
      // Fail-closed: nothing was registered as loaded/served.
      expect(registerCalled).toBe(false);
    });

    it("(item4-c) /model load fails closed when no owned identity is available (offline/reference seat), never calling the supervisor", async () => {
      let ensureCalled = false;
      const cmd = createModelCommand({
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => null,
        ensureOwnedServer: async () => {
          ensureCalled = true;
          return spawnedResult(1);
        },
        registerManagedModel: () => {},
        manifestPath: FIXTURE_MANIFEST,
      });

      const result = await cmd.execute("load", mockCtx);

      expect(ensureCalled).toBe(false);
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("no owned model identity available");
    });

    it("(d) _resolveModelIdentity handles subprocess failure gracefully (returns null, never throws)", async () => {
      const throwingRunner = () => {
        throw new Error("spawnSync exploded");
      };
      // The default runner itself catches spawnSync throws; exercise both the
      // injected-runner path and a runner that reports a crash via status.
      await expect(_resolveModelIdentity(FIXTURE_MANIFEST, () => {
        throw new Error("runner threw");
      })).resolves.toBeNull();

      await expect(_resolveModelIdentity(FIXTURE_MANIFEST, () => ({
        status: null,
        stdout: "",
      }))).resolves.toBeNull();

      await expect(_resolveModelIdentity(FIXTURE_MANIFEST, () => ({
        status: 1,
        stdout: "not json at all {{{",
      }))).resolves.toBeNull();

      await expect(_resolveModelIdentity(FIXTURE_MANIFEST, () => ({
        status: 0,
        stdout: "not json at all {{{",
      }))).resolves.toBeNull();

      await expect(_resolveModelIdentity("/definitely/does/not/exist.json")).resolves.toBeNull();

      void throwingRunner;
    });

    it("real round trip: a REAL tiny checkpoint bound to a REAL manifest resolves real sha256 + disposition", async () => {
      const identity = await _resolveModelIdentity(FIXTURE_MANIFEST);

      expect(identity).not.toBeNull();
      expect(identity?.byte_sha256).toBe(FIXTURE_BYTE_SHA256);
      expect(identity?.disposition).toBe(FIXTURE_DISPOSITION);

      // Sanity: the fixture checkpoint file exists and really is what the
      // manifest claims -- this is not a hand-typed constant.
      const { createHash } = await import("crypto");
      const { readFileSync } = await import("fs");
      const bytes = readFileSync(FIXTURE_CHECKPOINT);
      const actualSha256 = createHash("sha256").update(bytes).digest("hex");
      expect(actualSha256).toBe(FIXTURE_BYTE_SHA256);
    });

    it("real round trip: tampering with the checkpoint bytes fails closed (null, never a stale identity)", async () => {
      const { mkdtempSync, writeFileSync, rmSync, readFileSync } = await import("fs");
      const { tmpdir } = await import("os");
      const { join: pathJoin } = await import("path");

      const tmpDir = mkdtempSync(pathJoin(tmpdir(), "ember-model-identity-tamper-"));
      try {
        const manifestCopy = pathJoin(tmpDir, "manifest.json");
        const checkpointCopy = pathJoin(tmpDir, "checkpoint");
        writeFileSync(manifestCopy, readFileSync(FIXTURE_MANIFEST));
        writeFileSync(checkpointCopy, "tampered-bytes-do-not-match-manifest-hash");

        const identity = await _resolveModelIdentity(manifestCopy);
        expect(identity).toBeNull();
      } finally {
        rmSync(tmpDir, { recursive: true, force: true });
      }
    });

    it("real round trip: /model manifest inspect renders validated data + tokenizer lineage", async () => {
      const cmd = createModelCommand({
        manifestPath: FIXTURE_MANIFEST,
      });

      const result = await cmd.execute("manifest inspect", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("manifest inspect:");
      expect(result?.message).toContain("data.corpus_id:");
      expect(result?.message).toContain("data.sha256:");
      expect(result?.message).toContain("data.ordering_sha256:");
      expect(result?.message).toContain("data.curriculum_sha256:");
      expect(result?.message).toContain("data.verifier_sha256:");
      expect(result?.message).toContain("data.clean_genesis:");
      expect(result?.message).toContain("data.accepted_input.input_id:");
      expect(result?.message).toContain("data.accepted_input.authority_id:");
      expect(result?.message).toContain("tokenizer.id:");
      expect(result?.message).toContain("tokenizer.sha256:");
      // Ensure no exit code on success
      expect(result?.exitCode).toBeUndefined();
    });
  });

  // =========================================================================
  // cond3 process_registry_watchdog binding: "/model status" must derive its
  // reported owned-runtime state from manifest-bound control-plane authority
  // (verifyOwnedEndpointIdentity), never from the cached in-memory flag
  // alone. Binds the REAL consumer (createModelCommand's status handler) and
  // the REAL verifier (owned-seat-loader.ts, only its fetch stubbed) --
  // mirrors the proven-negative shape at
  // services/brain-server-supervisor.test.ts:448-456 (pid-reuse reclaim).
  // =========================================================================
  describe("cond3 procreg: /model status re-verifies owned endpoint identity", () => {
    const verifiedIdentity = {
      checkpointSha256: "1".repeat(64),
      endpointUrl: "http://127.0.0.1:29777/",
      identityUrl: "http://127.0.0.1:29777/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + "1".repeat(12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    } as unknown as OwnedModelIdentity;

    const matchingPayload = {
      seat: "OWNED_ADMITTED",
      mode: "INTERACTIVE",
      checkpoint_sha256: verifiedIdentity.checkpointSha256,
      model_name: verifiedIdentity.modelName,
      model_config_sha256: verifiedIdentity.modelConfigSha256,
      server_source_sha256: verifiedIdentity.serverSourceSha256,
      tokenizer_sha256: verifiedIdentity.tokenizerSha256,
    };

    it("POSITIVE: a manifest-verified owned endpoint IS reported as loaded", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => verifiedIdentity,
        verifyOwnedEndpointIdentity: (identity) =>
          realVerifyOwnedEndpointIdentity(identity, async () => Response.json(matchingPayload)),
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("model: loaded");
    });

    it("NEGATIVE-1: an ambient/pid-reused process (mismatched response shape) is NOT reported as loaded", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => verifiedIdentity,
        // Simulates a pid-reused ambient process (e.g. notepad.exe) now
        // holding the port: it answers HTTP, but not with our identity
        // contract -- the REAL verifier rejects this (mirrors the proven
        // negative at brain-server-supervisor.test.ts:448-456).
        verifyOwnedEndpointIdentity: (identity) =>
          realVerifyOwnedEndpointIdentity(identity, async () => Response.json({ notARealField: true })),
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).not.toContain("model: loaded");
      expect(result?.message).toContain("model: unloaded");
    });

    it("NEGATIVE-2: a live process on the owned port with a MISMATCHED checkpoint identity (manifest sha mismatch) is NOT reported as loaded", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => verifiedIdentity,
        // Live, well-formed response -- but bound to a DIFFERENT checkpoint
        // sha than the identity this session admitted. Fail-closed via
        // verifyOwnedEndpointIdentity's own checkpoint_sha256 comparison.
        verifyOwnedEndpointIdentity: (identity) =>
          realVerifyOwnedEndpointIdentity(
            identity,
            async () => Response.json({ ...matchingPayload, checkpoint_sha256: "9".repeat(64) }),
          ),
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).not.toContain("model: loaded");
      expect(result?.message).toContain("model: unloaded");
    });

    it("no owned identity available at all (offline/reference seat) fails closed rather than reporting loaded", async () => {
      const cmd = createModelCommand({
        getModelState: () => "loaded",
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => null,
        verifyOwnedEndpointIdentity: async () => {
          throw new Error("must not be called when there is no identity to verify against");
        },
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.message).toContain("model: unloaded");
    });

    it("external mode is untouched -- never re-verified, never overridden", async () => {
      const originalEnv = process.env["EMBER_MODEL_URL"];
      process.env["EMBER_MODEL_URL"] = "http://127.0.0.1:9/external";
      try {
        const cmd = createModelCommand({
          getModelState: () => "external",
          resolveModelIdentity: async () => fakeIdentity,
          loadOwnedIdentity: () => {
            throw new Error("must not be called in external mode");
          },
        });

        const result = await cmd.execute("status", mockCtx);
        expect(result?.message).toContain("model: external");
      } finally {
        if (originalEnv === undefined) delete process.env["EMBER_MODEL_URL"];
        else process.env["EMBER_MODEL_URL"] = originalEnv;
      }
    });
  });

  // =========================================================================
  // /model checkpoint save -- CLI routing/wiring only. The atomic-copy/
  // fail-closed CORE is covered against a fixture in
  // services/checkpoint-save.test.ts; these tests only prove the subcommand
  // parses args and wires them into saveCheckpoint correctly.
  // =========================================================================
  describe("/model checkpoint save", () => {
    it("resolves source from the currently-loaded manifestPath convention by default", async () => {
      const cmd = createModelCommand({
        manifestPath: FIXTURE_MANIFEST,
        checkpointSaveDeps: {
          resolveIdentity: async (manifestPath) => {
            expect(manifestPath).toBe(FIXTURE_MANIFEST);
            return fakeIdentity;
          },
          mkdir: async () => {},
          copyFile: async () => {},
          rename: async () => {},
          rmStaging: async () => {},
          stagingPath: (target) => `${target}.tmp`,
        },
      });

      const result = await cmd.execute("checkpoint save /tmp/target-dir", mockCtx);

      expect(result?.exitCode).toBeUndefined();
      expect(result?.message).toContain(fakeIdentity.byte_sha256);
      expect(result?.message).toContain("target-dir");
    });

    it("honors --source to override the default currently-loaded manifest", async () => {
      let resolvedManifest: string | undefined;
      const cmd = createModelCommand({
        manifestPath: FIXTURE_MANIFEST,
        checkpointSaveDeps: {
          resolveIdentity: async (manifestPath) => {
            resolvedManifest = manifestPath;
            return fakeIdentity;
          },
          mkdir: async () => {},
          copyFile: async () => {},
          rename: async () => {},
          rmStaging: async () => {},
          stagingPath: (target) => `${target}.tmp`,
        },
      });

      await cmd.execute("checkpoint save /tmp/target-dir --source /tmp/reference-checkpoint", mockCtx);

      expect(resolvedManifest).toBe(join("/tmp/reference-checkpoint", "manifest.json"));
    });

    it("fails closed (non-zero exit) when identity does not validate, and never writes", async () => {
      let mkdirCalled = false;
      const cmd = createModelCommand({
        manifestPath: FIXTURE_MANIFEST,
        checkpointSaveDeps: {
          resolveIdentity: async () => null,
          mkdir: async () => {
            mkdirCalled = true;
          },
          copyFile: async () => {},
          rename: async () => {},
          rmStaging: async () => {},
          stagingPath: (target) => `${target}.tmp`,
        },
      });

      const result = await cmd.execute("checkpoint save /tmp/target-dir", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("error");
      expect(mkdirCalled).toBe(false);
    });

    it("usage line when target-dir is missing", async () => {
      const cmd = createModelCommand();
      const result = await cmd.execute("checkpoint save", mockCtx);
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("usage:");
    });

    it("usage line for an unknown checkpoint action", async () => {
      const cmd = createModelCommand();
      const result = await cmd.execute("checkpoint frobnicate", mockCtx);
      expect(result?.message).toContain("usage:");
    });
  });

  // =========================================================================
  // AC10: /model unload calls unloadModel, /model load calls loadModel
  // =========================================================================
  describe("AC10: /model unload", () => {
    it("calls unloadModel and returns its status", async () => {
      const unloadCalls: string[] = [];

      const cmd = createModelCommand({
        unloadModel: async () => {
          unloadCalls.push("called");
          return "model unloaded (pid 1234 freed)";
        },
      });

      const result = await cmd.execute("unload", mockCtx);

      expect(unloadCalls.length).toBe(1);
      expect(result?.type).toBe("message");
      expect(result?.message).toContain("unloaded");
    });

    it("handles errors from unloadModel", async () => {
      const cmd = createModelCommand({
        unloadModel: async () => {
          throw new Error("kill failed");
        },
      });

      const result = await cmd.execute("unload", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("error");
      expect(result?.message).toContain("kill failed");
    });
  });

  describe("AC10: /model load", () => {
    it("calls loadModel and returns its status", async () => {
      const loadCalls: string[] = [];

      const cmd = createModelCommand({
        loadModel: async () => {
          loadCalls.push("called");
          return "model loaded (pid 5678)";
        },
        resolveModelIdentity: async () => fakeIdentity,
        // cond item4: the real serving path is reached via ensureOwnedServer;
        // stub the owned-identity load + supervisor so no real process spawns.
        loadOwnedIdentity: () => fakeOwnedIdentity,
        ensureOwnedServer: async () => spawnedResult(5678),
        registerManagedModel: () => {},
      });

      const result = await cmd.execute("load", mockCtx);

      expect(loadCalls.length).toBe(1);
      expect(result?.type).toBe("message");
      expect(result?.message).toContain("loaded");
    });

    it("handles errors from loadModel", async () => {
      const cmd = createModelCommand({
        loadModel: async () => {
          throw new Error("spawn failed");
        },
        resolveModelIdentity: async () => fakeIdentity,
        loadOwnedIdentity: () => fakeOwnedIdentity,
        ensureOwnedServer: async () => spawnedResult(1),
        registerManagedModel: () => {},
      });

      const result = await cmd.execute("load", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("error");
      expect(result?.message).toContain("spawn failed");
    });
  });

  // =========================================================================
  // /model manifest inspect — read-only identity lineage exposure
  // =========================================================================
  describe("/model manifest inspect", () => {
    it("renders data + tokenizer lineage when manifest is valid", async () => {
      const testIdentity: ResolvedModelIdentity = {
        byte_sha256: "a".repeat(64),
        disposition: "OWNED_CANDIDATE",
        data: {
          corpus_id: "test-corpus",
          sha256: "b".repeat(64),
          ordering_sha256: "c".repeat(64),
          curriculum_sha256: "d".repeat(64),
          verifier_sha256: "e".repeat(64),
          clean_genesis: true,
          accepted_input: {
            input_id: "test-input-id",
            authority_id: "test-authority-id",
          },
        },
        tokenizer: {
          id: "test-tokenizer",
          sha256: "f".repeat(64),
        },
      };

      const cmd = createModelCommand({
        resolveModelIdentity: async () => testIdentity,
      });

      const result = await cmd.execute("manifest inspect", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("manifest inspect:");
      expect(result?.message).toContain("data.corpus_id: test-corpus");
      expect(result?.message).toContain(`data.sha256: ${"b".repeat(64)}`);
      expect(result?.message).toContain(`data.ordering_sha256: ${"c".repeat(64)}`);
      expect(result?.message).toContain(`data.curriculum_sha256: ${"d".repeat(64)}`);
      expect(result?.message).toContain(`data.verifier_sha256: ${"e".repeat(64)}`);
      expect(result?.message).toContain("data.clean_genesis: true");
      expect(result?.message).toContain("data.accepted_input.input_id: test-input-id");
      expect(result?.message).toContain("data.accepted_input.authority_id: test-authority-id");
      expect(result?.message).toContain("tokenizer.id: test-tokenizer");
      expect(result?.message).toContain(`tokenizer.sha256: ${"f".repeat(64)}`);
    });

    it("renders UNVERIFIED when manifest is missing/invalid (fail-closed)", async () => {
      const cmd = createModelCommand({
        resolveModelIdentity: async () => null,
        manifestPath: "/does/not/exist/model-identity.json",
      });

      const result = await cmd.execute("manifest inspect", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("UNVERIFIED");
      expect(result?.message).toContain("no validated manifest");
    });

    it("handles missing manifest inspect subcommand gracefully", async () => {
      const cmd = createModelCommand();

      const result = await cmd.execute("manifest", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("usage:");
      expect(result?.message).toContain("manifest inspect");
    });

    it("never crashes on extra args", async () => {
      const cmd = createModelCommand({
        resolveModelIdentity: async () => fakeIdentity,
      });

      const result = await cmd.execute("manifest inspect extra args", mockCtx);

      expect(result).not.toBeNull();
      expect(result?.type).toBe("message");
    });
  });

  // =========================================================================
  // AC10: unknown subcommand → usage line
  // =========================================================================
  describe("AC10: unknown subcommand", () => {
    it("returns usage line for unknown subcommand", async () => {
      const cmd = createModelCommand();

      const result = await cmd.execute("invalid", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("usage:");
      expect(result?.message).toContain("status");
      expect(result?.message).toContain("load");
      expect(result?.message).toContain("unload");
    });

    it("never crashes on any input", async () => {
      const cmd = createModelCommand({
        getModelState: () => "unloaded",
        loadModel: async () => "model loaded (pid 1234)",
        unloadModel: async () => "model unloaded (pid 1234 freed)",
        resolveModelIdentity: async () => fakeIdentity,
      });

      const tests = ["", " ", "foobar", "load extra args", "unload 123"];

      for (const test of tests) {
        const result = await cmd.execute(test, mockCtx);
        expect(result).not.toBeNull();
        expect(result?.type).toBe("message");
      }
    });
  });

  // =========================================================================
  // realWriteKillReceipt: AC wiring test — writeKillReceipt flows through deps
  // =========================================================================
  describe("AC wiring: writeKillReceipt injected into ModelLifecycleDeps for unload", () => {
    it("passes the injected writeKillReceipt into the lifecycle deps object", async () => {
      const capturedDeps: ModelLifecycleDeps[] = [];
      const mockReceipt = async (_rec: { pid: number; match_rule: string }) => {};

      const cmd = createModelCommand({
        unloadModel: async (deps) => {
          capturedDeps.push(deps);
          return "model unloaded (pid 9999 freed)";
        },
        writeKillReceipt: mockReceipt,
      });

      await cmd.execute("unload", mockCtx);

      expect(capturedDeps.length).toBe(1);
      // The exact same function reference must be wired in
      expect(capturedDeps[0]!.writeKillReceipt).toBe(mockReceipt);
    });
  });
});

// =============================================================================
// _makeKillReceiptWriter — unit tests for JSONL format (no live FS)
// =============================================================================

describe("_makeKillReceiptWriter — JSONL format via injected appendFileFn", () => {
  it("appends a well-formed JSONL entry with all required fields", async () => {
    const captured: Array<{ path: string; data: string }> = [];

    const writer = _makeKillReceiptWriter({
      ledgerPath: "/fake/kill-receipts.jsonl",
      appendFileFn: async (path, data) => {
        captured.push({ path, data });
      },
    });

    writer({ pid: 4321, match_rule: "model child spawned this session" });

    // flush microtask queue so the fire-and-forget promise resolves
    await new Promise<void>((r) => setTimeout(r, 0));

    expect(captured.length).toBe(1);
    const raw = captured[0]!.data.trim();
    // Must be valid JSON
    let entry: Record<string, unknown>;
    expect(() => {
      entry = JSON.parse(raw);
    }).not.toThrow();
    entry = JSON.parse(raw);

    // ts: ISO8601Z timestamp
    expect(typeof entry["ts"]).toBe("string");
    expect(entry["ts"] as string).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);

    // script: must reference "ember" or "model"
    expect(typeof entry["script"]).toBe("string");
    expect(entry["script"] as string).toMatch(/ember|model/i);

    // pids: array containing the given pid
    expect(Array.isArray(entry["pids"])).toBe(true);
    expect(entry["pids"]).toEqual([4321]);

    // match_rule: matches the input
    expect(entry["match_rule"]).toBe("model child spawned this session");

    // survivors_expected: "none" or a numeric string
    const se = entry["survivors_expected"] as string;
    expect(se === "none" || /^\d+$/.test(se)).toBe(true);
  });

  it("writes to the exact ledger path provided", async () => {
    const capturedPaths: string[] = [];

    const writer = _makeKillReceiptWriter({
      ledgerPath: "/custom/vigil/receipts.jsonl",
      appendFileFn: async (path, _data) => {
        capturedPaths.push(path);
      },
    });

    writer({ pid: 111, match_rule: "test-rule" });
    await new Promise<void>((r) => setTimeout(r, 0));

    expect(capturedPaths.length).toBe(1);
    expect(capturedPaths[0]).toBe("/custom/vigil/receipts.jsonl");
  });

  // issue #881: the old writer swallowed I/O failures fire-and-forget, so /model unload
  // could report success with NO durable receipt ever landing. It must now be durable —
  // an I/O failure REJECTS the returned promise so the caller (unloadModel) can fail
  // closed instead of releasing the child with no audit trail.
  it("rejects (durable) on I/O failure — never swallows, always propagates", async () => {
    const writer = _makeKillReceiptWriter({
      ledgerPath: "/fake/path.jsonl",
      appendFileFn: async () => {
        throw new Error("ENOSPC: disk full");
      },
    });

    await expect(writer({ pid: 999, match_rule: "test" })).rejects.toThrow(/ENOSPC/);
  });

  // issue #881: path routing — EMBER_KILL_RECEIPTS_PATH is the SAME env var
  // services/activity-feed.ts resolves the authoritative shared vigil kill-receipts
  // ledger from. The writer must honor it (not the old cwd-relative default that
  // nothing else tail-polls).
  it("honors EMBER_KILL_RECEIPTS_PATH — the authoritative vigil ledger env var", async () => {
    const prior = process.env["EMBER_KILL_RECEIPTS_PATH"];
    process.env["EMBER_KILL_RECEIPTS_PATH"] = "/authoritative/vigil/kill-receipts.jsonl";
    try {
      const capturedPaths: string[] = [];
      const writer = _makeKillReceiptWriter({
        appendFileFn: async (path, _data) => {
          capturedPaths.push(path);
        },
      });
      await writer({ pid: 222, match_rule: "test" });
      expect(capturedPaths).toEqual(["/authoritative/vigil/kill-receipts.jsonl"]);
    } finally {
      if (prior === undefined) delete process.env["EMBER_KILL_RECEIPTS_PATH"];
      else process.env["EMBER_KILL_RECEIPTS_PATH"] = prior;
    }
  });

  it("appends a newline after the JSON so the file is valid JSONL", async () => {
    const captured: string[] = [];

    const writer = _makeKillReceiptWriter({
      ledgerPath: "/fake/ledger.jsonl",
      appendFileFn: async (_path, data) => {
        captured.push(data);
      },
    });

    writer({ pid: 777, match_rule: "line-end-check" });
    await new Promise<void>((r) => setTimeout(r, 0));

    expect(captured.length).toBe(1);
    expect(captured[0]!.endsWith("\n")).toBe(true);
  });
});

// =============================================================================
// writeKillReceipt call order — receipt-before-kill invariant via unloadModel seam
// =============================================================================

describe("writeKillReceipt call-order invariant — via model-lifecycle seam", () => {
  beforeEach(() => {
    resetModelLifecycleForTests();
  });

  it("receipt is written exactly once and strictly before killPid", async () => {
    const callOrder: string[] = [];

    registerManagedModel({ pid: 5001 });

    const deps: ModelLifecycleDeps = {
      spawnModel: () => ({ pid: 0 }),
      killPid: (pid) => {
        callOrder.push(`kill(${pid})`);
      },
      waitReady: async () => {},
      writeKillReceipt: async (rec) => {
        callOrder.push(`receipt(${rec.pid})`);
      },
      isExternal: () => false,
      now: () => new Date().toISOString(),
    };

    await unloadModel(deps);

    expect(callOrder).toEqual(["receipt(5001)", "kill(5001)"]);
  });

  it("writeKillReceipt is called only once on double unload (idempotency)", async () => {
    const receiptPids: number[] = [];

    registerManagedModel({ pid: 5002 });

    const deps: ModelLifecycleDeps = {
      spawnModel: () => ({ pid: 0 }),
      killPid: () => {},
      waitReady: async () => {},
      writeKillReceipt: async (rec) => {
        receiptPids.push(rec.pid);
      },
      isExternal: () => false,
      now: () => new Date().toISOString(),
    };

    // first unload: kills and writes receipt
    await unloadModel(deps);
    // second unload: already unloaded, must be a no-op
    await unloadModel(deps);

    expect(receiptPids.length).toBe(1);
    expect(receiptPids[0]).toBe(5002);
  });

  it("writeKillReceipt is never called in external mode (isExternal=true)", async () => {
    const receiptCalls: number[] = [];

    const deps: ModelLifecycleDeps = {
      spawnModel: () => ({ pid: 0 }),
      killPid: () => {},
      waitReady: async () => {},
      writeKillReceipt: async (rec) => {
        receiptCalls.push(rec.pid);
      },
      isExternal: () => true, // external mode: no managed process
      now: () => new Date().toISOString(),
    };

    await unloadModel(deps);

    expect(receiptCalls.length).toBe(0);
  });
});
