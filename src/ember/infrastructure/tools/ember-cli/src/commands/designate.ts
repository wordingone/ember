// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// /designate selects one admitted candidate. It never mints, loads, or trains.

import { createHash, randomBytes } from "node:crypto";
import {
  lstatSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, parse, relative, resolve, sep } from "node:path";
import type { CommandContext, CommandResult, RegistryCommand } from "../types/command-types.ts";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { verifyAdmissionProducerReceipt } from "./admit.ts";

/** The required-argument shape, declared once. USAGE renders it for the failure path; the
 *  registry entry publishes it as `argumentHint` so the command bar composes `/designate ` on
 *  click rather than dispatching a bare invocation that can only be a usage error. */
const ARGUMENT_HINT =
  "--output-root <path> --candidate-id <id> " +
  "--candidate-sha256 <sha256> --producer-receipt-sha256 <sha256>";
const USAGE = `usage: /designate ${ARGUMENT_HINT}`;
const SHA256_RE = /^[0-9a-f]{64}$/;
// Identical grammar to admit.ts's CANDIDATE_ID_RE (#1107 P1 cure): no dot, no
// slash -- "current.json" and any owned/-escaping path component are
// structurally unreachable through this pattern, not merely blocklisted.
const CANDIDATE_ID_RE = /^[a-z][a-z0-9_-]*$/;
const SELECTED_ROLE = "restart_run_manifest";

export interface DesignateOptions {
  outputRoot: string;
  candidateId: string;
  candidateSha256: string;
  producerReceiptSha256: string;
}

export interface DesignateCommandDeps {
  getConfigHome?: () => string;
  /** Defaults to the exact verifier /admit itself uses on its own output --
   * designation never re-derives bundle validity through a second, possibly
   * divergent, schema. */
  verifyReceipt?: (outputRoot: string, payload: Record<string, unknown>) => string | null;
  now?: () => Date;
}

interface FileIdentity {
  relative_path: string;
  sha256: string;
  bytes: number;
}

