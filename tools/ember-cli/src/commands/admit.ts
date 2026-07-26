// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// /admit produces one validated candidate. It never designates, loads, or trains.

import { spawnSync } from "child_process";
import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { isAbsolute, join, parse, relative, resolve, sep } from "path";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";


export interface AdmissionRunResult {
  status: number | null;
  stdout: string;
}

export interface AdmitCommandDeps {
  producerPath?: string;
  pythonExecutable?: string;
  runProducer?: (
    executable: string,
    args: string[],
    cwd: string,
  ) => AdmissionRunResult;
  verifyReceipt?: (
    outputRoot: string,
    payload: Record<string, unknown>,
  ) => string | null;
}

interface AdmitOptions {
  workspace: string;
  descriptor: string;
  outputRoot: string;
}

const USAGE =
  "usage: /admit --workspace <path> --descriptor <path> --output-root <path>";
const RECEIPT_KEYS = [
  "benchmark_claim",
  "candidate_id",
  "capability_claim",
  "claim_boundary",
  "consumers",
  "cross_consumer_digest_join_sha256",
  "loaded",
  "output_identities",
  "schema_version",
  "selected",
  "source_identities",
  "training_claim",
  "training_started",
].sort().join(",");
const CLAIM_BOUNDARY = [
  "candidate_produced",
  "identity_consumer_accepted",
  "restart_consumer_accepted",
];
export const ADMISSION_CONSUMER_COMMANDS = {
  identity: [
    "python",
    "scripts/ember_01_identity/validate_identity.py",
    "role:identity_manifest",
    "--checkpoint",
    "role:checkpoint",
    "--tensor-hashes",
    "role:tensor_hashes",
    "--tensor-manifest",
    "role:tensor_manifest",
    "--artifact-bundle",
    "role:artifact_bundle",
    "--receipt-bundle",
    "role:receipt_bundle",
    "--trusted-verifier-registry",
    "role:identity_trusted_verifier_registry",
    "--require-resolved",
  ],
  restart: [
    "python",
    "scripts/ember_restart/cli_seat.py",
    "role:restart_run_manifest",
    "--trusted-verifier-registry",
    "role:restart_trusted_verifier_registry",
  ],
} as const;
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
const SHA256_RE = /^[0-9a-f]{64}$/;

const CANDIDATE_ID_RE = /^[a-z][a-z0-9_.-]*$/;
function parseOptions(args: string): AdmitOptions | null {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  const values = new Map<string, string>();
  const allowed = new Set(["--workspace", "--descriptor", "--output-root"]);
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
  if (parts.length !== 6) return null;
  const workspace = values.get("--workspace");
  const descriptor = values.get("--descriptor");
  const outputRoot = values.get("--output-root");
  return workspace && descriptor && outputRoot
    ? { workspace, descriptor, outputRoot }
    : null;
}

