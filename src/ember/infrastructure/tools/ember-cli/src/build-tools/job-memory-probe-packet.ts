// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, join, relative } from "node:path";

const PACKET_FILES = [
  "certificate.json",
  "declaration-ledger.jsonl",
  "launch-authority-custody.json",
  "run-spec.json",
] as const;

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} is not an object`);
  }
  return value as JsonObject;
}

function exactInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new Error(`${label} is not an exact safe integer`);
  }
  return value;
}

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

export interface PacketBinding {
  runId: string;
  signedDeltaBytes: number;
  maximumJobMemoryBytes: number;
  operationalReceipt: string;
  hashes: Record<string, string>;
}

export function readPacketBinding(
  repoRoot: string,
  authorityRoot: string,
): PacketBinding {
  if (!isAbsolute(authorityRoot)) throw new Error("authority root must be absolute");
  const fromRepository = relative(repoRoot, authorityRoot);
  if (fromRepository === "" || (!fromRepository.startsWith("..") && !isAbsolute(fromRepository))) {
    throw new Error("authority root must be outside the repository");
  }
  const paths = Object.fromEntries(
    PACKET_FILES.map((name) => [name, join(authorityRoot, name)]),
  ) as Record<(typeof PACKET_FILES)[number], string>;
  for (const name of PACKET_FILES) {
    if (!existsSync(paths[name])) throw new Error(`authority packet lacks ${name}`);
  }
  const runSpec = object(
    JSON.parse(readFileSync(paths["run-spec.json"], "utf8")),
    "run spec",
  );
  if (runSpec["schema_version"] !== "ember-certified-train-run-v1") {
    throw new Error("run spec schema mismatch");
  }
  const runId = runSpec["run_id"];
  if (typeof runId !== "string" || runId.length === 0) throw new Error("run spec lacks run_id");
  const requestedScope = object(runSpec["requested_scope"], "requested scope");
  if (requestedScope["mode"] !== "governed-vertical") {
    throw new Error("run spec is not a job-memory ceiling probe");
  }
  const custodyRoot = requestedScope["custody_root"];
  if (typeof custodyRoot !== "string" || !isAbsolute(custodyRoot)) {
    throw new Error("requested custody root must be absolute");
  }
  const probe = object(runSpec["job_memory_ceiling_probe"], "job-memory probe request");
  const maximumJobMemoryBytes = exactInteger(
    probe["maximum_job_memory_bytes"],
    "maximum_job_memory_bytes",
  );
  const signedDeltaBytes = exactInteger(probe["signed_delta_bytes"], "signed_delta_bytes");
  if (maximumJobMemoryBytes <= 0 || signedDeltaBytes === 0) {
    throw new Error("probe quantities are not positive-maximum/nonzero-delta");
  }
  const operationalReceipt = join(
    custodyRoot,
    runId,
    "ember-lab-certified-launch-operational.json",
  );
  if (existsSync(operationalReceipt)) {
    throw new Error(`no-overwrite operational receipt already exists: ${operationalReceipt}`);
  }
  return {
    runId,
    signedDeltaBytes,
    maximumJobMemoryBytes,
    operationalReceipt,
    hashes: Object.fromEntries(PACKET_FILES.map((name) => [name, sha256(paths[name])])),
  };
}
