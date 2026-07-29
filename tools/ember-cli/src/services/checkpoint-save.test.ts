// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/checkpoint-save.test.ts — unit tests for the /model checkpoint save
// CORE (validate -> atomic copy -> return sha), kept separate from the
// "which path is currently loaded" seat wiring in commands/model.ts. No
// admissible real model checkpoint exists yet, so these exercise the core
// against a synthetic fixture with an injected `resolveIdentity` -- the same
// injection seam commands/model.test.ts already uses for `resolveModelIdentity`.

import { describe, it, expect } from "bun:test";
import { createHash } from "crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { copyFile, mkdir, rename, rm } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";
import {
  saveCheckpoint,
  saveCheckpointBundle,
  type CheckpointSaveDeps,
  type ModernCheckpointSaveDeps,
} from "./checkpoint-save.ts";
import { verifyCheckpointBundle } from "./checkpoint-load.ts";
import type { ResolvedModelIdentity } from "../commands/model.ts";

const VALID_IDENTITY: ResolvedModelIdentity = {
  byte_sha256: "a".repeat(64),
  disposition: "OWNED_CANDIDATE",
  data: {
    corpus_id: "fixture-corpus",
    sha256: "b".repeat(64),
    ordering_sha256: "c".repeat(64),
    curriculum_sha256: "d".repeat(64),
    verifier_sha256: "e".repeat(64),
    clean_genesis: true,
    accepted_input: { input_id: "fixture-input", authority_id: "fixture-authority" },
  },
  tokenizer: { id: "fixture-tokenizer", sha256: "f".repeat(64) },
};

/** Real fs-backed deps (no mocked I/O) with an injected identity resolver --
 * mirrors production `_realCheckpointSaveDeps` in commands/model.ts. */
