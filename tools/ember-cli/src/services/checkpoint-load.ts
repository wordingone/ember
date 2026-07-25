// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "crypto";
import type { Stats } from "fs";
import { lstat, open, readdir } from "fs/promises";
import { basename, dirname, join, resolve } from "path";

const SHA256_RE = /^[0-9a-f]{64}$/;
const MANIFEST_NAME = "checkpoint-manifest.json";
const EXPERT_NAMES = ["vision", "audio", "reasoning", "tool"] as const;
const SUPPORTED_SCHEMAS = new Set([
  "ember-sparse-checkpoint-v3",
  "ember-sparse-checkpoint-v4",
  "ember-sparse-checkpoint-v5",
]);
export const CHECKPOINT_HASH_CHUNK_BYTES = 1024 * 1024;
export const MAX_CHECKPOINT_MANIFEST_BYTES = 1024 * 1024;


export interface CheckpointLoadFsDeps {
  open: (
    path: string,
    flags: "r",
  ) => Promise<Pick<Awaited<ReturnType<typeof open>>, "stat" | "read" | "close">>;
}

const DEFAULT_FS_DEPS: CheckpointLoadFsDeps = {
  open,
};

export interface VerifiedCheckpointArtifact {
  path: string;
  bytes: number;
  sha256: string;
}

export interface VerifiedCheckpointBundle {
  checkpointDir: string;
  manifestPath: string;
  manifestSha256: string;
  schemaVersion: string;
  artifacts: readonly VerifiedCheckpointArtifact[];
}

export class CheckpointBundleIntegrityError extends Error {
  constructor(detail: string) {
    super(
      `This checkpoint bundle is corrupt, incomplete, or tampered. ${detail} ` +
        "Restore or regenerate the bundle and retry; no model process was started.",
    );
    this.name = "CheckpointBundleIntegrityError";
  }
}

function fail(detail: string): never {
  throw new CheckpointBundleIntegrityError(detail);
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}
function sameFileSnapshot(left: Stats, right: Stats): boolean {

  return (
    left.isFile() &&
    right.isFile() &&
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.size === right.size &&
    left.mtimeMs === right.mtimeMs &&
    left.ctimeMs === right.ctimeMs
  );
}
async function readManifestFile(path: string, fsDeps: CheckpointLoadFsDeps): Promise<Buffer> {
  let handle;
  try {
    handle = await fsDeps.open(path, "r");
  } catch {
    fail(`${MANIFEST_NAME} is unreadable.`);
  }

  let openedBefore: Stats;
  let openedAfter: Stats;
  let bytes: Buffer;
  try {
    openedBefore = await handle.stat();
    if (
      !openedBefore.isFile() ||
      openedBefore.size <= 0 ||
      openedBefore.size > MAX_CHECKPOINT_MANIFEST_BYTES
    ) {
      fail(`${MANIFEST_NAME} exceeds the maximum allowed size or is empty.`);
    }

    bytes = Buffer.allocUnsafe(openedBefore.size);
    let position = 0;
    while (position < bytes.length) {
      const { bytesRead } = await handle.read(
        bytes,
        position,
        bytes.length - position,
        position,
      );
      if (bytesRead <= 0 || bytesRead > bytes.length - position) {
        fail(`${MANIFEST_NAME} changed or ended while it was being verified.`);
      }
      position += bytesRead;
    }
    openedAfter = await handle.stat();
  } catch (error) {
    if (error instanceof CheckpointBundleIntegrityError) throw error;
    fail(`${MANIFEST_NAME} is unreadable.`);
  } finally {
    try {
      await handle.close();
    } catch {
      fail(`${MANIFEST_NAME} could not be closed after verification.`);
    }
  }

  let pathAfter: Stats;
  try {
    pathAfter = await lstat(path);
  } catch {
    fail(`${MANIFEST_NAME} changed or disappeared while it was being verified.`);
  }
  if (
    pathAfter.isSymbolicLink() ||
    !sameFileSnapshot(openedBefore, openedAfter) ||
    !sameFileSnapshot(openedAfter, pathAfter)
  ) {
    fail(`${MANIFEST_NAME} changed while it was being verified.`);
  }
  return bytes;
}


