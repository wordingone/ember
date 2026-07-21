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
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { copyFile, mkdir, rename, rm } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";
import { saveCheckpoint, type CheckpointSaveDeps } from "./checkpoint-save.ts";
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