function realFsDeps(resolveIdentity: CheckpointSaveDeps["resolveIdentity"]): CheckpointSaveDeps {
  return {
    resolveIdentity,
    mkdir: async (path) => { await mkdir(path, { recursive: true }); },
    copyFile: (src, dest) => copyFile(src, dest),
    rename: (from, to) => rename(from, to),
    rmStaging: (path) => rm(path, { recursive: true, force: true }),
    stagingPath: (targetDir) => `${targetDir}.tmp-test`,
  };
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function writeSparseBundle(root: string): string {
  mkdirSync(root);
  const payloads = new Map<string, Buffer>([
    ["shared-model.pt", Buffer.from("shared-model")],
    ["optimizer-state.pt", Buffer.from("optimizer-state")],
    ["replay-state.pt", Buffer.from("replay-state")],
    ["expert-vision.pt", Buffer.from("vision")],
    ["expert-audio.pt", Buffer.from("audio")],
    ["expert-reasoning.pt", Buffer.from("reasoning")],
    ["expert-tool.pt", Buffer.from("tool")],
  ]);
  const shards = [...payloads].map(([path, bytes]) => ({
    path,
    bytes: bytes.length,
    sha256: sha256(bytes),
  }));
  for (const [path, bytes] of payloads) {
    writeFileSync(join(root, path), bytes);
  }
  const manifestBytes = Buffer.from(
    `${JSON.stringify({ schema_version: "ember-sparse-checkpoint-v5", shards })}\n`,
    "utf8",
  );
  writeFileSync(join(root, "checkpoint-manifest.json"), manifestBytes);
  return sha256(manifestBytes);
}

function realModernDeps(
  overrides: Partial<ModernCheckpointSaveDeps> = {},
): ModernCheckpointSaveDeps {
  return {
    verifyBundle: verifyCheckpointBundle,
    assertSafeDestination: async () => {},
    mkdirStaging: (path) => mkdir(path),
    copyFile: (src, dest) => copyFile(src, dest),
    publishNoReplace: (from, to) => rename(from, to),
    rmStaging: (path) => rm(path, { recursive: true, force: true }),
    stagingPath: (targetDir) => `${targetDir}.tmp-modern-test`,
    ...overrides,
  };
}

describe("saveCheckpointBundle (modern governed sparse bundle)", () => {
  it("round-trips a v5 bundle through the unchanged production verifier and writes the manifest last", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-positive-"));
    try {
      const source = join(root, "source");
      const expectedManifestSha256 = writeSparseBundle(source);
      const target = join(root, "target");
      const copied: string[] = [];
      const deps = realModernDeps({
        copyFile: async (src, dest) => {
          copied.push(src.split(/[\\/]/).at(-1) ?? "");
          await copyFile(src, dest);
        },
      });

      const result = await saveCheckpointBundle(
        source,
        target,
        expectedManifestSha256,
        deps,
      );
      const verified = await verifyCheckpointBundle(target);

      expect(result.manifestSha256).toBe(expectedManifestSha256);
      expect(result.schemaVersion).toBe("ember-sparse-checkpoint-v5");
      expect(result.artifactCount).toBe(7);
      expect(verified.manifestSha256).toBe(expectedManifestSha256);
      expect(copied.at(-1)).toBe("checkpoint-manifest.json");
      expect(existsSync(`${target}.tmp-modern-test`)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("refuses a structurally valid but non-selected checkpoint before writing", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-pin-"));
    try {
      const source = join(root, "source");
      writeSparseBundle(source);
      const target = join(root, "target");
      let mkdirCalled = false;
      const deps = realModernDeps({
        mkdirStaging: async () => {
          mkdirCalled = true;
        },
      });

      await expect(
        saveCheckpointBundle(source, target, "f".repeat(64), deps),
      ).rejects.toThrow(/selected checkpoint digest/i);
      expect(mkdirCalled).toBe(false);
      expect(existsSync(target)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("refuses hostile shard substitution under an unchanged manifest before publication", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-tamper-"));
    try {
      const source = join(root, "source");
      const expectedManifestSha256 = writeSparseBundle(source);
      const target = join(root, "target");
      let copyCalls = 0;
      let publishCalled = false;
      const deps = realModernDeps({
        copyFile: async (src, dest) => {
          copyCalls++;
          await copyFile(src, dest);
          if (copyCalls === 1) {
            writeFileSync(join(source, "expert-tool.pt"), "hostile-substitution");
          }
        },
        publishNoReplace: async () => {
          publishCalled = true;
        },
      });

      await expect(
        saveCheckpointBundle(source, target, expectedManifestSha256, deps),
      ).rejects.toThrow(/tampered|sha-256|changed|match/i);
      expect(publishCalled).toBe(false);
      expect(existsSync(target)).toBe(false);
      expect(existsSync(`${target}.tmp-modern-test`)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("refuses extra bundle entries through the unchanged verifier before any write", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-extra-"));
    try {
      const source = join(root, "source");
      const expectedManifestSha256 = writeSparseBundle(source);
      writeFileSync(join(source, "unlisted.pt"), "not in manifest");
      let mkdirCalled = false;

      await expect(
        saveCheckpointBundle(
          source,
          join(root, "target"),
          expectedManifestSha256,
          realModernDeps({
            mkdirStaging: async () => {
              mkdirCalled = true;
            },
          }),
        ),
      ).rejects.toThrow(/unexpected checkpoint bundle entry/i);
      expect(mkdirCalled).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("preserves a colliding destination and removes staged bytes", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-collision-"));
    try {
      const source = join(root, "source");
      const expectedManifestSha256 = writeSparseBundle(source);
      const target = join(root, "target");
      mkdirSync(target);
      writeFileSync(join(target, "sentinel"), "pre-existing");

      await expect(
        saveCheckpointBundle(
          source,
          target,
          expectedManifestSha256,
          realModernDeps({
            publishNoReplace: async () => {
              throw new Error("destination collision");
            },
          }),
        ),
      ).rejects.toThrow(/destination collision/i);
      expect(readFileSync(join(target, "sentinel"), "utf8")).toBe("pre-existing");
      expect(existsSync(`${target}.tmp-modern-test`)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails before staging when destination ancestry is unsafe", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-reparse-"));
    try {
      const source = join(root, "source");
      const expectedManifestSha256 = writeSparseBundle(source);
      let mkdirCalled = false;
      await expect(
        saveCheckpointBundle(
          source,
          join(root, "unsafe-parent", "target"),
          expectedManifestSha256,
          realModernDeps({
            assertSafeDestination: async () => {
              throw new Error("destination ancestry contains a reparse surface");
            },
            mkdirStaging: async () => {
              mkdirCalled = true;
            },
          }),
        ),
      ).rejects.toThrow(/reparse surface/i);
      expect(mkdirCalled).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("saveCheckpoint (core)", () => {
  it("positive: a valid source checkpoint snapshots -- manifest validates, returns the envelope sha, target holds checkpoint + manifest", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-positive-"));
    try {
      const sourceManifestPath = join(root, "source-manifest.json");
      const sourceCheckpointPath = join(root, "source-checkpoint");
      writeFileSync(sourceManifestPath, JSON.stringify({ fixture: "identity-manifest" }));
      writeFileSync(sourceCheckpointPath, "fixture-checkpoint-bytes");

      const targetDir = join(root, "target");
      let resolveCalledWith: string | undefined;
      const deps = realFsDeps(async (manifestPath) => {
        resolveCalledWith = manifestPath;
        return VALID_IDENTITY;
      });

      const result = await saveCheckpoint(sourceManifestPath, sourceCheckpointPath, targetDir, deps);

      expect(resolveCalledWith).toBe(sourceManifestPath);
      expect(result.byte_sha256).toBe(VALID_IDENTITY.byte_sha256);
      expect(result.disposition).toBe(VALID_IDENTITY.disposition);
      expect(result.targetDir).toBe(targetDir);
      expect(existsSync(join(targetDir, "manifest.json"))).toBe(true);
      expect(existsSync(join(targetDir, "checkpoint"))).toBe(true);
      expect(readFileSync(join(targetDir, "checkpoint"), "utf8")).toBe("fixture-checkpoint-bytes");
      // staging dir never left behind on success
      expect(existsSync(`${targetDir}.tmp-test`)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("negative-1: an identity-mismatched (tampered) source is rejected fail-closed -- nothing written to target", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-tampered-"));
    try {
      const sourceManifestPath = join(root, "source-manifest.json");
      const sourceCheckpointPath = join(root, "source-checkpoint");
      writeFileSync(sourceManifestPath, JSON.stringify({ fixture: "identity-manifest" }));
      writeFileSync(sourceCheckpointPath, "tampered-checkpoint-bytes");

      const targetDir = join(root, "target");
      // Fail-closed resolver: the real `_resolveModelIdentity` returns null on any
      // tamper/validation failure -- this is the same contract, injected.
      const deps = realFsDeps(async () => null);

      await expect(
        saveCheckpoint(sourceManifestPath, sourceCheckpointPath, targetDir, deps),
      ).rejects.toThrow(/identity did not validate/);

      expect(existsSync(targetDir)).toBe(false);
      expect(existsSync(`${targetDir}.tmp-test`)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("negative-2: a simulated mid-write failure leaves a pre-existing target dir intact (atomicity, no partial checkpoint)", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-midwrite-"));
    try {
      const sourceManifestPath = join(root, "source-manifest.json");
      const sourceCheckpointPath = join(root, "source-checkpoint");
      writeFileSync(sourceManifestPath, JSON.stringify({ fixture: "identity-manifest" }));
      writeFileSync(sourceCheckpointPath, "fixture-checkpoint-bytes");

      const targetDir = join(root, "target");
      mkdirSync(targetDir);
      writeFileSync(join(targetDir, "sentinel"), "pre-existing-untouched");

      let copyCalls = 0;
      const deps: CheckpointSaveDeps = {
        resolveIdentity: async () => VALID_IDENTITY,
        mkdir: async (path) => { await mkdir(path, { recursive: true }); },
        copyFile: async (src, dest) => {
          copyCalls++;
          // Fail on the SECOND copy (the checkpoint bytes) -- proves a failure
          // partway through staging never touches targetDir at all.
          if (copyCalls === 2) throw new Error("simulated mid-write disk failure");
          await copyFile(src, dest);
        },
        rename: (from, to) => rename(from, to),
        rmStaging: (path) => rm(path, { recursive: true, force: true }),
        stagingPath: (target) => `${target}.tmp-midwrite-test`,
      };

      await expect(
        saveCheckpoint(sourceManifestPath, sourceCheckpointPath, targetDir, deps),
      ).rejects.toThrow(/simulated mid-write disk failure/);

      // targetDir untouched: still ONLY the original sentinel, no rename ever happened.
      expect(existsSync(join(targetDir, "sentinel"))).toBe(true);
      expect(readFileSync(join(targetDir, "sentinel"), "utf8")).toBe("pre-existing-untouched");
      expect(existsSync(join(targetDir, "checkpoint"))).toBe(false);
      expect(existsSync(join(targetDir, "manifest.json"))).toBe(false);
      // orphaned staging dir cleaned up best-effort
      expect(existsSync(`${targetDir}.tmp-midwrite-test`)).toBe(false);
      expect(copyCalls).toBe(2);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
