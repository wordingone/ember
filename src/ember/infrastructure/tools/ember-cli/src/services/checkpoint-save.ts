// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/checkpoint-save.ts — core of the /model checkpoint save spine verb.
//
// Pairs with the already-landed checkpoint-LOAD wiring (PR #983 / model.ts
// `/model load`). This is a PRE-TRAINING spine surface: it snapshots an
// ALREADY-EXISTING checkpoint (the currently-loaded seat, or an explicit
// reference) to a target directory and writes its identity manifest. It
// never trains and never produces new weights.
//
// The source checkpoint convention mirrors `_resolveModelIdentity` in
// commands/model.ts: a manifest JSON file (validated by
// scripts/ember_01_identity/validate_identity.py) plus, alongside it, a
// binary `checkpoint` file named literally `checkpoint`. `saveCheckpoint`
// below is the CORE — validate -> atomic copy -> return sha — kept
// deliberately separate from "which path is the currently-loaded seat",
// which stays in commands/model.ts (the seam ember-cli's owned-seat-loader/
// model-seat machinery already owns).

import type { ResolvedModelIdentity } from "../commands/model.ts";
import type { VerifiedCheckpointBundle } from "./checkpoint-load.ts";
import { join } from "path";

const SHA256_RE = /^[0-9a-f]{64}$/;

export interface ModernCheckpointSaveResult {
  manifestSha256: string;
  schemaVersion: string;
  artifactCount: number;
  targetDir: string;
}

export interface ModernCheckpointSaveDeps {
  verifyBundle: (checkpointDir: string) => Promise<VerifiedCheckpointBundle>;
  assertSafeDestination: (targetDir: string) => Promise<void>;
  mkdirStaging: (path: string) => Promise<void>;
  copyFile: (src: string, dest: string) => Promise<void>;
  publishNoReplace: (from: string, to: string) => Promise<void>;
  rmStaging: (path: string) => Promise<void>;
  stagingPath: (targetDir: string) => string;
}

function bundleProjection(bundle: VerifiedCheckpointBundle): string {
  return JSON.stringify({
    manifestSha256: bundle.manifestSha256,
    schemaVersion: bundle.schemaVersion,
    artifacts: [...bundle.artifacts]
      .map(({ path, bytes, sha256 }) => ({ path, bytes, sha256 }))
      .sort((left, right) => left.path.localeCompare(right.path)),
  });
}

function requireSameBundle(
  expected: VerifiedCheckpointBundle,
  actual: VerifiedCheckpointBundle,
  label: string,
): void {
  if (bundleProjection(actual) !== bundleProjection(expected)) {
    throw new Error(
      `checkpoint save refused: ${label} no longer matches the selected governed bundle`,
    );
  }
}

/**
 * Snapshot one already-governed sparse checkpoint bundle without changing its
 * format or authority. The unchanged production verifier defines the source,
 * staged, and published bundle contract.
 *
 * The durable selected checkpoint digest is mandatory. A self-consistent but
 * different bundle is structurally valid yet ineligible for this save path.
 * Saving never admits a checkpoint or grants ownership.
 */
export async function saveCheckpointBundle(
  sourceDir: string,
  targetDir: string,
  selectedManifestSha256: string,
  deps: ModernCheckpointSaveDeps,
): Promise<ModernCheckpointSaveResult> {
  if (!SHA256_RE.test(selectedManifestSha256)) {
    throw new Error(
      "checkpoint save refused: selected checkpoint digest is missing or invalid",
    );
  }

  const selected = await deps.verifyBundle(sourceDir);
  if (selected.manifestSha256 !== selectedManifestSha256) {
    throw new Error(
      "checkpoint save refused: source does not match the selected checkpoint digest",
    );
  }
  await deps.assertSafeDestination(targetDir);

  const stagingDir = deps.stagingPath(targetDir);
  let stagingCreated = false;
  try {
    await deps.mkdirStaging(stagingDir);
    stagingCreated = true;

    // Closed named artifact set comes only from the production verifier.
    // The manifest is deliberately copied last.
    for (const artifact of [...selected.artifacts].sort((left, right) =>
      left.path.localeCompare(right.path)
    )) {
      await deps.copyFile(
        join(selected.checkpointDir, artifact.path),
        join(stagingDir, artifact.path),
      );
    }
    await deps.copyFile(selected.manifestPath, join(stagingDir, "checkpoint-manifest.json"));

    const staged = await deps.verifyBundle(stagingDir);
    requireSameBundle(selected, staged, "staged bundle");

    // Re-read the source after every copied byte. This closes source swaps
    // between initial verification and publication.
    const sourceAfterCopy = await deps.verifyBundle(selected.checkpointDir);
    requireSameBundle(selected, sourceAfterCopy, "source bundle");

    await deps.publishNoReplace(stagingDir, targetDir);
    stagingCreated = false;

    const published = await deps.verifyBundle(targetDir);
    requireSameBundle(selected, published, "published bundle");

    return {
      manifestSha256: published.manifestSha256,
      schemaVersion: published.schemaVersion,
      artifactCount: published.artifacts.length,
      targetDir: published.checkpointDir,
    };
  } catch (error) {
    if (stagingCreated) {
      try {
        await deps.rmStaging(stagingDir);
      } catch {
        // Preserve the original failure. No target publication occurred.
      }
    }
    throw error;
  }
}

