// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { createServer } from "node:net";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import type { OwnedModelIdentity } from "./model-seat.ts";
import {
  buildOwnedServerCommand,
  ensureOwnedServer,
  probeOwnedEndpointPresence,
} from "./owned-server-supervisor.ts";

const CHECKPOINT = "d".repeat(64);

function identity(): OwnedModelIdentity {
  return {
    checkpointSha256: CHECKPOINT,
    endpointUrl: "http://127.0.0.1:8083",
    identityUrl: "http://127.0.0.1:8083/v1/models",
    modelConfigSha256: "b".repeat(64),
    modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
    modelFormat: "safetensors",
    serverSourceSha256: "a".repeat(64),
    tokenizerSha256: "c".repeat(64),
    launch: {
      authorityKind: "ADMISSION",
      checkpointDir: "C:\\owned\\checkpoint",
      mode: "INTERACTIVE",
      modelConfigPath: "C:\\owned\\model-config.json",
      pythonExecutable: "C:\\Python\\python.exe",
      runManifestPath: "C:\\owned\\run.json",
      serverPath: "C:\\repo\\tools\\ember-restart-3b\\serve_owned_openai.py",
      tokenizerPath: "C:\\owned\\tokenizer.json",
      trustedVerifierRegistryPath: "C:\\owned\\trusted-verifiers.json",
    },
  };
}

