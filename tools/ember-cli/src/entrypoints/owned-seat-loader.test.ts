// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { resolve } from "path";

import {
  loadOwnedModelIdentity,
  verifyOwnedEndpointIdentity,
} from "./owned-seat-loader.ts";

const CHECKPOINT = "d".repeat(64);

describe("owned seat loader", () => {
  it("returns unavailable when the default pointer does not exist", () => {
    let executed = false;
    const identity = loadOwnedModelIdentity(
      { repoRoot: "C:/repo", configHome: "C:/home" },
      {
        exists: () => false,
        execute: () => {
          executed = true;
          return { status: 0, stdout: "{}", stderr: "" };
        },
      },
    );
    expect(identity).toBeUndefined();
    expect(executed).toBe(false);
  });

  it("fails closed when an explicitly selected manifest is missing", () => {
    expect(() =>
      loadOwnedModelIdentity(
        {
          repoRoot: "C:/repo",
          configHome: "C:/home",
          manifestPath: "C:/missing.json",
        },
        { exists: () => false },
      ),
    ).toThrow("owned rung manifest does not exist");
  });

  it("executes the central resolver and derives the admitted identity", () => {
    let observedArgs: string[] = [];
    const identity = loadOwnedModelIdentity(
      {
        repoRoot: "C:/repo",
        configHome: "C:/home",
        manifestPath: resolve("C:/run.json"),
        verifierRegistryPath: resolve("C:/trusted.json"),
        pythonExecutable: "python-owned",
      },
      {
        exists: () => true,
        execute: (executable, args) => {
          observedArgs = [executable, ...args];
          return {
            status: 0,
            stderr: "",
            stdout: JSON.stringify({
              valid: true,
              seat: "OWNED_ADMITTED",
              checkpoint_sha256: CHECKPOINT,
              endpoint_url: "http://127.0.0.1:8083",
              identity_url: "http://127.0.0.1:8083/v1/models",
              model_config_sha256: "b".repeat(64),
              model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
              model_format: "safetensors",
              server_source_sha256: "a".repeat(64),
              tokenizer_sha256: "c".repeat(64),
              launch: {
                checkpoint_dir: resolve("C:/owned/checkpoint"),
                mode: "INTERACTIVE",
                run_manifest_path: resolve("C:/run.json"),
                server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
                tokenizer_path: resolve("C:/owned/tokenizer.json"),
                trusted_verifier_registry_path: resolve("C:/trusted.json"),
              },
            }),
          };
        },
      },
    );

    expect(identity).toEqual({
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      modelFormat: "safetensors",
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
      launch: {
        checkpointDir: resolve("C:/owned/checkpoint"),
        mode: "INTERACTIVE",
        pythonExecutable: "python-owned",
        runManifestPath: resolve("C:/run.json"),
        serverPath: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
        tokenizerPath: resolve("C:/owned/tokenizer.json"),
        trustedVerifierRegistryPath: resolve("C:/trusted.json"),
      },
    });
    expect(observedArgs).toEqual([
      "python-owned",
      "C:\\repo\\scripts\\ember_restart\\cli_seat.py",
      "C:\\run.json",
      "--trusted-verifier-registry",
      "C:\\trusted.json",
    ]);
  });

  it("surfaces admission errors and rejects malformed successful output", () => {
    const common = {
      repoRoot: "C:/repo",
      configHome: "C:/home",
      manifestPath: resolve("C:/run.json"),
      verifierRegistryPath: resolve("C:/trusted.json"),
    };
    expect(() =>
      loadOwnedModelIdentity(common, {
        exists: () => true,
        execute: () => ({
          status: 1,
          stdout: JSON.stringify({ errors: ["stage is not OWNED_ADMITTED"] }),
          stderr: "",
        }),
      }),
    ).toThrow("stage is not OWNED_ADMITTED");

    expect(() =>
      loadOwnedModelIdentity(common, {
        exists: () => true,
        execute: () => ({
          status: 0,
          stdout: JSON.stringify({
            valid: true,
            seat: "OWNED_ADMITTED",
            checkpoint_sha256: CHECKPOINT,
            endpoint_url: "http://127.0.0.1:8083",
            identity_url: "http://127.0.0.1:8083/v1/models",
            model_name: "qwen3.6-27b",
          }),
          stderr: "",
        }),
      }),
    ).toThrow("invalid admitted identity");

    expect(() =>
      loadOwnedModelIdentity(common, {
        exists: () => true,
        execute: () => ({
          status: 0,
          stdout: JSON.stringify({
            valid: true,
            seat: "OWNED_ADMITTED",
            checkpoint_sha256: CHECKPOINT,
            endpoint_url: "",
            identity_url: "/v1/models",
            model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
          }),
          stderr: "",
        }),
      }),
    ).toThrow("invalid admitted identity");
  });

  it("accepts only a live endpoint bound to the admitted checkpoint", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    let requested = "";
    await verifyOwnedEndpointIdentity(identity, async (input) => {
      requested = String(input);
      return Response.json({
        seat: "OWNED_ADMITTED",
        mode: "INTERACTIVE",
        checkpoint_sha256: CHECKPOINT,
        model_name: identity.modelName,
        model_config_sha256: identity.modelConfigSha256,
        server_source_sha256: identity.serverSourceSha256,
        tokenizer_sha256: identity.tokenizerSha256,
      });
    });
    expect(requested).toBe(identity.identityUrl);
  });

  it("rejects a frozen-eval endpoint when the CLI requested interactive mode", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    await expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({
          seat: "OWNED_ADMITTED",
          mode: "FROZEN_EVAL",
          checkpoint_sha256: CHECKPOINT,
          model_name: identity.modelName,
          model_config_sha256: identity.modelConfigSha256,
          server_source_sha256: identity.serverSourceSha256,
          tokenizer_sha256: identity.tokenizerSha256,
        }),
      ),
    ).rejects.toThrow("does not match admitted checkpoint");
  });
  it("rejects a live endpoint that reports another checkpoint or identity", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({
          seat: "OWNED_ADMITTED",
          checkpoint_sha256: "f".repeat(64),
          model_name: identity.modelName,
        }),
      ),
    ).rejects.toThrow("does not match admitted checkpoint");
    expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        new Response("unavailable", { status: 503 }),
      ),
    ).rejects.toThrow("identity request failed with HTTP 503");
  });

  it("rejects a live endpoint whose runtime bytes differ from the admitted identity", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    await expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({
          seat: "OWNED_ADMITTED",
          checkpoint_sha256: CHECKPOINT,
          model_name: identity.modelName,
          model_config_sha256: identity.modelConfigSha256,
          tokenizer_sha256: identity.tokenizerSha256,
          server_source_sha256: "f".repeat(64),
        }),
      ),
    ).rejects.toThrow("does not match admitted checkpoint");
  });
});