async function hashArtifactFile(
  artifactPath: string,
  artifact: VerifiedCheckpointArtifact,
  fsDeps: CheckpointLoadFsDeps,
): Promise<string> {
  let handle;
  try {
    handle = await fsDeps.open(artifactPath, "r");
  } catch {
    fail(`${artifact.path} is unreadable.`);
  }

  let openedBefore: Stats;
  let openedAfter: Stats;
  const digest = createHash("sha256");
  const buffer = Buffer.allocUnsafe(
    Math.min(CHECKPOINT_HASH_CHUNK_BYTES, artifact.bytes),
  );

  try {
    openedBefore = await handle.stat();
    if (!openedBefore.isFile() || openedBefore.size !== artifact.bytes) {
      fail(`${artifact.path} byte size does not match the manifest.`);
    }

    let position = 0;
    while (position < artifact.bytes) {
      const length = Math.min(buffer.length, artifact.bytes - position);
      const { bytesRead } = await handle.read(buffer, 0, length, position);
      if (bytesRead <= 0 || bytesRead > length) {
        fail(`${artifact.path} changed or ended while it was being verified.`);
      }
      digest.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    openedAfter = await handle.stat();
  } catch (error) {
    if (error instanceof CheckpointBundleIntegrityError) throw error;
    fail(`${artifact.path} is unreadable.`);
  } finally {
    try {
      await handle.close();
    } catch {
      fail(`${artifact.path} could not be closed after verification.`);
    }
  }

  let pathAfter: Stats;
  try {
    pathAfter = await lstat(artifactPath);
  } catch {
    fail(`${artifact.path} changed or disappeared while it was being verified.`);
  }
  if (
    pathAfter.isSymbolicLink() ||
    !sameFileSnapshot(openedBefore, openedAfter) ||
    !sameFileSnapshot(openedAfter, pathAfter)
  ) {
    fail(`${artifact.path} changed while it was being verified.`);
  }
  return digest.digest("hex");
}

function objectRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(`${label} must be a JSON object.`);
  }
  return value as Record<string, unknown>;
}

function decodeManifest(bytes: Buffer): Record<string, unknown> {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    fail(`${MANIFEST_NAME} is not strict UTF-8.`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    fail(`${MANIFEST_NAME} is not valid JSON.`);
  }
  return objectRecord(parsed, MANIFEST_NAME);
}

function expectedPaths(schemaVersion: string): Set<string> {
  const experts = EXPERT_NAMES.map((name) => `expert-${name}.pt`);
  if (schemaVersion === "ember-sparse-checkpoint-v5") {
    return new Set([
      "shared-model.pt",
      "optimizer-state.pt",
      "replay-state.pt",
      ...experts,
    ]);
  }
  return new Set(["shared.pt", "replay-state.pt", ...experts]);
}

function validateShardRecord(
  value: unknown,
  index: number,
): VerifiedCheckpointArtifact {
  const record = objectRecord(value, `shards[${index}]`);
  const allowed = new Set([
    "path",
    "bytes",
    "sha256",
    "publication_mode",
    "incremental_bytes",
  ]);
  for (const key of Object.keys(record)) {
    if (!allowed.has(key)) fail(`shards[${index}] has unknown field ${key}.`);
  }

  const relative = record.path;
  const bytes = record.bytes;
  const digest = record.sha256;
  if (
    typeof relative !== "string" ||
    relative.length === 0 ||
    relative !== basename(relative) ||
    relative.includes("/") ||
    relative.includes("\\") ||
    relative === "." ||
    relative === ".."
  ) {
    fail(`shards[${index}].path is not a confined bundle-relative filename.`);
  }
  if (!Number.isSafeInteger(bytes) || (bytes as number) <= 0) {
    fail(`${relative} has an invalid byte count.`);
  }
  if (typeof digest !== "string" || !SHA256_RE.test(digest)) {
    fail(`${relative} has an invalid SHA-256.`);
  }

  const hasPublication = "publication_mode" in record || "incremental_bytes" in record;
  if (hasPublication) {
    const mode = record.publication_mode;
    const incremental = record.incremental_bytes;
    if (
      !["written", "hardlink", "copy"].includes(String(mode)) ||
      !Number.isSafeInteger(incremental) ||
      (incremental as number) < 0 ||
      (mode === "hardlink" ? incremental !== 0 : incremental !== bytes)
    ) {
      fail(`${relative} has an invalid publication record.`);
    }
  }

  return { path: relative, bytes: bytes as number, sha256: digest };
}

async function requireRegularPath(
  path: string,
  kind: "file" | "directory",
  label: string,
): Promise<void> {
  let stat;
  try {
    stat = await lstat(path);
  } catch {
    fail(`${label} is missing or unreadable.`);
  }
  if (
    stat.isSymbolicLink() ||
    (kind === "file" ? !stat.isFile() : !stat.isDirectory())
  ) {
    fail(`${label} must be a regular ${kind}, not an alias or reparse path.`);
  }
}

