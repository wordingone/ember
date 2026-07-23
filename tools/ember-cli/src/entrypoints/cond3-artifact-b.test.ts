// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// cond3-artifact-b.test.ts — consumer replay leg for the cond3 Artifact B
// fixture (state/specs/cond3-seat-bridge-spec.md): the ONE fully-resolved
// OWNED_CANDIDATE identity instance must round-trip GREEN through the REAL
// /model status+load resolver -- the same validate_identity.py subprocess
// convention model.ts uses in production, not a mocked resolver. The Python
// side of the same fixture (validate_identity.py --require-resolved, the
// seat bridge derivation, and its OWNED_CANDIDATE admission refusal) is
// covered in scripts/ember_restart/test_cond3_artifact_b.py.
//
// Fixture lives under tests/ (not tools/.../__fixtures__/model-identity/,
// the sibling used by model.test.ts) because a raw binary checkpoint under a
// control path (tools/, scripts/, ...) cannot carry the comment-marker
// goal_id/workstream_id/next_executed_outcome binding the repo's
// authority-conservation gate requires there; tests/ is outside that scope.

import { describe, it, expect } from "bun:test";
import { createHash } from "crypto";
import { readFileSync } from "fs";
import { join } from "path";
import { _resolveModelIdentity } from "../commands/model.ts";

const FIXTURE_DIR = join(
  import.meta.dir,
  "..",
  "..",
  "..",
  "..",
  "tests",
  "ember_restart",
  "__fixtures__",
  "cond3-artifact-b",
);
const FIXTURE_MANIFEST = join(FIXTURE_DIR, "manifest.json");
const FIXTURE_CHECKPOINT = join(FIXTURE_DIR, "checkpoint");

describe("cond3 Artifact B: /model identity resolution on the fully-resolved OWNED_CANDIDATE instance", () => {
  it("resolves the real fixture through the real validate_identity.py subprocess", async () => {
    const identity = await _resolveModelIdentity(FIXTURE_MANIFEST);

    expect(identity).not.toBeNull();
    expect(identity?.disposition).toBe("OWNED_CANDIDATE");

    // Sanity: byte_sha256 is the REAL hash of the REAL checkpoint bytes on
    // disk, never a hand-typed constant re-asserted against itself.
    const bytes = readFileSync(FIXTURE_CHECKPOINT);
    const actualSha256 = createHash("sha256").update(bytes).digest("hex");
    expect(identity?.byte_sha256).toBe(actualSha256);
  });

  it("fails closed when the checkpoint bytes are tampered (never a stale identity)", async () => {
    const { mkdtempSync, writeFileSync, rmSync } = await import("fs");
    const { tmpdir } = await import("os");
    const { join: pathJoin } = await import("path");

    const tmpDir = mkdtempSync(pathJoin(tmpdir(), "cond3-artifact-b-tamper-"));
    try {
      const manifestCopy = pathJoin(tmpDir, "manifest.json");
      const checkpointCopy = pathJoin(tmpDir, "checkpoint");
      writeFileSync(manifestCopy, readFileSync(FIXTURE_MANIFEST));
      writeFileSync(checkpointCopy, "tampered-bytes-do-not-match-manifest-hash");

      const identity = await _resolveModelIdentity(manifestCopy);
      expect(identity).toBeNull();
    } finally {
      rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