function defaultRunProducer(
  executable: string,
  args: string[],
  cwd: string,
): AdmissionRunResult {
  const result = spawnSync(executable, args, {
    cwd,
    encoding: "utf8",
    shell: false,
    timeout: 120_000,
    windowsHide: true,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
  };
}


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

export function verifyAdmissionProducerReceipt(
  outputRoot: string,
  payload: Record<string, unknown>,
): string | null {
  const candidateId = payload.candidate_id;
  const receiptSha256 = payload.producer_receipt_sha256;
  const claimedCandidateSha256 = payload.candidate_sha256;
  if (
    typeof candidateId !== "string" ||
    !CANDIDATE_ID_RE.test(candidateId) ||
    typeof receiptSha256 !== "string" ||
    !SHA256_RE.test(receiptSha256) ||
    typeof claimedCandidateSha256 !== "string" ||
    !SHA256_RE.test(claimedCandidateSha256)
  ) {
    return null;
  }
  const receiptPath = resolve(
    outputRoot,
    candidateId,
    "producer-receipts",
    `${receiptSha256}.json`,
  );
  if (!isRegularFileUnderUnlinkedRoot(outputRoot, receiptPath)) {
    return null;
  }
  let receiptBytes: Uint8Array;
  try {
    receiptBytes = readFileSync(receiptPath);
  } catch {
    return null;
  }
  if (createHash("sha256").update(receiptBytes).digest("hex") !== receiptSha256) {
    return null;
  }
  let receipt: Record<string, unknown>;
  try {
    const parsed = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(receiptBytes),
    );
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    receipt = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  if (
    Buffer.from(`${canonicalJson(receipt)}\n`, "utf8").compare(receiptBytes) !== 0 ||
    Object.keys(receipt).sort().join(",") !== RECEIPT_KEYS
  ) {
    return null;
  }
  const identities = receipt.source_identities;
  const outputIdentities = receipt.output_identities;
  const consumers = receipt.consumers;
  const digestJoin = receipt.cross_consumer_digest_join_sha256;
  if (
    receipt.schema_version !== "ember-owned-admission-producer-receipt-v1" ||
    receipt.candidate_id !== candidateId ||
    receipt.selected !== false ||
    receipt.loaded !== false ||
    receipt.training_started !== false ||
    receipt.training_claim !== false ||
    receipt.benchmark_claim !== false ||
    receipt.capability_claim !== false ||
    canonicalJson(receipt.claim_boundary) !== canonicalJson(CLAIM_BOUNDARY) ||
    typeof identities !== "object" ||
    identities === null ||
    Array.isArray(identities) ||
    typeof outputIdentities !== "object" ||
    outputIdentities === null ||
    Array.isArray(outputIdentities) ||
    typeof consumers !== "object" ||
    consumers === null ||
    Array.isArray(consumers) ||
    typeof digestJoin !== "string" ||
    !SHA256_RE.test(digestJoin)
  ) {
    return null;
  }
  const consumerRows = consumers as Record<string, unknown>;
  const roleIdentities = identities as Record<string, unknown>;
  if (
    Object.keys(roleIdentities).length === 0 ||
    Object.entries(roleIdentities).some(
      ([role, digest]) =>
        role.length === 0 ||
        typeof digest !== "string" ||
        !SHA256_RE.test(digest),
    ) ||
    canonicalJson(outputIdentities) !== canonicalJson(roleIdentities) ||
    createHash("sha256")
      .update(`${canonicalJson({ role_sha256: roleIdentities })}\n`)
      .digest("hex") !== digestJoin
  ) {
    return null;
  }
  if (
    Object.keys(consumerRows).sort().join(",") !== "identity,restart" ||
    (["identity", "restart"] as const).some((name) => {
      const row = consumerRows[name];
      if (typeof row !== "object" || row === null || Array.isArray(row)) {
        return true;
      }
      const record = row as Record<string, unknown>;
      return (
        canonicalJson(record.command) !== canonicalJson(ADMISSION_CONSUMER_COMMANDS[name]) ||
        Object.keys(record).sort().join(",") !==
          "accepted,command,returncode,stdout_sha256,validator_sha256" ||
        record.accepted !== true ||
        typeof record.stdout_sha256 !== "string" ||
        !SHA256_RE.test(record.stdout_sha256) ||
        record.returncode !== 0 ||
        typeof record.validator_sha256 !== "string" ||
        !SHA256_RE.test(record.validator_sha256)
      );
    })
  ) {
    return null;
  }
  const candidateSha256 = createHash("sha256").update(
    canonicalJson({
      producer_receipt_sha256: receiptSha256,
      role_sha256: identities,
    }),
  ).digest("hex");
  return candidateSha256 === claimedCandidateSha256 ? candidateSha256 : null;
}

export function createAdmitCommand(deps: AdmitCommandDeps = {}): RegistryCommand {
  const runProducer = deps.runProducer ?? defaultRunProducer;
  const pythonExecutable = deps.pythonExecutable ?? "python";
  const verifyReceipt = deps.verifyReceipt ?? verifyAdmissionProducerReceipt;
  return {
    name: "admit",
    description:
      "Construct and validate an owned-admission candidate from existing evidence bytes without selecting or loading it",
    isEnabled: () => true,
    async execute(args: string, context: CommandContext) {
      const options = parseOptions(args);
      if (options === null) {
        return { type: "message" as const, message: USAGE, exitCode: 2 };
      }
      const sourceRoot = resolveEmberSourceRootOrCwd(
        { startDir: context.cwd },
        "[ember] /admit",
      );
      const producerPath =
        deps.producerPath ??
        join(sourceRoot, "scripts", "ember_admission", "produce_candidate.py");
      const result = runProducer(
        pythonExecutable,
        [
          producerPath,
          "--workspace", options.workspace,
          "--descriptor", options.descriptor,
          "--output-root", options.outputRoot,
        ],
        sourceRoot,
      );
      if (result.status !== 0) {
        return {
          type: "message" as const,
          message: "admission candidate refused",
          exitCode: result.status ?? 2,
        };
      }
      let payload: unknown;
      try {
        payload = JSON.parse(result.stdout);
      } catch {
        payload = null;
      }
      if (
        typeof payload !== "object" ||
        payload === null ||
        !("ok" in payload) ||
        payload.ok !== true ||
        !("candidate_id" in payload) ||
        typeof payload.candidate_id !== "string" ||
        !CANDIDATE_ID_RE.test(payload.candidate_id) ||
        !("candidate_sha256" in payload) ||
        typeof payload.candidate_sha256 !== "string" ||
        !SHA256_RE.test(payload.candidate_sha256) ||
        !("producer_receipt_sha256" in payload) ||
        typeof payload.producer_receipt_sha256 !== "string" ||
        !SHA256_RE.test(payload.producer_receipt_sha256) ||
        !("selected" in payload) ||
        payload.selected !== false ||
        !("loaded" in payload) ||
        payload.loaded !== false ||
        !("training_started" in payload) ||
        payload.training_started !== false
      ) {
        return {
          type: "message" as const,
          message: "admission producer returned invalid authority evidence",
          exitCode: 2,
        };
      }
      const verifiedCandidateSha256 = verifyReceipt(
        options.outputRoot,
        payload as Record<string, unknown>,
      );
      if (verifiedCandidateSha256 !== payload.candidate_sha256) {
        return {
          type: "message" as const,
          message: "admission producer returned invalid authority evidence",
          exitCode: 2,
        };
      }
      return {
        type: "message" as const,
        message:
          `admission candidate produced: ${payload.candidate_sha256}\n` +
          "selected=false loaded=false training_started=false",
      };
    },
  };
}
