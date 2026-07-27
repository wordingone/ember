// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { createServer } from "node:net";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { callEmberLab } from "../services/ember-lab-rpc.ts";

import type { OwnedModelIdentity } from "./model-seat.ts";
import {
  buildOwnedServerCommand,
  dispatchManifestParams,
  ensureOwnedServer,
  probeOwnedEndpointPresence,
  validateOwnedDispatchManifest,
  verifyDispatchReceiptCustody,
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
      trustedVerifierRegistrySha256: "d".repeat(64),
      trustedVerifierRegistryApprovalPath: "C:\\owned\\trusted-registry-approval.json",
      trustedVerifierRegistryApprovalSha256: "e".repeat(64),
    },
  };
}

const realDaemonPipe = process.env["EMBER_LAB_REAL_DAEMON_PIPE"];
const realDaemonManifest = process.env["EMBER_LAB_REAL_DAEMON_MANIFEST"];

describe.skipIf(!(realDaemonPipe && realDaemonManifest))("owned server supervisor real ember-lab bridge", () => {
  it("uses the production manifest_utf8 request type against the real Rust daemon", async () => {
    const manifestBytes = readFileSync(realDaemonManifest!);
    const result = await callEmberLab({
      pipeName: realDaemonPipe!,
      method: "dispatch_manifest",
      params: dispatchManifestParams(manifestBytes),
      timeoutMs: 5_000,
    });
    expect(result["pid"]).toSatisfy((value) => typeof value === "number" && value > 0);
  });
});
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
      "--expected-registry-root-sha256", "d".repeat(64),
      "--trusted-verifier-registry-approval", "C:\\owned\\trusted-registry-approval.json",
      "--expected-registry-approval-sha256", "e".repeat(64),
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
    expect(command.args[2]).toContain("site.getusersitepackages()");
    expect(command.args[2]).toContain("sys.path.append(str(user_site))");
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

  it("routes an absent connected owned endpoint through daemon dispatch without CLI spawning", async () => {
    const priorPipe = process.env["EMBER_LAB_PIPE"];
    process.env["EMBER_LAB_PIPE"] = "\\\\.\\pipe\\ember-lab-p2d-test";
    try {
      let spawned = 0;
      let dispatched = 0;
      const result = await ensureOwnedServer(identity(), {
        probePresence: async () => "absent",
        dispatchManifest: async () => {
          dispatched += 1;
          return { pid: 77, preflightReceiptPath: "C:\\owned\\custody\\preflight.json", preflightReceiptSha256: "f".repeat(64) };
        },
        spawnServer: () => {
          spawned += 1;
          throw new Error("CLI-owned spawn is forbidden for connected owned seats");
        },
        waitForDispatchReady: async () => {},
      });
      expect(result).toMatchObject({ outcome: "dispatched", port: 8083, pid: 77 });
      expect(dispatched).toBe(1);
      expect(spawned).toBe(0);
    } finally {
      if (priorPipe === undefined) delete process.env["EMBER_LAB_PIPE"];
      else process.env["EMBER_LAB_PIPE"] = priorPipe;
    }
  });
  it("rejects receipts outside daemon custody and rehashes their exact bytes", () => {
    const root = mkdtempSync(join(tmpdir(), "ember-p2d-receipt-custody-"));
    const outside = mkdtempSync(join(tmpdir(), "ember-p2d-receipt-outside-"));
    try {
      const receiptPath = join(root, "preflight.json");
      writeFileSync(receiptPath, "original-receipt");
      const digest = new Bun.CryptoHasher("sha256").update("original-receipt").digest("hex");
      expect(verifyDispatchReceiptCustody(receiptPath, digest, root)).toEqual({ path: resolve(receiptPath), sha256: digest });
      writeFileSync(receiptPath, "mutated-receipt");
      expect(() => verifyDispatchReceiptCustody(receiptPath, digest, root)).toThrow("hash does not match custody bytes");
      const outsideReceipt = join(outside, "preflight.json");
      writeFileSync(outsideReceipt, "outside-receipt");
      const outsideDigest = new Bun.CryptoHasher("sha256").update("outside-receipt").digest("hex");
      expect(() => verifyDispatchReceiptCustody(outsideReceipt, outsideDigest, root)).toThrow("escapes authorized custody");
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(outside, { recursive: true, force: true });
    }
  });

  it("sends exact bound manifest bytes to ember-lab without CLI custody writes", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-p2d-dispatch-bound-"));
    const sourcePath = join(root, "source-dispatch.json");
    const pipe = `\\\\.\\pipe\\ember-lab-p2d-dispatch-${process.pid}-${Math.random().toString(16).slice(2)}`;
    const priorPipe = process.env["EMBER_LAB_PIPE"];
    const priorManifest = process.env["EMBER_LAB_DISPATCH_MANIFEST"];
    const priorCommit = (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
    const owned = identity();
    const launch = owned.launch;
    if (!launch) throw new Error("missing launch");
    const command = buildOwnedServerCommand(owned, "cuda");
    const payload = {
      schema_version: "ember-lab-dispatch-manifest-v2",
      job_id: "owned-interactive",
      source_commit: "e".repeat(40),
      not_before_ms: 1,
      expires_at_ms: 2,
      resource_lease: "owned-interactive",
      program: { path: command.executable, sha256: "f".repeat(64) },
      args: command.args,
      env: {},
      bindings: [
        { kind: "config", path: launch.modelConfigPath, sha256: owned.modelConfigSha256 },
        { kind: "manifest", path: launch.tokenizerPath, sha256: owned.tokenizerSha256 },
        { kind: "manifest", path: launch.serverPath, sha256: owned.serverSourceSha256 },
        { kind: "manifest", path: join(launch.checkpointDir, "checkpoint-manifest.json"), sha256: owned.checkpointSha256 },
      ],
      custody_root: root,
      storage_reserves: [{ root, minimum_free_bytes: 1 }],
      minimum_free_vram_bytes: 1,
      required_available_maximum_commit_bytes: 2,
      maximum_job_memory_bytes: 1,
      simulated_peak_commit_bytes: 1,
      preflight_receipt: join(root, "preflight.json"),
    };
    const manifestBytes = Buffer.from(JSON.stringify(payload));
    writeFileSync(sourcePath, manifestBytes);
    const receiptBytes = Buffer.from("daemon-preflight-receipt");
    const receiptPath = join(root, "preflight.json");
    writeFileSync(receiptPath, receiptBytes);
    let receivedManifest: unknown;
    const server = createServer((socket) => {
      socket.once("data", (buffer) => {
        const request = JSON.parse(buffer.toString("utf8")) as { id: string; params: { manifest_utf8: string; manifest_sha256: string } };
        receivedManifest = request.params;
        writeFileSync(sourcePath, "{\"mutated\":true}");
        socket.end(JSON.stringify({
          jsonrpc: "2.0", id: request.id,
          result: { pid: 77, preflight_receipt_path: receiptPath, preflight_receipt_sha256: new Bun.CryptoHasher("sha256").update(receiptBytes).digest("hex") },
        }) + "\n");
      });
    });
    await new Promise<void>((resolvePromise, reject) => {
      const onError = (error: Error): void => {
        server.removeListener("listening", onListening);
        reject(error);
      };
      const onListening = (): void => {
        server.removeListener("error", onError);
        resolvePromise();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen({ path: pipe });
    });
    process.env["EMBER_LAB_PIPE"] = pipe;
    process.env["EMBER_LAB_DISPATCH_MANIFEST"] = sourcePath;
    (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__ = "e".repeat(40);
    try {
      const result = await ensureOwnedServer(owned, {
        probePresence: async () => "absent",
        spawnServer: () => { throw new Error("connected mode must never direct-spawn"); },
        waitForDispatchReady: async () => {},
      });
      expect(result).toMatchObject({ outcome: "dispatched", pid: 77 });
      expect(receivedManifest).toEqual({
        manifest_utf8: manifestBytes.toString("utf8"),
        manifest_sha256: new Bun.CryptoHasher("sha256").update(manifestBytes).digest("hex"),
      });
      expect(readFileSync(sourcePath, "utf8")).toBe("{\"mutated\":true}");
      expect(existsSync(join(root, ".ember-lab-dispatch-manifests"))).toBeFalse();
    } finally {
      await new Promise<void>((resolvePromise) => server.close(() => resolvePromise()));
      if (priorPipe === undefined) delete process.env["EMBER_LAB_PIPE"];
      else process.env["EMBER_LAB_PIPE"] = priorPipe;
      if (priorManifest === undefined) delete process.env["EMBER_LAB_DISPATCH_MANIFEST"];
      else process.env["EMBER_LAB_DISPATCH_MANIFEST"] = priorManifest;
      if (priorCommit === undefined) delete (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
      else (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__ = priorCommit;
      rmSync(root, { recursive: true, force: true });
    }
  });
  it("rejects a daemon dispatch result without its preflight receipt custody", async () => {
    const priorPipe = process.env["EMBER_LAB_PIPE"];
    process.env["EMBER_LAB_PIPE"] = "\\\\.\\pipe\\ember-lab-p2d-missing-receipt";
    try {
      await expect(ensureOwnedServer(identity(), {
        probePresence: async () => "absent",
        dispatchManifest: async () => ({ pid: 77 }),
        waitForDispatchReady: async () => {},
      })).rejects.toThrow("preflight receipt custody");
    } finally {
      if (priorPipe === undefined) delete process.env["EMBER_LAB_PIPE"];
      else process.env["EMBER_LAB_PIPE"] = priorPipe;
    }
  });
  it("refuses a connected owned endpoint without a dispatch manifest before direct spawn", async () => {
    const priorPipe = process.env["EMBER_LAB_PIPE"];
    const priorManifest = process.env["EMBER_LAB_DISPATCH_MANIFEST"];
    process.env["EMBER_LAB_PIPE"] = "\\\\.\\pipe\\ember-lab-p2d-missing-manifest";
    delete process.env["EMBER_LAB_DISPATCH_MANIFEST"];
    let spawned = 0;
    try {
      await expect(ensureOwnedServer(identity(), {
        probePresence: async () => "absent",
        spawnServer: () => { spawned += 1; throw new Error("must not spawn"); },
      })).rejects.toThrow("EMBER_LAB_DISPATCH_MANIFEST");
      expect(spawned).toBe(0);
    } finally {
      if (priorPipe === undefined) delete process.env["EMBER_LAB_PIPE"];
      else process.env["EMBER_LAB_PIPE"] = priorPipe;
      if (priorManifest === undefined) delete process.env["EMBER_LAB_DISPATCH_MANIFEST"];
      else process.env["EMBER_LAB_DISPATCH_MANIFEST"] = priorManifest;
    }
  });
  it("rejects invalid UTF-8 dispatch manifest bytes before opening a daemon pipe", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-p2d-invalid-utf8-"));
    const manifest = join(root, "dispatch.json");
    const previousPipe = process.env["EMBER_LAB_PIPE"];
    const previousManifest = process.env["EMBER_LAB_DISPATCH_MANIFEST"];
    const previousCommit = (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
    writeFileSync(manifest, Buffer.from([0xff]));
    process.env["EMBER_LAB_PIPE"] = "\\\\.\\pipe\\ember-lab-p2d-invalid-utf8";
    process.env["EMBER_LAB_DISPATCH_MANIFEST"] = manifest;
    (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__ = "e".repeat(40);
    let spawned = 0;
    try {
      await expect(ensureOwnedServer(identity(), {
        probePresence: async () => "absent",
        spawnServer: () => { spawned += 1; throw new Error("must not direct-spawn"); },
      })).rejects.toThrow("cannot read dispatch manifest");
      expect(spawned).toBe(0);
    } finally {
      if (previousPipe === undefined) delete process.env["EMBER_LAB_PIPE"];
      else process.env["EMBER_LAB_PIPE"] = previousPipe;
      if (previousManifest === undefined) delete process.env["EMBER_LAB_DISPATCH_MANIFEST"];
      else process.env["EMBER_LAB_DISPATCH_MANIFEST"] = previousManifest;
      if (previousCommit === undefined) delete (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
      else (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__ = previousCommit;
      rmSync(root, { recursive: true, force: true });
    }
  });  it("rejects a dispatch manifest whose server binding differs from the selected owned identity", () => {
    const owned = identity();
    const command = buildOwnedServerCommand(owned, "cuda");
    const launch = owned.launch;
    if (!launch) throw new Error("missing launch");
    const manifest = {
      schema_version: "ember-lab-dispatch-manifest-v2",
      job_id: "owned-interactive",
      source_commit: "e".repeat(40),
      not_before_ms: 1,
      expires_at_ms: 2,
      resource_lease: "owned-interactive",
      program: { path: command.executable, sha256: "f".repeat(64) },
      args: command.args,
      env: {},
      bindings: [
        { kind: "config", path: launch.modelConfigPath, sha256: owned.modelConfigSha256 },
        { kind: "manifest", path: launch.tokenizerPath, sha256: owned.tokenizerSha256 },
        { kind: "manifest", path: launch.serverPath, sha256: "0".repeat(64) },
        { kind: "manifest", path: join(launch.checkpointDir, "checkpoint-manifest.json"), sha256: owned.checkpointSha256 },
      ],
      custody_root: "C:\\owned\\custody",
      storage_reserves: [{ root: "C:\\owned", minimum_free_bytes: 1 }],
      minimum_free_vram_bytes: 1,
      required_available_maximum_commit_bytes: 2,
      maximum_job_memory_bytes: 1,
      simulated_peak_commit_bytes: 1,
      preflight_receipt: "C:\\owned\\custody\\preflight.json",
    };
    expect(() => validateOwnedDispatchManifest(owned, manifest, "e".repeat(40)))
      .toThrow("server source binding");
    manifest.bindings[2] = { kind: "manifest", path: launch.serverPath, sha256: owned.serverSourceSha256 };
    manifest.bindings[0] = { kind: "manifest", path: launch.modelConfigPath, sha256: owned.modelConfigSha256 };
    expect(() => validateOwnedDispatchManifest(owned, manifest, "e".repeat(40)))
      .toThrow("model config binding");
    manifest.bindings[0] = { kind: "config", path: launch.modelConfigPath, sha256: owned.modelConfigSha256 };
    manifest.bindings.push({ kind: "config", path: launch.modelConfigPath, sha256: owned.modelConfigSha256 });
    expect(() => validateOwnedDispatchManifest(owned, manifest, "e".repeat(40)))
      .toThrow("model config binding path is not unique");
    manifest.bindings.pop();
    Object.assign(manifest, { unexpected: true });
    expect(() => validateOwnedDispatchManifest(owned, manifest, "e".repeat(40)))
      .toThrow("fields are not closed");
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
