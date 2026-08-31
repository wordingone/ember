// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// /admit produces one validated candidate. It never designates, loads, or trains.

import { spawnSync } from "child_process";
import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { isAbsolute, join, parse, relative, resolve, sep } from "path";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";


export interface AdmissionRunResult {
  status: number | null;
  stdout: string;
}

export interface AdmitCommandDeps {
  getConfigHome?: () => string;
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

/** The required-argument shape, declared once. USAGE renders it for the failure path; the
 *  registry entry publishes it as `argumentHint` so the command bar knows a bare `/admit` can
 *  only ever be a usage error and composes instead of dispatching one. */
const ARGUMENT_HINT = "--workspace <path> --descriptor <path> --output-root <path>";
const USAGE = `usage: /admit ${ARGUMENT_HINT}`;
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
    "src/ember/governance/scripts/ember_01_identity/validate_identity.py",
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
const ADMISSION_CONSUMER_ENTRYPOINTS = {
  identity: "src/ember/governance/scripts/ember_01_identity/validate_identity.py",
  restart: "scripts/ember_restart/cli_seat.py",
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

interface FileIdentity {
  relative_path: string;
  sha256: string;
  bytes: number;
}

function parseFileIdentity(value: unknown): FileIdentity | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const identity = value as Record<string, unknown>;
  const relativePath = identity.relative_path;
  const parts = typeof relativePath === "string" ? relativePath.split("/") : [];
  if (
    Object.keys(identity).sort().join(",") !== "bytes,relative_path,sha256" ||
    typeof relativePath !== "string" ||
    relativePath.length === 0 ||
    relativePath.includes("\\") ||
    /[\u0000-\u0020]/u.test(relativePath) ||
    isAbsolute(relativePath) ||
    parts.some((part) => part === "" || part === "." || part === "..") ||
    parts[0]?.includes(":") ||
    parts[0] === "producer-receipts" ||
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

function collectCandidateTree(candidateRoot: string): {
  files: Set<string>;
  directories: Set<string>;
} | null {
  const files = new Set<string>();
  const directories = new Set<string>();
  const walk = (directory: string): boolean => {
    let entries;
    try {
      if (!lstatSync(directory).isDirectory()) return false;
      entries = readdirSync(directory, { withFileTypes: true });
    } catch {
      return false;
    }
    for (const entry of entries) {
      const absolute = join(directory, entry.name);
      const relativePath = relative(candidateRoot, absolute).split(sep).join("/");
      if (entry.isSymbolicLink()) return false;
      if (entry.isDirectory()) {
        directories.add(relativePath);
        if (!walk(absolute)) return false;
      } else if (entry.isFile()) {
        files.add(relativePath);
      } else {
        return false;
      }
    }
    return true;
  };
  return walk(candidateRoot) ? { files, directories } : null;
}

const CANDIDATE_ID_RE = /^[a-z][a-z0-9_-]*$/;
function pathsOverlap(left: string, right: string): boolean {
  const fold = (value: string): string => {
    const absolute = resolve(value).replace(/[\\/]+$/u, "");
    return process.platform === "win32" ? absolute.toLocaleLowerCase("en-US") : absolute;
  };
  const leftPath = fold(left);
  const rightPath = fold(right);
  const boundary = sep;
  return leftPath === rightPath ||
    leftPath.startsWith(`${rightPath}${boundary}`) ||
    rightPath.startsWith(`${leftPath}${boundary}`);
}
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
  const sourceIdentities = identities as Record<string, unknown>;
  const descriptorIdentity = parseFileIdentity(sourceIdentities.descriptor);
  const sourceRoles = sourceIdentities.roles;
  if (
    Object.keys(sourceIdentities).sort().join(",") !== "descriptor,roles" ||
    descriptorIdentity === null ||
    typeof sourceRoles !== "object" ||
    sourceRoles === null ||
    Array.isArray(sourceRoles) ||
    canonicalJson(outputIdentities) !== canonicalJson(sourceRoles)
  ) {
    return null;
  }
  const roleIdentities = outputIdentities as Record<string, unknown>;
  const parsedRoles = new Map<string, FileIdentity>();
  if (
    Object.keys(roleIdentities).length === 0 ||
    Object.entries(roleIdentities).some(([role, identity]) => {
      const parsed = parseFileIdentity(identity);
      if (parsed !== null) parsedRoles.set(role, parsed);
      return (
        role.length === 0 ||
        parsed === null
      );
    }) ||
    new Set([...parsedRoles.values()].map((identity) => identity.relative_path)).size
      !== parsedRoles.size ||
    createHash("sha256")
      .update(`${canonicalJson({ output_identities: roleIdentities })}\n`)
      .digest("hex") !== digestJoin
  ) {
    return null;
  }
  const candidateRoot = resolve(outputRoot, candidateId);
  const expectedFiles = new Set<string>([
    `producer-receipts/${receiptSha256}.json`,
  ]);
  const expectedDirectories = new Set<string>(["producer-receipts"]);
  for (const identity of parsedRoles.values()) {
    const file = resolve(candidateRoot, ...identity.relative_path.split("/"));
    if (!isRegularFileUnderUnlinkedRoot(candidateRoot, file)) return null;
    let bytes: Uint8Array;
    try {
      bytes = readFileSync(file);
    } catch {
      return null;
    }
    if (
      bytes.byteLength !== identity.bytes ||
      createHash("sha256").update(bytes).digest("hex") !== identity.sha256
    ) {
      return null;
    }
    expectedFiles.add(identity.relative_path);
    let parent = identity.relative_path.split("/").slice(0, -1);
    while (parent.length > 0) {
      expectedDirectories.add(parent.join("/"));
      parent = parent.slice(0, -1);
    }
  }
  const tree = collectCandidateTree(candidateRoot);
  if (
    tree === null ||
    canonicalJson([...tree.files].sort()) !== canonicalJson([...expectedFiles].sort()) ||
    canonicalJson([...tree.directories].sort()) !==
      canonicalJson([...expectedDirectories].sort())
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
      const closure = record.validator_closure;
      if (typeof closure !== "object" || closure === null || Array.isArray(closure)) {
        return true;
      }
      const parsedClosure = new Map<string, FileIdentity>();
      if (
        Object.entries(closure).length === 0 ||
        Object.entries(closure).some(([relativePath, identity]) => {
          const parsed = parseFileIdentity(identity);
          if (parsed !== null) parsedClosure.set(relativePath, parsed);
          return parsed === null || parsed.relative_path !== relativePath;
        })
      ) {
        return true;
      }
      const entrypoint = parsedClosure.get(ADMISSION_CONSUMER_ENTRYPOINTS[name]);
      return (
        canonicalJson(record.command) !== canonicalJson(ADMISSION_CONSUMER_COMMANDS[name]) ||
        Object.keys(record).sort().join(",") !==
          "accepted,command,returncode,stdout_sha256,validator_closure,validator_sha256" ||
        record.accepted !== true ||
        typeof record.stdout_sha256 !== "string" ||
        !SHA256_RE.test(record.stdout_sha256) ||
        record.returncode !== 0 ||
        typeof record.validator_sha256 !== "string" ||
        !SHA256_RE.test(record.validator_sha256) ||
        entrypoint === undefined ||
        entrypoint.sha256 !== record.validator_sha256
      );
    })
  ) {
    return null;
  }
  const candidateSha256 = createHash("sha256").update(
    canonicalJson({
      producer_receipt_sha256: receiptSha256,
      descriptor_identity: descriptorIdentity,
      output_identities: roleIdentities,
    }),
  ).digest("hex");
  return candidateSha256 === claimedCandidateSha256 ? candidateSha256 : null;
}

export function createAdmitCommand(deps: AdmitCommandDeps = {}): RegistryCommand {
  const getConfigHome = deps.getConfigHome ?? getEmberConfigHomeDir;
  const runProducer = deps.runProducer ?? defaultRunProducer;
  const pythonExecutable = deps.pythonExecutable ?? "python";
  const verifyReceipt = deps.verifyReceipt ?? verifyAdmissionProducerReceipt;
  return {
    name: "admit",
    description:
      "Construct and validate an owned-admission candidate from existing evidence bytes without selecting or loading it",
    argumentHint: ARGUMENT_HINT,
    isEnabled: () => true,
    async execute(args: string, context: CommandContext) {
      const options = parseOptions(args);
      if (options === null) {
        return { type: "message" as const, message: USAGE, exitCode: 2 };
      }
      const currentSelection = join(
        getConfigHome(),
        "owned",
        "current.json",
      );
      if (pathsOverlap(options.outputRoot, currentSelection)) {
        return {
          type: "message" as const,
          message: "admission output overlaps live owned selection",
          exitCode: 2,
        };
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