/**
 * Refuse a checkpoint directory that is reached through a symlink or junction.
 *
 * The property under test is "no component of this path is a reparse point", so it is tested
 * directly — every ancestor is lstat'd — rather than through the textual proxy of comparing
 * resolve() against realpath(). That proxy refuses legitimate directories whenever the two
 * strings differ for reasons that are not reparse points at all: on Windows realpath returns
 * the canonical on-disk casing while resolve preserves whatever casing the caller typed, and
 * 8.3 short name components expand the same way. Both spellings name exactly the same
 * directory, and both made the loader report a genuine bundle as corrupt.
 */
async function requireNoReparseAncestry(path: string): Promise<void> {
  let current = path;
  for (;;) {
    let stat;
    try {
      stat = await lstat(current);
    } catch {
      fail("checkpoint directory is missing or unreadable.");
    }
    if (stat.isSymbolicLink()) {
      fail("checkpoint directory resolves through an alias or reparse path.");
    }
    const parent = dirname(current);
    if (parent === current) {
      return;
    }
    current = parent;
  }
}

export async function verifyCheckpointBundle(
  checkpointDir: string,
  fsOverrides: Partial<CheckpointLoadFsDeps> = {},
): Promise<VerifiedCheckpointBundle> {
  const fsDeps = { ...DEFAULT_FS_DEPS, ...fsOverrides };
  if (typeof checkpointDir !== "string" || checkpointDir.trim() === "") {
    fail("A checkpoint directory is required.");
  }

  const requestedDir = resolve(checkpointDir);
  await requireRegularPath(requestedDir, "directory", "checkpoint directory");
  await requireNoReparseAncestry(requestedDir);
  // With every ancestor proven to be a real directory, requestedDir already names the same
  // directory realpath() would return, so it is used directly. realpath() is deliberately not
  // called here: on Windows its sync and async forms disagree about canonical casing, which
  // would make the surfaced checkpointDir unstable for no verification benefit.
  const canonicalDir = requestedDir;

  const manifestPath = join(canonicalDir, MANIFEST_NAME);
  await requireRegularPath(manifestPath, "file", MANIFEST_NAME);
  const manifestBytes = await readManifestFile(manifestPath, fsDeps);
  const manifest = decodeManifest(manifestBytes);
  const schemaVersion = manifest.schema_version;
  if (
    typeof schemaVersion !== "string" ||
    !SUPPORTED_SCHEMAS.has(schemaVersion)
  ) {
    fail("checkpoint schema version is unsupported.");
  }

  if (!Array.isArray(manifest.shards)) {
    fail("checkpoint manifest shards must be an array.");
  }
  const artifacts = manifest.shards.map(validateShardRecord);
  const records = new Map<string, VerifiedCheckpointArtifact>();
  for (const artifact of artifacts) {
    if (records.has(artifact.path)) {
      fail(`checkpoint contains duplicate shard path ${artifact.path}.`);
    }
    records.set(artifact.path, artifact);
  }

  const expected = expectedPaths(schemaVersion);
  if (
    records.size !== expected.size ||
    [...expected].some((path) => !records.has(path))
  ) {
    fail(`checkpoint shard set is not closed for ${schemaVersion}.`);
  }

  let entries;
  try {
    entries = await readdir(canonicalDir, { withFileTypes: true });
  } catch {
    fail("checkpoint directory cannot be enumerated.");
  }
  const allowedEntries = new Set([MANIFEST_NAME, ...expected]);
  for (const entry of entries) {
    if (!allowedEntries.has(entry.name)) {
      fail(`unexpected checkpoint bundle entry ${entry.name}.`);
    }
  }
  if (entries.length !== allowedEntries.size) {
    fail("checkpoint bundle is missing one or more required entries.");
  }

  for (const artifact of artifacts) {
    const artifactPath = join(canonicalDir, artifact.path);
    await requireRegularPath(artifactPath, "file", artifact.path);
    const artifactSha256 = await hashArtifactFile(artifactPath, artifact, fsDeps);
    if (artifactSha256 !== artifact.sha256) {
      fail(`${artifact.path} SHA-256 does not match the manifest.`);
    }
  }

  return {
    checkpointDir: canonicalDir,
    manifestPath,
    manifestSha256: sha256(manifestBytes),
    schemaVersion,
    artifacts,
  };
}
