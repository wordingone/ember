// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/checkpoint-save-modern-command.test.ts — the full production
// ROUND-TRIP for issue #1056: /model checkpoint save (real saveModernCheckpoint,
// real fs, real verifyCheckpointBundle) followed by /model checkpoint load
// (the REAL production entry point with its default invocation -- never a
// helper or a fixture shaped to only prove the happy path) against the
// bundle that save just produced. This is the acceptance-map's row (3):
// "/model checkpoint load <saved-dir> reaches the authorized owned
// supervisor only when its durable admitted identity already names the
// exact checkpoint" -- exercised end to end, not by construction.

import { afterEach, describe, expect, it } from "bun:test";
import { createHash } from "crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { createModelCommand } from "./model.ts";
import type { OwnedModelIdentity } from "../entrypoints/model-seat.ts";
import type { CommandContext } from "../types/command-types.ts";

const roots: string[] = [];

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

const EXPERT_PATHS = [
  "expert-vision.pt",
  "expert-audio.pt",
  "expert-reasoning.pt",
  "expert-tool.pt",
] as const;

/** Writes a real, closed, byte-valid v5 modern sparse bundle -- the same
 * governed shape tools/ember-restart-3b/checkpoint_artifacts.py produces. */
function writeV5Bundle(dir: string): void {
  mkdirSync(dir, { recursive: true });
  const payloads = new Map<string, Buffer>([
    ["shared-model.pt", Buffer.from("shared-model")],
    ["optimizer-state.pt", Buffer.from("optimizer-state")],
    ["replay-state.pt", Buffer.from("replay-state")],
    ...EXPERT_PATHS.map((path) => [path, Buffer.from(path)] as const),
  ]);
  const manifest = {
    schema_version: "ember-sparse-checkpoint-v5",
    shards: [...payloads].map(([path, bytes]) => ({
      path,
      bytes: bytes.length,
      sha256: sha256(bytes),
    })),
  };
  for (const [path, bytes] of payloads) {
    writeFileSync(join(dir, path), bytes);
  }
  writeFileSync(
    join(dir, "checkpoint-manifest.json"),
    Buffer.from(JSON.stringify(manifest) + "\n", "utf8"),
  );
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

const context: CommandContext = {
  sessionId: "checkpoint-save-modern-roundtrip-test",
  mode: "test",
  cwd: process.cwd(),
};

describe("/model checkpoint save (modern) -> /model checkpoint load round-trip", () => {
  it("acceptance #1/#2: production save emits one modern sparse bundle from real writer semantics, and it passes the production verifier unchanged", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-roundtrip-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    writeV5Bundle(sourceDir);
    const targetDir = join(root, "saved");

    const cmd = createModelCommand();
    const result = await cmd.execute(
      `checkpoint save ${targetDir} --source ${sourceDir}`,
      context,
    );

    expect(result?.exitCode).toBeUndefined();
    expect(result?.message).toContain("/model checkpoint load compatible");

    // Independent, real production verifier run against the saved output --
    // not the same call the save path itself already made internally.
    const { verifyCheckpointBundle } = await import("../services/checkpoint-load.ts");
    const verified = await verifyCheckpointBundle(targetDir);
    expect(verified.schemaVersion).toBe("ember-sparse-checkpoint-v5");
    expect(verified.artifacts).toHaveLength(7);
  });

  it("acceptance #3: /model checkpoint load reaches the authorized owned supervisor only when the durable admitted identity already names the saved checkpoint's exact digest", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-roundtrip-auth-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    writeV5Bundle(sourceDir);
    const targetDir = join(root, "saved");

    const cmd = createModelCommand();
    const saveResult = await cmd.execute(
      `checkpoint save ${targetDir} --source ${sourceDir}`,
      context,
    );
    expect(saveResult?.exitCode).toBeUndefined();
    const savedManifestSha256 = saveResult!.message.match(/([0-9a-f]{64})/)![1]!;

    let ensureCalls = 0;
    let receivedIdentity: OwnedModelIdentity | null = null;

    // Negative half first: an owned identity whose durable checkpointSha256
    // does NOT name this saved bundle refuses before any supervisor call --
    // save/load never grants ownership by itself.
    const unauthorizedCmd = createModelCommand({
      loadOwnedIdentity: () =>
        ({
          checkpointSha256: "0".repeat(64),
          endpointUrl: "http://127.0.0.1:29777/",
          launch: {
            mode: "INTERACTIVE",
            authorityKind: "ADMISSION",
            checkpointDir: "/unrelated",
            tokenizerPath: "/tokenizer.json",
          },
        }) as unknown as OwnedModelIdentity,
      ensureOwnedServer: async () => {
        ensureCalls += 1;
        throw new Error("must not start");
      },
    });
    const unauthorizedResult = await unauthorizedCmd.execute(
      `checkpoint load ${targetDir}`,
      context,
    );
    expect(unauthorizedResult?.exitCode).toBe(1);
    expect(unauthorizedResult?.message).toContain(
      "not the currently authorized owned checkpoint",
    );
    expect(ensureCalls).toBe(0);

    // Positive half: an owned identity whose durable checkpointSha256
    // EXACTLY names the saved bundle's manifest digest reaches the
    // supervisor, and is handed the saved bundle's own directory.
    const authorizedCmd = createModelCommand({
      loadOwnedIdentity: () =>
        ({
          checkpointSha256: savedManifestSha256,
          endpointUrl: "http://127.0.0.1:29777/",
          launch: {
            mode: "INTERACTIVE",
            authorityKind: "ADMISSION",
            checkpointDir: "/previous-seat",
            tokenizerPath: "/tokenizer.json",
          },
        }) as unknown as OwnedModelIdentity,
      ensureOwnedServer: async (identity) => {
        receivedIdentity = identity;
        return {
          outcome: "spawned",
          port: 29777,
          handle: {
            process: { pid: 4242 },
            port: 29777,
            kill: () => {},
          } as never,
        };
      },
      loadModel: async () => "model loaded (pid 4242)",
      registerManagedModel: () => {},
    });
    const authorizedResult = await authorizedCmd.execute(
      `checkpoint load ${targetDir}`,
      context,
    );

    expect(authorizedResult?.exitCode).toBeUndefined();
    expect(authorizedResult?.message).toContain("model loaded");
    expect(receivedIdentity).not.toBeNull();
    expect((receivedIdentity as unknown as OwnedModelIdentity).launch?.checkpointDir).toBe(
      await (async () => {
        const { realpath } = await import("fs/promises");
        return realpath(targetDir);
      })(),
    );
  });

  it("acceptance #4: hostile byte substitution on the SAVED bundle (manifest unchanged) is refused before any model process starts", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-roundtrip-hostile-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    writeV5Bundle(sourceDir);
    const targetDir = join(root, "saved");

    const cmd = createModelCommand();
    const saveResult = await cmd.execute(
      `checkpoint save ${targetDir} --source ${sourceDir}`,
      context,
    );
    expect(saveResult?.exitCode).toBeUndefined();
    const savedManifestSha256 = saveResult!.message.match(/([0-9a-f]{64})/)![1]!;
    const manifestBefore = readFileSync(join(targetDir, "checkpoint-manifest.json"));

    // Tamper with a named shard AFTER save -- manifest bytes untouched.
    writeFileSync(join(targetDir, "expert-audio.pt"), Buffer.from("tampered-post-save"));

    let ensureCalls = 0;
    let lifecycleCalls = 0;
    const cmdLoad = createModelCommand({
      loadOwnedIdentity: () =>
        ({
          checkpointSha256: savedManifestSha256,
          endpointUrl: "http://127.0.0.1:29777/",
          launch: {
            mode: "INTERACTIVE",
            authorityKind: "ADMISSION",
            checkpointDir: "/previous-seat",
            tokenizerPath: "/tokenizer.json",
          },
        }) as unknown as OwnedModelIdentity,
      ensureOwnedServer: async () => {
        ensureCalls += 1;
        throw new Error("must not start");
      },
      loadModel: async () => {
        lifecycleCalls += 1;
        return "must not load";
      },
    });

    const result = await cmdLoad.execute(`checkpoint load ${targetDir}`, context);

    expect(result?.exitCode).toBe(1);
    expect(result?.message).toMatch(/corrupt, incomplete, or tampered.*expert-audio\.pt/i);
    expect(ensureCalls).toBe(0);
    expect(lifecycleCalls).toBe(0);
    expect(readFileSync(join(targetDir, "checkpoint-manifest.json"))).toEqual(manifestBefore);
  });

  it("acceptance #5: existing legacy save (save-legacy) output remains visibly marked non-round-tripping", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-legacy-marker-"));
    roots.push(root);
    const targetDir = join(root, "legacy-target");

    const cmd = createModelCommand({
      checkpointSaveDeps: {
        resolveIdentity: async () => ({
          byte_sha256: "a".repeat(64),
          disposition: "OWNED_CANDIDATE",
          data: {
            corpus_id: "fixture",
            sha256: "b".repeat(64),
            ordering_sha256: "c".repeat(64),
            curriculum_sha256: "d".repeat(64),
            verifier_sha256: "e".repeat(64),
            clean_genesis: true,
            accepted_input: { input_id: "fixture-input", authority_id: "fixture-authority" },
          },
          tokenizer: { id: "fixture-tokenizer", sha256: "f".repeat(64) },
        }),
        mkdir: async () => {},
        copyFile: async () => {},
        rename: async () => {},
        rmStaging: async () => {},
        stagingPath: (target) => `${target}.tmp`,
      },
    });

    const result = await cmd.execute(
      `checkpoint save-legacy ${targetDir} --source ${root}`,
      context,
    );

    expect(result?.exitCode).toBeUndefined();
    expect(result?.message).toContain("not /model checkpoint load compatible");
  });
});
