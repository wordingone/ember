// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Fail-closed producer for the operator source-provenance contract added in
// #921 (operator-surface-pane.ts requires sourceBindingVerified===true plus
// well-formed commit/binary digests before it will render anything other
// than "SOURCE UNVERIFIED/UNBOUND"). Before this file NO producer ever set
// sourceBindingVerified: repl.ts only forwarded raw EMBER_PUBLIC_SOURCE_COMMIT
// / EMBER_CLI_BINARY_SHA256 env strings, so the pane always fell back to
// unverified -- ember #924.
//
// This module independently re-derives both values from the actual bytes on
// disk (git HEAD for the commit, sha256 of the running binary for the hash)
// and only reports verified:true when BOTH claimed values match what was
// independently measured. Any missing evidence, malformed pattern, mismatch,
// or measurement failure returns verified:false with a reason -- never
// throws, never defaults open.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";

const SHA1_HEX  = /^[0-9a-f]{40}$/i;
const SHA256_HEX = /^[0-9a-f]{64}$/i;

export interface SourceBindingInput {
  /** Commit SHA the operator surface wants to display, from env/config. */
  claimedCommit?: string;
  /** Binary SHA-256 the operator surface wants to display, from env/config. */
  claimedBinarySha256?: string;
  /** Working directory to resolve the git repository from. */
  cwd: string;
  /** Path to the actual running binary/entrypoint whose bytes get hashed. */
  binaryPath?: string;
  /** Injection seam for tests: overrides `git rev-parse HEAD`. */
  readGitHead?: (cwd: string) => string;
  /** Injection seam for tests: overrides binary byte reads. */
  readBinaryBytes?: (binaryPath: string) => Buffer;
}

export type SourceBindingFailureReason =
  | "missing-claimed-commit"
  | "malformed-claimed-commit"
  | "missing-claimed-binary-hash"
  | "malformed-claimed-binary-hash"
  | "git-head-unreadable"
  | "commit-mismatch"
  | "missing-binary-path"
  | "binary-unreadable"
  | "binary-hash-mismatch";

export interface SourceBindingResult {
  verified: boolean;
  reason?: SourceBindingFailureReason;
  /** Present only when verified: true -- the independently measured values. */
  measuredCommit?: string;
  measuredBinarySha256?: string;
}

function defaultReadGitHead(cwd: string): string {
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd, encoding: "utf8" }).trim();
}

function defaultReadBinaryBytes(binaryPath: string): Buffer {
  return fs.readFileSync(binaryPath);
}

/**
 * Fail-closed verification: binds a claimed (commit, binary-sha256) pair to
 * the actual inspected source/binary bytes. Never throws -- every failure
 * mode (missing evidence, malformed pattern, mismatch, unreadable source)
 * resolves to { verified: false, reason }.
 */
export function verifySourceBinding(input: SourceBindingInput): SourceBindingResult {
  const {
    claimedCommit,
    claimedBinarySha256,
    cwd,
    binaryPath,
    readGitHead = defaultReadGitHead,
    readBinaryBytes = defaultReadBinaryBytes,
  } = input;

  if (!claimedCommit) return { verified: false, reason: "missing-claimed-commit" };
  if (!SHA1_HEX.test(claimedCommit)) return { verified: false, reason: "malformed-claimed-commit" };

  if (!claimedBinarySha256) return { verified: false, reason: "missing-claimed-binary-hash" };
  if (!SHA256_HEX.test(claimedBinarySha256)) return { verified: false, reason: "malformed-claimed-binary-hash" };

  let measuredCommit: string;
  try {
    measuredCommit = readGitHead(cwd);
  } catch {
    return { verified: false, reason: "git-head-unreadable" };
  }
  if (!SHA1_HEX.test(measuredCommit) || measuredCommit.toLowerCase() !== claimedCommit.toLowerCase()) {
    return { verified: false, reason: "commit-mismatch" };
  }

  if (!binaryPath) return { verified: false, reason: "missing-binary-path" };

  let bytes: Buffer;
  try {
    bytes = readBinaryBytes(binaryPath);
  } catch {
    return { verified: false, reason: "binary-unreadable" };
  }
  const measuredBinarySha256 = createHash("sha256").update(bytes).digest("hex");
  if (measuredBinarySha256.toLowerCase() !== claimedBinarySha256.toLowerCase()) {
    return { verified: false, reason: "binary-hash-mismatch" };
  }

  return { verified: true, measuredCommit, measuredBinarySha256 };
}
