// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import type { OwnedModelIdentity } from "./model-seat.ts";
import {
  buildOwnedServerCommand,
  ensureOwnedServer,
} from "./owned-server-supervisor.ts";

const CHECKPOINT = "d".repeat(64);

function identity(): OwnedModelIdentity {
  return {
    checkpointSha256: CHECKPOINT,
    endpointUrl: "http://127.0.0.1:8083",
    identityUrl: "http://127.0.0.1:8083/v1/models",
    modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
    modelFormat: "safetensors",
    serverSourceSha256: "a".repeat(64),
    launch: {
      checkpointDir: "C:\\owned\\checkpoint",
      mode: "INTERACTIVE",
      pythonExecutable: "C:\\Python\\python.exe",
      runManifestPath: "C:\\owned\\run.json",
      serverPath: "C:\\repo\\tools\\ember-restart-3b\\serve_owned_openai.py",
      tokenizerPath: "C:\\owned\\tokenizer.json",
      trustedVerifierRegistryPath: "C:\\owned\\trusted-verifiers.json",
    },
  };
}

describe("owned server supervisor", () => {
  it("builds only the exact admitted interactive launch command", () => {
    const command = buildOwnedServerCommand(identity(), "cuda");
    expect(command.executable).toBe("C:\\Python\\python.exe");
    expect(command.port).toBe(8083);
    expect(command.args).toEqual([
      "C:\\repo\\tools\\ember-restart-3b\\serve_owned_openai.py",
      "--checkpoint", "C:\\owned\\checkpoint",
      "--tokenizer", "C:\\owned\\tokenizer.json",
      "--run-manifest", "C:\\owned\\run.json",
      "--trusted-verifier-registry", "C:\\owned\\trusted-verifiers.json",
      "--host", "127.0.0.1",
      "--port", "8083",
      "--device", "cuda",
      "--mode", "INTERACTIVE",
    ]);
    expect(JSON.stringify(command)).not.toContain("qwen");
    expect(JSON.stringify(command)).not.toContain("llama-server");
  });

  it("adopts only after the live endpoint verifies exact identity", async () => {
    let verified = 0;
    let spawned = 0;
    const result = await ensureOwnedServer(identity(), {
      probePresence: async () => "present",
      verifyEndpoint: async () => { verified += 1; },
      spawnServer: () => { spawned += 1; throw new Error("must not spawn"); },
    });
    expect(result).toEqual({ outcome: "adopted", port: 8083 });
    expect(verified).toBe(1);
    expect(spawned).toBe(0);
  });

  it("spawns the exact server when absent and waits for verified readiness", async () => {
    const fakeHandle = { process: { pid: 77, kill: () => true }, port: 8083 } as never;
    let waited = 0;
    const result = await ensureOwnedServer(identity(), {
      probePresence: async () => "absent",
      spawnServer: () => fakeHandle,
      waitUntilReady: async (_identity, handle) => {
        expect(handle).toBe(fakeHandle);
        waited += 1;
      },
    });
    expect(result).toEqual({ outcome: "spawned", port: 8083, handle: fakeHandle });
    expect(waited).toBe(1);
  });

  it("surfaces asynchronous spawn errors without waiting for readiness timeout", async () => {
    const fakeHandle = {
      process: { exitCode: 1, kill: () => true },
      port: 8083,
      startupError: new Error("ENOENT python-owned"),
      kill: () => {},
    } as never;
    expect(
      ensureOwnedServer(identity(), {
        probePresence: async () => "absent",
        spawnServer: () => fakeHandle,
        verifyEndpoint: async () => { throw new Error("not ready"); },
      }),
    ).rejects.toThrow("owned server failed to start: ENOENT python-owned");
  });

  it("never spawns over a present mismatched or unverifiable endpoint", async () => {
    let spawned = 0;
    expect(
      ensureOwnedServer(identity(), {
        probePresence: async () => "present",
        verifyEndpoint: async () => { throw new Error("checkpoint mismatch"); },
        spawnServer: () => { spawned += 1; throw new Error("must not spawn"); },
      }),
    ).rejects.toThrow("checkpoint mismatch");
    expect(spawned).toBe(0);
  });

  it("fails closed when an absent endpoint lacks a launch descriptor", async () => {
    const withoutLaunch = { ...identity(), launch: undefined };
    expect(
      ensureOwnedServer(withoutLaunch, { probePresence: async () => "absent" }),
    ).rejects.toThrow("launch descriptor");
  });
});