function refuse(message: string): CommandResult {
  return { type: "message", message, exitCode: 2 };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`).join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new TypeError("non-JSON receipt value");
  return encoded;
}

function parseOptions(args: string): DesignateOptions | null {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  const values = new Map<string, string>();
  const allowed = new Set([
    "--output-root",
    "--candidate-id",
    "--candidate-sha256",
    "--producer-receipt-sha256",
  ]);
  for (let index = 0; index < parts.length; index += 2) {
    const option = parts[index];
    const value = parts[index + 1];
    if (
      option === undefined ||
      value === undefined ||
      !allowed.has(option) ||
      value.startsWith("--") ||
      values.has(option)
    ) {
      return null;
    }
    values.set(option, value);
  }
  if (parts.length !== 8) return null;
  const outputRoot = values.get("--output-root");
  const candidateId = values.get("--candidate-id");
  const candidateSha256 = values.get("--candidate-sha256");
  const producerReceiptSha256 = values.get("--producer-receipt-sha256");
  return outputRoot && candidateId && candidateSha256 && producerReceiptSha256
    ? { outputRoot, candidateId, candidateSha256, producerReceiptSha256 }
    : null;
}

/** Same containment discipline as admit.ts's own helper of the same name:
 * every path component from root down to the target must be a real
 * directory (or the final component a real file), none of them a symlink
 * or reparse point, and the target must actually resolve inside root. */
function isRegularFileUnderUnlinkedRoot(root: string, file: string): boolean {
  const absoluteRoot = resolve(root);
  const absoluteFile = resolve(file);
  const fromRoot = relative(absoluteRoot, absoluteFile);
  if (
    fromRoot === "" ||
    isAbsolute(fromRoot) ||
    fromRoot === ".." ||
    fromRoot.startsWith(`..${sep}`)
  ) {
    return false;
  }
  const anchor = parse(absoluteFile).root;
  let current = anchor;
  try {
    const parts = relative(anchor, absoluteFile).split(sep).filter(Boolean);
    for (let index = 0; index < parts.length; index += 1) {
      current = join(current, parts[index]!);
      const info = lstatSync(current);
      if (info.isSymbolicLink()) return false;
      if (index === parts.length - 1) {
        if (!info.isFile()) return false;
      } else if (!info.isDirectory()) {
        return false;
      }
    }
  } catch {
    return false;
  }
  return true;
}

function parseFileIdentity(value: unknown): FileIdentity | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const identity = value as Record<string, unknown>;
  if (
    Object.keys(identity).sort().join(",") !== "bytes,relative_path,sha256" ||
    typeof identity.relative_path !== "string" ||
    typeof identity.sha256 !== "string" ||
    !SHA256_RE.test(identity.sha256) ||
    typeof identity.bytes !== "number" ||
    !Number.isSafeInteger(identity.bytes) ||
    identity.bytes < 0
  ) {
    return null;
  }
  return identity as unknown as FileIdentity;
}

/** Re-reads the receipt this exact process JUST proved authentic (via
 * verifyReceipt, called immediately before this) to pull out the one field
 * designation needs: which published file is the restart_run_manifest.
 * This is not a second, independent validation pass -- it is reading a
 * single already-verified field out of already-verified bytes. */
function readSelectedManifestIdentity(
  outputRoot: string,
  candidateId: string,
  producerReceiptSha256: string,
): FileIdentity | null {
  const receiptPath = resolve(
    outputRoot,
    candidateId,
    "producer-receipts",
    `${producerReceiptSha256}.json`,
  );
  if (!isRegularFileUnderUnlinkedRoot(resolve(outputRoot, candidateId), receiptPath)) {
    return null;
  }
  let receiptBytes: Buffer;
  try {
    receiptBytes = readFileSync(receiptPath);
  } catch {
    return null;
  }
  if (createHash("sha256").update(receiptBytes).digest("hex") !== producerReceiptSha256) {
    return null;
  }
  let receipt: Record<string, unknown>;
  try {
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(receiptBytes));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    receipt = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  const outputIdentities = receipt.output_identities;
  if (typeof outputIdentities !== "object" || outputIdentities === null || Array.isArray(outputIdentities)) {
    return null;
  }
  return parseFileIdentity((outputIdentities as Record<string, unknown>)[SELECTED_ROLE]);
}

export function createDesignateCommand(deps: DesignateCommandDeps = {}): RegistryCommand {
  const getConfigHome = deps.getConfigHome ?? getEmberConfigHomeDir;
  const verifyReceipt = deps.verifyReceipt ?? verifyAdmissionProducerReceipt;
  const now = deps.now ?? (() => new Date());
  return {
    name: "designate",
    description:
      "Atomically select one admitted candidate into the live owned/current.json seat pointer, " +
      "with hash-verified read-back and a designation receipt",
    argumentHint: ARGUMENT_HINT,
    isEnabled: () => true,
    async execute(args: string, _context: CommandContext) {
      const options = parseOptions(args);
      if (options === null) {
        return { type: "message" as const, message: USAGE, exitCode: 2 };
      }
      if (!CANDIDATE_ID_RE.test(options.candidateId)) {
        return refuse("designation refused: invalid candidate id");
      }
      if (
        !SHA256_RE.test(options.candidateSha256) ||
        !SHA256_RE.test(options.producerReceiptSha256)
      ) {
        return refuse("designation refused: invalid candidate authority evidence");
      }

      // 1. Bundle integrity: reuse the exact verifier /admit uses on its own
      // output. Designation never re-derives bundle schema validity through
      // a second, independently-written check -- that would let the two
      // validators drift apart and reopen exactly the gap #1107's own
      // nested-schema cure closed.
      const verifiedCandidateSha256 = verifyReceipt(options.outputRoot, {
        candidate_id: options.candidateId,
        candidate_sha256: options.candidateSha256,
        producer_receipt_sha256: options.producerReceiptSha256,
      });
      if (
        verifiedCandidateSha256 === null ||
        verifiedCandidateSha256 !== options.candidateSha256
      ) {
        return refuse("designation refused: candidate bundle failed integrity verification");
      }

      // 2. Pull the restart_run_manifest identity out of the now-proven
      // receipt.
      const manifestIdentity = readSelectedManifestIdentity(
        options.outputRoot,
        options.candidateId,
        options.producerReceiptSha256,
      );
      if (manifestIdentity === null) {
        return refuse("designation refused: candidate bundle has no restart_run_manifest role");
      }

      // 3. Read the exact published bytes and re-confirm they match the
      // identity the receipt declared for them (defense in depth on the one
      // file about to be selected).
      const candidateRoot = resolve(options.outputRoot, options.candidateId);
      const manifestFile = resolve(candidateRoot, ...manifestIdentity.relative_path.split("/"));
      if (!isRegularFileUnderUnlinkedRoot(candidateRoot, manifestFile)) {
        return refuse("designation refused: restart_run_manifest path is not a plain file under the candidate");
      }
      let manifestBytes: Buffer;
      try {
        manifestBytes = readFileSync(manifestFile);
      } catch {
        return refuse("designation refused: restart_run_manifest could not be read");
      }
      if (
        manifestBytes.byteLength !== manifestIdentity.bytes ||
        createHash("sha256").update(manifestBytes).digest("hex") !== manifestIdentity.sha256
      ) {
        return refuse("designation refused: restart_run_manifest bytes do not match the verified receipt");
      }

      // 4. Atomic selection: stage in a temp file in the SAME directory as
      // current.json, then rename over it. Verification above is already
      // complete before any write under owned/ happens, so a pre-existing
      // current.json is only ever replaced by a fully-verified rename.
      const ownedDir = join(getConfigHome(), "owned");
      const currentPath = join(ownedDir, "current.json");
      const tempPath = join(ownedDir, `.current.json.${randomBytes(8).toString("hex")}.tmp`);
      try {
        mkdirSync(ownedDir, { recursive: true });
        writeFileSync(tempPath, manifestBytes, { flag: "wx" });
      } catch {
        try {
          unlinkSync(tempPath);
        } catch {
          // nothing was staged; nothing to clean up
        }
        return refuse("designation refused: could not stage the selected manifest");
      }
      try {
        renameSync(tempPath, currentPath);
      } catch {
        try {
          unlinkSync(tempPath);
        } catch {
          // best-effort cleanup of the temp file only; current.json is untouched
        }
        return refuse("designation refused: atomic selection rename failed");
      }

      // 5. Read-back verification.
      let readBack: Buffer;
      try {
        readBack = readFileSync(currentPath);
      } catch {
        return refuse("designation refused: read-back of the selected manifest failed");
      }
      const designatedManifestSha256 = createHash("sha256").update(readBack).digest("hex");
      if (
        readBack.length !== manifestBytes.length ||
        !readBack.equals(manifestBytes) ||
        designatedManifestSha256 !== manifestIdentity.sha256
      ) {
        return refuse("designation refused: read-back verification failed after selection");
      }

      // 6. Designation receipt -- content-addressed, sibling to current.json
      // under owned/, matching #1107's producer-receipts/ convention. The
      // ONLY writes under EMBER_HOME from this command are current.json and
      // this receipt.
      const receiptPayload = {
        schema_version: "ember-owned-designation-receipt-v1",
        candidate_id: options.candidateId,
        candidate_sha256: options.candidateSha256,
        producer_receipt_sha256: options.producerReceiptSha256,
        designated_manifest_sha256: designatedManifestSha256,
        resolved_at: now().toISOString(),
        read_back_verified: true,
      };
      const receiptBytes = Buffer.from(`${canonicalJson(receiptPayload)}\n`, "utf8");
      const receiptSha256 = createHash("sha256").update(receiptBytes).digest("hex");
      const receiptDir = join(ownedDir, "designation-receipts");
      mkdirSync(receiptDir, { recursive: true });
      const receiptPath = join(receiptDir, `${receiptSha256}.json`);
      try {
        writeFileSync(receiptPath, receiptBytes, { flag: "wx" });
      } catch (error) {
        const code = (error as NodeJS.ErrnoException)?.code;
        if (code !== "EEXIST") {
          return refuse("designation refused: could not write the designation receipt");
        }
        // Content-addressed and identical: this exact designation was
        // already receipted (idempotent re-run), not a new failure.
      }

      return {
        type: "message" as const,
        message:
          `designation selected: ${options.candidateId} -> ${designatedManifestSha256}\n` +
          "read_back_verified=true",
      };
    },
  };
}
