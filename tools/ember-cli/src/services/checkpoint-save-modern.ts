// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/checkpoint-save-modern.ts — the MODERN `/model checkpoint save` path.
//
// Unlike the legacy `saveCheckpoint` (checkpoint-save.ts: a single opaque
// `manifest.json` + `checkpoint` file pair, NOT `/model checkpoint load`
// compatible -- see that command's own "legacy checkpoint snapshot saved (not
// /model checkpoint load compatible)" message), this snapshots an
// ALREADY-GOVERNED modern sparse checkpoint bundle (`checkpoint-manifest.json`
// + its closed named shard set, schema `ember-sparse-checkpoint-v3/v4/v5` --
// the exact shape `checkpoint-load.ts`'s `verifyCheckpointBundle` already
// verifies and `/model checkpoint load` already consumes) into a new target
// directory, byte-for-byte, so the result round-trips through
// `/model checkpoint load` unchanged.
//
// Design decision recorded in docs/verification/checkpoint-save-1056-acceptance-map.md:
// this module invents NO new format and reimplements NO validation. The
// source bundle is re-verified with the SAME production verifier
// `/model checkpoint load` uses (services/checkpoint-load.ts
// verifyCheckpointBundle) before any byte is written, and the produced
// bundle is re-verified with that same verifier before this function
// returns success -- "the resulting directory passes the production
// checkpoint bundle verifier unchanged" is proven by executing that verifier
// a second time, not merely claimed by construction.
//
// The manifest is copied byte-for-byte (never re-serialized) because the
// loader does not close the manifest's TOP-LEVEL key set beyond
// schema_version/shards -- the governed Python writer's own fields
// (architecture, lineage, optimizer_contract, rng_state_sha256, ...) are
// allowed-but-not-required from the loader's point of view, and
// re-serializing a subset would silently drop them while still passing the
// loader (the over-closure trap the acceptance map names explicitly).

import { basename, join } from "path";
import type { VerifiedCheckpointBundle } from "./checkpoint-load.ts";

export interface CheckpointSaveModernResult {
  targetDir: string;
  manifestSha256: string;
  schemaVersion: string;
  artifactCount: number;
}

/** One artifact copy, with its own freshly-measured sha256 + byte count --
 * always measured from the bytes actually written to `dest`, never assumed
 * or restated from the source artifact's manifest record. */
export interface CopiedArtifact {
  sha256: string;
  bytes: number;
}

export interface CheckpointSaveModernDeps {
  /** Re-verifies a checkpoint bundle directory against the SAME closed-schema,
   * hash-bound contract `/model checkpoint load` uses. Called once against
   * the SOURCE (before any write) and once against the freshly published
   * TARGET (after the atomic rename) -- the second call is what proves the
   * round-trip, not an assumption that the copy succeeded. Production
   * default: the real `verifyCheckpointBundle`; injectable only for tests. */
  verifyBundle: (checkpointDir: string) => Promise<VerifiedCheckpointBundle>;
  /** True when `path` already exists (any type: file, directory, symlink) --
   * the destination no-replace collision check, fail-closed and evaluated
   * BEFORE any staging write. */
  pathExists: (path: string) => Promise<boolean>;
  mkdir: (path: string) => Promise<void>;
  /** Copies `src` to `dest` and returns the FRESHLY MEASURED sha256 + byte
   * count of the bytes actually landed at `dest` -- never the source
   * artifact's pre-recorded sha256/bytes restated as though re-verified. */
  copyFileHashed: (src: string, dest: string) => Promise<CopiedArtifact>;
  rename: (from: string, to: string) => Promise<void>;
  rmStaging: (path: string) => Promise<void>;
  stagingPath: (targetDir: string) => string;
}

export class CheckpointSaveModernError extends Error {
  constructor(detail: string) {
    super(`modern checkpoint save refused: ${detail}`);
    this.name = "CheckpointSaveModernError";
  }
}