export interface CheckpointSaveResult {
  byte_sha256: string;
  disposition: string;
  targetDir: string;
}

/** Injectable filesystem seam so the atomic-write and fail-closed paths are
 * unit-testable against a fixture, with no real disk I/O required to exercise
 * the failure branches (mid-write failure, tampered source). */
export interface CheckpointSaveDeps {
  /** Resolves + validates the SOURCE manifest's identity. Reuses the same
   * `_resolveModelIdentity` contract already wired through /model status|load
   * — never a reimplemented validator. Returns null on any failure to
   * validate (missing manifest, tampered bytes, subprocess rejection). */
  resolveIdentity: (manifestPath: string) => Promise<ResolvedModelIdentity | null>;
  mkdir: (path: string) => Promise<void>;
  copyFile: (src: string, dest: string) => Promise<void>;
  rename: (from: string, to: string) => Promise<void>;
  /** Best-effort cleanup of an orphaned staging dir after a failed save.
   * Failure to clean up is never surfaced — the target dir's integrity is
   * the only invariant this module guarantees. */
  rmStaging: (path: string) => Promise<void>;
  /** Produces a staging directory path sibling to the target, unique per
   * call (default: `${targetDir}.tmp-<random>`). Injectable so tests can
   * assert on the exact staging path. */
  stagingPath: (targetDir: string) => string;
}

/**
 * Snapshots the checkpoint at `sourceManifestPath` (+ its sibling
 * `sourceCheckpointPath`) into `targetDir`, atomically, after validating the
 * source's identity fail-closed.
 *
 * Sequence: validate identity (reject before any write) -> stage into a
 * fresh sibling temp dir -> copy manifest + checkpoint bytes into staging ->
 * rename staging -> targetDir (atomic on same filesystem). A failure at any
 * point strictly BEFORE the rename leaves `targetDir` completely untouched —
 * pre-existing content there survives a mid-write failure unmodified, and no
 * partial checkpoint is ever visible at `targetDir`.
 *
 * FAIL-CLOSED: throws (never returns a partial/best-effort result) when the
 * source identity does not validate, or when any write step fails.
 */
export async function saveCheckpoint(
  sourceManifestPath: string,
  sourceCheckpointPath: string,
  targetDir: string,
  deps: CheckpointSaveDeps,
): Promise<CheckpointSaveResult> {
  const identity = await deps.resolveIdentity(sourceManifestPath);
  if (identity === null) {
    throw new Error(
      "checkpoint save refused: source checkpoint identity did not validate",
    );
  }

  const stagingDir = deps.stagingPath(targetDir);
  try {
    await deps.mkdir(stagingDir);
    await deps.copyFile(sourceManifestPath, join(stagingDir, "manifest.json"));
    await deps.copyFile(sourceCheckpointPath, join(stagingDir, "checkpoint"));
    // Atomic swap: only after every byte is staged does the target identity
    // change. A crash/throw at any prior line leaves `targetDir` untouched.
    await deps.rename(stagingDir, targetDir);
  } catch (error) {
    // Best-effort cleanup of the orphaned staging dir; never lets a cleanup
    // failure mask the original error, and never touches targetDir itself.
    try {
      await deps.rmStaging(stagingDir);
    } catch {
      // Nothing more a fail-closed save can do about an unremovable orphan;
      // targetDir's integrity (the actual invariant) is unaffected.
    }
    throw error;
  }

  return {
    byte_sha256: identity.byte_sha256,
    disposition: identity.disposition,
    targetDir,
  };
}
