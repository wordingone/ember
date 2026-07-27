// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { verifySourceBinding } from "./source-binding-verifier.ts";

const COMMIT = "a".repeat(40);
const OTHER_COMMIT = "b".repeat(40);
const HASH = "c".repeat(64);
const OTHER_HASH = "d".repeat(64);

describe("verifySourceBinding", () => {
  test("verifies true end-to-end when claimed commit + binary hash equal the independently measured bytes", async () => {
    const { createHash } = await import("node:crypto");
    const bytes = Buffer.from("binary-bytes-fixture");
    const realHash = createHash("sha256").update(bytes).digest("hex");
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: realHash,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => COMMIT,
      readBinaryBytes:     () => bytes,
    });
    expect(result).toEqual({ verified: true, measuredCommit: COMMIT, measuredBinarySha256: realHash });
  });

  test("fails closed on missing claimed commit", () => {
    const result = verifySourceBinding({
      claimedBinarySha256: HASH,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => COMMIT,
      readBinaryBytes:     () => Buffer.from("x"),
    });
    expect(result).toEqual({ verified: false, reason: "missing-claimed-commit" });
  });

  test("fails closed on malformed claimed commit", () => {
    const result = verifySourceBinding({
      claimedCommit:       "not-a-sha",
      claimedBinarySha256: HASH,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => COMMIT,
      readBinaryBytes:     () => Buffer.from("x"),
    });
    expect(result).toEqual({ verified: false, reason: "malformed-claimed-commit" });
  });

  test("fails closed on missing claimed binary hash", () => {
    const result = verifySourceBinding({
      claimedCommit: COMMIT,
      cwd:           "/repo",
      binaryPath:    "/bin/ember",
      readGitHead:   () => COMMIT,
    });
    expect(result).toEqual({ verified: false, reason: "missing-claimed-binary-hash" });
  });

  test("fails closed on malformed claimed binary hash", () => {
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: "not-a-hash",
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => COMMIT,
    });
    expect(result).toEqual({ verified: false, reason: "malformed-claimed-binary-hash" });
  });

  test("fails closed when git HEAD read throws", () => {
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: HASH,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => { throw new Error("not a git repo"); },
    });
    expect(result).toEqual({ verified: false, reason: "git-head-unreadable" });
  });

  test("fails closed when measured commit does not match claimed commit (stale claim)", () => {
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: HASH,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => OTHER_COMMIT,
    });
    expect(result).toEqual({ verified: false, reason: "commit-mismatch" });
  });

  test("fails closed when binaryPath is absent", () => {
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: HASH,
      cwd:                 "/repo",
      readGitHead:         () => COMMIT,
    });
    expect(result).toEqual({ verified: false, reason: "missing-binary-path" });
  });

  test("fails closed when binary bytes are unreadable", () => {
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: HASH,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => COMMIT,
      readBinaryBytes:     () => { throw new Error("ENOENT"); },
    });
    expect(result).toEqual({ verified: false, reason: "binary-unreadable" });
  });

  test("fails closed when measured binary hash does not match claimed hash", () => {
    const result = verifySourceBinding({
      claimedCommit:       COMMIT,
      claimedBinarySha256: OTHER_HASH,
      cwd:                 "/repo",
      binaryPath:          "/bin/ember",
      readGitHead:         () => COMMIT,
      readBinaryBytes:     () => Buffer.from("fixture"),
    });
    expect(result.verified).toBe(false);
    expect(result.reason).toBe("binary-hash-mismatch");
  });
});