/**
 * Snapshots the governed sparse checkpoint bundle at `sourceCheckpointDir`
 * into `targetDir`:
 *
 *   1. verify source (production verifier; refuses a corrupt/tampered/
 *      unsupported-schema source before any write)
 *   2. refuse if `targetDir` already exists (no-replace, checked before any
 *      write -- not merely relied on at rename time)
 *   3. stage every shard into a fresh sibling temp dir, hash-binding each as
 *      it lands (bytes+sha256 of the copy, not the source record, checked)
 *   4. write the manifest LAST, byte-identical to the verified source
 *      manifest, only after every shard it names is already staged and
 *      hash-confirmed
 *   5. atomically publish (rename staging -> targetDir; the only moment
 *      targetDir's identity changes)
 *   6. re-verify the PUBLISHED bundle with the production verifier -- the
 *      round-trip proof, not an assumption
 *
 * FAIL-CLOSED at every step: a source that does not verify, a destination
 * that already exists, a mid-copy failure, or a published bundle that
 * (absent a race) fails re-verification all throw. `targetDir` is guaranteed
 * untouched until the single atomic rename in step 5, and nothing is ever
 * reported saved without a fresh verifier pass on the actual published bytes.
 */
export async function saveModernCheckpoint(
  sourceCheckpointDir: string,
  targetDir: string,
  deps: CheckpointSaveModernDeps,
): Promise<CheckpointSaveModernResult> {
  // 1. Verify the source is a real, hash-bound, closed-schema bundle -- the
  // SAME check /model checkpoint load performs. Never reimplemented.
  const source = await deps.verifyBundle(sourceCheckpointDir);

  // 2. Destination no-replace: refuse before any write, not merely at
  // rename time -- a named, fail-closed refusal instead of a raw fs error.
  if (await deps.pathExists(targetDir)) {
    throw new CheckpointSaveModernError(
      `destination already exists: ${targetDir}`,
    );
  }

  const stagingDir = deps.stagingPath(targetDir);
  try {
    await deps.mkdir(stagingDir);

    // 3. Copy every shard FIRST, hash-binding each as it lands. Order
    // follows `source.artifacts` (already the manifest's own shard order);
    // the manifest itself is written last, below.
    for (const artifact of source.artifacts) {
      const destPath = join(stagingDir, artifact.path);
      const copied = await deps.copyFileHashed(
        join(source.checkpointDir, artifact.path),
        destPath,
      );
      if (copied.bytes !== artifact.bytes || copied.sha256 !== artifact.sha256) {
        throw new CheckpointSaveModernError(
          `${artifact.path} did not land intact (expected ${artifact.bytes}B ` +
            `sha256 ${artifact.sha256}, wrote ${copied.bytes}B sha256 ${copied.sha256})`,
        );
      }
    }

    // 4. Manifest LAST, byte-identical to the verified source manifest --
    // this is what "publishes" the bundle's identity; every artifact it
    // names is already staged and hash-confirmed above.
    const manifestDestName = basename(source.manifestPath);
    const manifestCopy = await deps.copyFileHashed(
      source.manifestPath,
      join(stagingDir, manifestDestName),
    );
    if (manifestCopy.sha256 !== source.manifestSha256) {
      throw new CheckpointSaveModernError(
        `${manifestDestName} did not land intact (expected sha256 ` +
          `${source.manifestSha256}, wrote ${manifestCopy.sha256})`,
      );
    }

    // 5. Atomic, no-replace publish. A same-filesystem rename is the only
    // moment `targetDir`'s identity changes; every prior throw leaves it
    // completely absent.
    await deps.rename(stagingDir, targetDir);
  } catch (error) {
    try {
      await deps.rmStaging(stagingDir);
    } catch {
      // Best-effort only; never masks the original error, never touches targetDir.
    }
    throw error;
  }

  // 6. Re-verify the PUBLISHED bytes with the production verifier -- the
  // same one /model checkpoint load will run. This is the round-trip proof,
  // not an assumption that steps 3-5 succeeded.
  const published = await deps.verifyBundle(targetDir);
  if (
    published.manifestSha256 !== source.manifestSha256 ||
    published.schemaVersion !== source.schemaVersion ||
    published.artifacts.length !== source.artifacts.length
  ) {
    throw new CheckpointSaveModernError(
      `published bundle at ${targetDir} diverges from the verified source ` +
        `(unreachable outside a concurrent external mutation of targetDir ` +
        `between the atomic rename and this re-verification)`,
    );
  }

  return {
    targetDir: published.checkpointDir,
    manifestSha256: published.manifestSha256,
    schemaVersion: published.schemaVersion,
    artifactCount: published.artifacts.length,
  };
}
