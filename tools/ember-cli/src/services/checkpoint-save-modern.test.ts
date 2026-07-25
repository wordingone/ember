// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/checkpoint-save-modern.test.ts — unit tests for the modern
// /model checkpoint save CORE (issue #1056): verify source -> stage+hash-bind
// -> manifest-last -> atomic publish -> re-verify published, all against the
// REAL fs-backed verifyCheckpointBundle (never a reimplemented validator),
// matching the injection seam commands/model.test.ts already uses.

import { afterEach, describe, expect, it } from "bun:test";
import { createHash } from "crypto";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "fs";
import { copyFile, lstat, mkdir, rename, rm } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";
import {
  saveModernCheckpoint,
  type CheckpointSaveModernDeps,
  type CopiedArtifact,
} from "./checkpoint-save-modern.ts";
import { verifyCheckpointBundle } from "./checkpoint-load.ts";

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

/** Writes a real, closed, byte-valid v5 modern sparse bundle to a fresh temp
 * dir -- the exact same fixture shape services/checkpoint-load.test.ts uses,
 * so both the source AND the eventual saved-copy are real bundles the
 * production verifier accepts. */
function writeV5Bundle(root: string): void {
  const payloads = new Map<string, Buffer>([
    ["shared-model.pt", Buffer.from("shared-model")],
    ["optimizer-state.pt", Buffer.from("optimizer-state")],
    ["replay-state.pt", Buffer.from("replay-state")],
    ...EXPERT_PATHS.map((path) => [path, Buffer.from(path)] as const),
  ]);
  const manifest = {
    schema_version: "ember-sparse-checkpoint-v5",
    // Extra top-level fields, exactly like the real governed Python writer's
    // manifest -- proves the save path copies the manifest byte-for-byte
    // rather than re-serializing a schema_version/shards-only subset (the
    // over-closure trap named in the acceptance map).
    architecture_revision: "ember-sparse-3b-v2",
    launch_seed: 7,
    shards: [...payloads].map(([path, bytes]) => ({
      path,
      bytes: bytes.length,
      sha256: sha256(bytes),
    })),
  };
  for (const [path, bytes] of payloads) {
    writeFileSync(join(root, path), bytes);
  }
  writeFileSync(
    join(root, "checkpoint-manifest.json"),
    Buffer.from(JSON.stringify(manifest) + "\n", "utf8"),
  );
}

/** Real fs-backed deps -- no mocked I/O, mirrors production
 * `_realCheckpointSaveModernDeps` in commands/model.ts, but with a
 * `pathExists`/`copyFileHashed` built from plain fs/promises (no streaming
 * needed for these small fixtures) so the test stays dependency-free. */