describe("owned server supervisor", () => {
  it("treats a silent occupied TCP listener as present", async () => {
    const server = createServer(() => {});
    await new Promise<void>((resolvePromise, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolvePromise);
    });
    try {
      const address = server.address();
      if (address === null || typeof address === "string") throw new Error("missing TCP address");
      const ownedIdentity = identity();
      ownedIdentity.endpointUrl = `http://127.0.0.1:${address.port}`;
      ownedIdentity.identityUrl = ownedIdentity.endpointUrl + "/v1/models";
      expect(await probeOwnedEndpointPresence(ownedIdentity)).toBe("present");
    } finally {
      await new Promise<void>((resolvePromise) => server.close(() => resolvePromise()));
    }
  });

  it("builds only the exact admitted interactive launch command", () => {
    const command = buildOwnedServerCommand(identity(), "cuda");
    expect(command.executable).toBe("C:\\Python\\python.exe");
    expect(command.port).toBe(8083);
    expect(command.args).toEqual([
      "C:\\repo\\tools\\ember-restart-3b\\serve_owned_openai.py",
      "--checkpoint", "C:\\owned\\checkpoint",
      "--tokenizer", "C:\\owned\\tokenizer.json",
      "--config", "C:\\owned\\model-config.json",
      "--run-manifest", "C:\\owned\\run.json",
      "--trusted-verifier-registry", "C:\\owned\\trusted-verifiers.json",
      "--host", "127.0.0.1",
      "--port", "8083",
      "--device", "cuda",
      "--parent-pid", String(process.pid),
      "--mode", "INTERACTIVE",
    ]);
    expect(JSON.stringify(command)).not.toContain("qwen");
    expect(JSON.stringify(command)).not.toContain("llama-server");
  });

  it("builds the separate exact development launch command without admission arguments", () => {
    const development: OwnedModelIdentity = {
      ...identity(),
      seat: "OWNED_DEVELOPMENT",
      claimStatus: "NON_ADMISSIBLE",
      tokensSeen: 2048,
      allocatedParameters: 3_839_161_856,
      activeParameters: 1_020_589_568,
      modelName: "ember-owned-development:" + CHECKPOINT.slice(0, 12),
      launch: {
        authorityKind: "DEVELOPMENT",
        cleanupRuntimeSnapshot: () => {},
        developmentManifestSha256: "e".repeat(64),
        runtimeIndexPath: "C:\\owned\\runtime-bundle-index.json",
        runtimeIndexSha256: "f".repeat(64),
        checkpointDir: "C:\\owned\\checkpoint",
        developmentManifestPath: "C:\\owned\\development.json",
        mode: "INTERACTIVE",
        modelConfigPath: "C:\\owned\\model-config.json",
        pythonExecutable: "C:\\Python\\python.exe",
        serverPath: "C:\\repo\\tools\\ember-restart-3b\\serve_owned_openai.py",
        tokenizerPath: "C:\\owned\\tokenizer.json",
      },
    };
    const command = buildOwnedServerCommand(development, "cuda");
    expect(command.args).toEqual([
      "-I",
      "-c",
      expect.any(String),
      "C:\\owned\\runtime-bundle-index.json",
      "f".repeat(64),
      "C:\\repo\\tools\\ember-restart-3b\\serve_owned_openai.py",
      "--checkpoint", "C:\\owned\\checkpoint",
      "--tokenizer", "C:\\owned\\tokenizer.json",
      "--config", "C:\\owned\\model-config.json",
      "--development-manifest", "C:\\owned\\development.json",
      "--expected-development-manifest-sha256", "e".repeat(64),
      "--expected-runtime-index-sha256", "f".repeat(64),
      "--host", "127.0.0.1",
      "--port", "8083",
      "--device", "cuda",
      "--parent-pid", String(process.pid),
      "--mode", "INTERACTIVE",
    ]);
    expect(command.args).not.toContain("--run-manifest");
    expect(command.args).not.toContain("--trusted-verifier-registry");
  });

  it("rejects a mutated snapshot file before importing the development server", () => {
    const root = mkdtempSync(join(tmpdir(), "ember-preimport-test-"));
    try {
      const serverPath = join(root, "server.py");
      const payloadPath = join(root, "module.py");
      writeFileSync(serverPath, "raise SystemExit('SERVER_RAN')\n");
      writeFileSync(payloadPath, "exact = True\n");
      const payload = new TextEncoder().encode("exact = True\n");
      const index = {
        files: {
          "module.py": {
            bytes: payload.byteLength,
            sha256: new Bun.CryptoHasher("sha256").update(payload).digest("hex"),
          },
        },
      };
      const indexBytes = new TextEncoder().encode(JSON.stringify(index));
      const indexPath = join(root, "runtime-bundle-index.json");
      writeFileSync(indexPath, indexBytes);
      const development: OwnedModelIdentity = {
        ...identity(),
        seat: "OWNED_DEVELOPMENT",
        claimStatus: "NON_ADMISSIBLE",
        tokensSeen: 2048,
        allocatedParameters: 3_839_161_856,
        activeParameters: 1_020_589_568,
        modelName: "ember-owned-development:" + CHECKPOINT.slice(0, 12),
        launch: {
          authorityKind: "DEVELOPMENT",
          cleanupRuntimeSnapshot: () => {},
          developmentManifestSha256: "e".repeat(64),
          runtimeIndexPath: indexPath,
          runtimeIndexSha256: new Bun.CryptoHasher("sha256").update(indexBytes).digest("hex"),
          checkpointDir: "missing-checkpoint",
          developmentManifestPath: "missing-development.json",
          mode: "INTERACTIVE",
          modelConfigPath: "missing-model-config.json",
          pythonExecutable: process.env.PYTHON ?? "python",
          serverPath,
          tokenizerPath: "missing-tokenizer.json",
        },
      };
      writeFileSync(payloadPath, "mutated = True\n");
      const command = buildOwnedServerCommand(development, "cpu");
      const result = Bun.spawnSync([command.executable, ...command.args]);
      const stderr = new TextDecoder().decode(result.stderr);
      expect(result.exitCode).toBe(1);
      expect(stderr).toContain("runtime bundle file changed before development server import");
      expect(stderr).not.toContain("SERVER_RAN");
    } finally {
      rmSync(root, { force: true, recursive: true });
    }
  });

  it("passes the constructed development argv through the real Python receiver", () => {
    const serverPath = resolve(
      import.meta.dir,
      "../../../ember-restart-3b/serve_owned_openai.py",
    );
    const development: OwnedModelIdentity = {
      ...identity(),
      seat: "OWNED_DEVELOPMENT",
      claimStatus: "NON_ADMISSIBLE",
      tokensSeen: 2048,
      allocatedParameters: 3_839_161_856,
      activeParameters: 1_020_589_568,
      modelName: "ember-owned-development:" + CHECKPOINT.slice(0, 12),
      launch: {
        authorityKind: "DEVELOPMENT",
        cleanupRuntimeSnapshot: () => {},
        developmentManifestSha256: "e".repeat(64),
        runtimeIndexPath: "C:\\owned\\runtime-bundle-index.json",
        runtimeIndexSha256: "f".repeat(64),
        checkpointDir: "missing-checkpoint",
        developmentManifestPath: "missing-development.json",
        mode: "INTERACTIVE",
        modelConfigPath: "missing-model-config.json",
        pythonExecutable: process.env.PYTHON ?? "python",
        serverPath,
        tokenizerPath: "missing-tokenizer.json",
      },
    };

    const command = buildOwnedServerCommand(development, "cpu");
    const receiverOffset = command.args.indexOf(serverPath);
    expect(receiverOffset).toBeGreaterThan(0);
    const result = Bun.spawnSync([command.executable, ...command.args.slice(receiverOffset)]);
    const stderr = new TextDecoder().decode(result.stderr);

    expect(result.exitCode).toBe(1);
    expect(stderr).toContain("development seat resolver rejected the manifest");
    expect(stderr).not.toContain("unrecognized arguments");
  });

  it("rejects every pre-existing listener instead of trusting self-reported identity", async () => {
    let verified = 0;
    let spawned = 0;
    await expect(
      ensureOwnedServer(identity(), {
        probePresence: async () => "present",
        verifyEndpoint: async () => { verified += 1; },
        spawnServer: () => { spawned += 1; throw new Error("must not spawn"); },
      }),
    ).rejects.toThrow("pre-existing listener");
    expect(verified).toBe(0);
    expect(spawned).toBe(0);
  });

  it("spawns the exact server when absent and registers cleanup before readiness", async () => {
    const fakeHandle = { process: { pid: 77, kill: () => true }, port: 8083, kill: () => {} } as never;
    let cleanupRegistrations = 0;
    let waited = 0;
    const result = await ensureOwnedServer(identity(), {
      probePresence: async () => "absent",
      spawnServer: () => fakeHandle,
      registerCleanup: () => {
        cleanupRegistrations += 1;
        return () => {};
      },
      waitUntilReady: async (_identity, handle) => {
        expect(handle).toBe(fakeHandle);
        expect(cleanupRegistrations).toBe(1);
        waited += 1;
      },
    });
    expect(result).toEqual({ outcome: "spawned", port: 8083, handle: fakeHandle });
    expect(waited).toBe(1);
  });

  it("surfaces a real asynchronous spawn error for a missing executable", async () => {
    const missingExecutable = identity();
    if (!missingExecutable.launch) throw new Error("missing launch fixture");
    missingExecutable.launch.pythonExecutable = "C:\\definitely-missing\\python-owned.exe";
    await expect(
      ensureOwnedServer(missingExecutable, {
        probePresence: async () => "absent",
        registerCleanup: () => () => {},
      }),
    ).rejects.toThrow("owned server failed to start");
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

  it("never verifies or spawns over any present endpoint", async () => {
    let verified = 0;
    let spawned = 0;
    expect(
      ensureOwnedServer(identity(), {
        probePresence: async () => "present",
        verifyEndpoint: async () => { verified += 1; },
        spawnServer: () => { spawned += 1; throw new Error("must not spawn"); },
      }),
    ).rejects.toThrow("pre-existing listener");
    expect(verified).toBe(0);
    expect(spawned).toBe(0);
  });

  it("fails closed when an absent endpoint lacks a launch descriptor", async () => {
    const withoutLaunch = { ...identity(), launch: undefined };
    expect(
      ensureOwnedServer(withoutLaunch, { probePresence: async () => "absent" }),
    ).rejects.toThrow("launch descriptor");
  });
});