function realFsDeps(overrides: Partial<CheckpointSaveModernDeps> = {}): CheckpointSaveModernDeps {
  return {
    verifyBundle: (dir) => verifyCheckpointBundle(dir),
    pathExists: async (path) => {
      try {
        await lstat(path);
        return true;
      } catch {
        return false;
      }
    },
    mkdir: async (path) => {
      await mkdir(path, { recursive: true });
    },
    copyFileHashed: async (src, dest): Promise<CopiedArtifact> => {
      await copyFile(src, dest);
      const bytes = readFileSync(dest);
      return { sha256: sha256(bytes), bytes: bytes.length };
    },
    rename: (from, to) => rename(from, to),
    rmStaging: (path) => rm(path, { recursive: true, force: true }),
    stagingPath: (target) => `${target}.tmp-test`,
    ...overrides,
  };
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("saveModernCheckpoint (core)", () => {
  it("positive round-trip: a real closed v5 bundle saves, and the copy passes the REAL production verifier unchanged", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-positive-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    writeV5Bundle(sourceDir);
    const targetDir = join(root, "target");

    const result = await saveModernCheckpoint(sourceDir, targetDir, realFsDeps());

    expect(result.schemaVersion).toBe("ember-sparse-checkpoint-v5");
    expect(result.artifactCount).toBe(7);

    // The published bytes independently re-verify through the REAL
    // production verifier -- the exact function /model checkpoint load runs.
    const reverified = await verifyCheckpointBundle(targetDir);
    expect(reverified.manifestSha256).toBe(result.manifestSha256);
    expect(reverified.schemaVersion).toBe("ember-sparse-checkpoint-v5");
    expect(reverified.artifacts).toHaveLength(7);

    // Manifest was copied byte-for-byte -- extra top-level fields (the
    // over-closure guard) survived, not just schema_version/shards.
    const savedManifest = JSON.parse(
      readFileSync(join(targetDir, "checkpoint-manifest.json"), "utf8"),
    );
    expect(savedManifest.architecture_revision).toBe("ember-sparse-3b-v2");
    expect(savedManifest.launch_seed).toBe(7);

    // No staging dir left behind.
    expect(readdirSync(root).sort()).toEqual(["source", "target"]);
  });

  it("negative: destination collision (no-replace) refuses before any staging write", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-collision-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    writeV5Bundle(sourceDir);
    const targetDir = join(root, "target");
    mkdirSync(targetDir);
    writeFileSync(join(targetDir, "sentinel"), "pre-existing");

    let mkdirCalled = false;
    await expect(
      saveModernCheckpoint(
        sourceDir,
        targetDir,
        realFsDeps({
          mkdir: async (path) => {
            mkdirCalled = true;
            await mkdir(path, { recursive: true });
          },
        }),
      ),
    ).rejects.toThrow(/destination already exists/);

    expect(mkdirCalled).toBe(false);
    expect(readdirSync(targetDir)).toEqual(["sentinel"]);
  });

  it("negative: a tampered source (named shard changed, manifest unchanged) is refused before any write -- hostile byte substitution", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-tampered-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    writeV5Bundle(sourceDir);
    const manifestBefore = readFileSync(join(sourceDir, "checkpoint-manifest.json"));
    writeFileSync(join(sourceDir, "expert-audio.pt"), Buffer.from("tampered-audio"));
    const targetDir = join(root, "target");

    let mkdirCalled = false;
    await expect(
      saveModernCheckpoint(
        sourceDir,
        targetDir,
        realFsDeps({
          mkdir: async (path) => {
            mkdirCalled = true;
            await mkdir(path, { recursive: true });
          },
        }),
      ),
    ).rejects.toThrow(/corrupt, incomplete, or tampered.*expert-audio\.pt/i);

    expect(mkdirCalled).toBe(false);
    expect(readFileSync(join(sourceDir, "checkpoint-manifest.json"))).toEqual(manifestBefore);
    let targetExists = true;
    try {
      await lstat(targetDir);
    } catch {
      targetExists = false;
    }
    expect(targetExists).toBe(false);
  });

  it("negative: an unsupported/missing schema_version source is refused before any write", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-badschema-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    writeFileSync(
      join(sourceDir, "checkpoint-manifest.json"),
      JSON.stringify({ schema_version: "not-a-real-schema", shards: [] }),
    );
    const targetDir = join(root, "target");

    await expect(
      saveModernCheckpoint(sourceDir, targetDir, realFsDeps()),
    ).rejects.toThrow(/schema version is unsupported/i);
  });

  it("negative: a mid-copy corruption (bytes land wrong) is refused fail-closed, staging cleaned up, target never published", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-midcopy-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    writeV5Bundle(sourceDir);
    const targetDir = join(root, "target");

    let copyCalls = 0;
    await expect(
      saveModernCheckpoint(
        sourceDir,
        targetDir,
        realFsDeps({
          copyFileHashed: async (src, dest): Promise<CopiedArtifact> => {
            copyCalls++;
            if (copyCalls === 2) {
              // Simulate silent corruption: write different bytes than the source.
              writeFileSync(dest, "corrupted-bytes-not-the-source-content");
              const bytes = readFileSync(dest);
              return { sha256: sha256(bytes), bytes: bytes.length };
            }
            await copyFile(src, dest);
            const bytes = readFileSync(dest);
            return { sha256: sha256(bytes), bytes: bytes.length };
          },
        }),
      ),
    ).rejects.toThrow(/did not land intact/);

    let targetExists = true;
    try {
      await lstat(targetDir);
    } catch {
      targetExists = false;
    }
    expect(targetExists).toBe(false);
    expect(readdirSync(root).sort()).toEqual(["source"]);
  });

  it("negative: extra/missing shards in the source manifest are refused before any write (closed shard-set enforcement, reused not reimplemented)", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-shardset-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    writeV5Bundle(sourceDir);
    // Remove one required shard: shard-set is no longer closed for v5.
    rmSync(join(sourceDir, "expert-tool.pt"));
    const targetDir = join(root, "target");

    await expect(
      saveModernCheckpoint(sourceDir, targetDir, realFsDeps()),
    ).rejects.toThrow(/corrupt, incomplete, or tampered/i);
  });

  it("over-closure check: a real unmodified v3-schema bundle (different shard set than v5) still saves and round-trips", async () => {
    const root = mkdtempSync(join(tmpdir(), "ckpt-save-modern-v3-"));
    roots.push(root);
    const sourceDir = join(root, "source");
    mkdirSync(sourceDir);
    const payloads = new Map<string, Buffer>([
      ["shared.pt", Buffer.from("shared")],
      ["replay-state.pt", Buffer.from("replay-state")],
      ...EXPERT_PATHS.map((path) => [path, Buffer.from(path)] as const),
    ]);
    const manifest = {
      schema_version: "ember-sparse-checkpoint-v3",
      shards: [...payloads].map(([path, bytes]) => ({
        path,
        bytes: bytes.length,
        sha256: sha256(bytes),
      })),
    };
    for (const [path, bytes] of payloads) {
      writeFileSync(join(sourceDir, path), bytes);
    }
    writeFileSync(
      join(sourceDir, "checkpoint-manifest.json"),
      Buffer.from(JSON.stringify(manifest) + "\n", "utf8"),
    );
    const targetDir = join(root, "target");

    const result = await saveModernCheckpoint(sourceDir, targetDir, realFsDeps());
    expect(result.schemaVersion).toBe("ember-sparse-checkpoint-v3");
    expect(result.artifactCount).toBe(6);

    const reverified = await verifyCheckpointBundle(targetDir);
    expect(reverified.schemaVersion).toBe("ember-sparse-checkpoint-v3");
  });
});
