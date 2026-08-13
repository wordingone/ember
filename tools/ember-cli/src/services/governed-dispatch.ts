// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Closed, model-free Ember CLI transport for one governed_vertical manifest.
// Ember Lab remains the sole process launcher, resource authority, and receipt producer.

import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { isAbsolute, posix, relative, resolve, win32 } from "node:path";
import {
  callEmberLab as callResidentEmberLab,
  configuredEmberLabPipe,
  type EmberLabRequestOptions,
} from "./ember-lab-rpc.ts";

const MANIFEST_FIELDS = [
  "args", "bindings", "custody_root", "cpu_pacing_class", "env", "expires_at_ms", "job_id",
  "maximum_job_memory_bytes", "minimum_free_vram_bytes", "not_before_ms",
  "preflight_receipt", "program", "required_available_maximum_commit_bytes",
  "resource_lease", "schema_version", "simulated_peak_commit_bytes", "source_commit",
  "storage_reserves", "window_contract", "workload_profile",
].sort();

// Legal snake_case spellings for the two required closed-choice dispatch-manifest fields
// (runtime/ember-lab/src/lib.rs DispatchCpuPacingClass / DispatchWindowContract). Kept here
// rather than imported so this transport has no compile-time dependency on the Rust crate;
// keep in sync by hand if the enums ever grow a variant.
const CPU_PACING_CLASS_LEGAL_VALUES = ["unpaced", "governed"] as const;
const WINDOW_CONTRACT_LEGAL_VALUES = ["headless_no_windows", "cockpit_hosted"] as const;

/**
 * Require `field` to be present on `manifest` and hold one of `legalValues`, throwing a
 * refusal that names the specific missing/invalid field and enumerates its legal values
 * (e.g. "governed dispatch cpu_pacing_class: missing required field (legal values: unpaced,
 * governed)") rather than a bare "fields are not closed" error. Returns the validated value.
 */
function requireClosedChoiceField(
  manifest: Record<string, unknown>, field: string, legalValues: readonly string[],
): string {
  const legal = legalValues.join(", ");
  if (!(field in manifest)) {
    throw new Error(`governed dispatch ${field}: missing required field (legal values: ${legal})`);
  }
  const actual = manifest[field];
  if (typeof actual !== "string" || !legalValues.includes(actual)) {
    throw new Error(
      `governed dispatch ${field}: invalid value ${JSON.stringify(actual)} (legal values: ${legal})`,
    );
  }
  return actual;
}

const PROFILE_FIELDS = [
  "cpu_rate_percent", "pinned_host_producers", "profile_id",
  "requires_ui_responsiveness",
].sort();

type CallEmberLab = (
  options: EmberLabRequestOptions,
) => Promise<Record<string, unknown>>;

export interface GovernedDispatchOptions {
  manifestPath: string;
  expectedSourceCommit: string;
  pipeName: string;
  callEmberLab?: CallEmberLab;
}

export interface GovernedDispatchResult {
  pid: number;
  preflight_receipt_path: string;
  preflight_receipt_sha256: string;
  manifest_sha256: string;
}

export function parseGovernedDispatchArgs(args: string[]): string {
  if (args.length !== 2 || args[0] !== "--manifest" || !isAbsolute(args[1] ?? "")) {
    throw new Error("usage: ember dispatch-governed --manifest <absolute-path>");
  }
  return args[1]!;
}

export function isStrictContainedRelative(inside: string): boolean {
  return inside !== ""
    && inside !== ".."
    && !inside.startsWith("..\\")
    && !inside.startsWith("../")
    && !isAbsolute(inside)
    && !win32.isAbsolute(inside)
    && !posix.isAbsolute(inside);
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`governed dispatch ${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function closedFields(value: Record<string, unknown>, expected: string[], label: string): void {
  const actual = Object.keys(value).sort();
  if (actual.length !== expected.length || actual.some((field, index) => field !== expected[index])) {
    throw new Error(`governed dispatch ${label} fields are not closed`);
  }
}

function decodeManifest(bytes: Buffer): Record<string, unknown> {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("governed dispatch manifest is not valid UTF-8");
  }
  try {
    return object(JSON.parse(text), "manifest");
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("governed dispatch")) throw error;
    throw new Error("governed dispatch manifest is not JSON");
  }
}

function validateManifest(manifest: Record<string, unknown>, expectedSourceCommit: string): string {
  if (!/^[0-9a-f]{40}$/.test(expectedSourceCommit)) {
    throw new Error("governed dispatch source commit trust root is invalid");
  }
  // Named-field checks for the two closed-choice fields run before the generic closed-field
  // check so a missing/invalid value gets a self-describing refusal instead of the generic
  // "fields are not closed" message.
  const cpuPacingClass = requireClosedChoiceField(manifest, "cpu_pacing_class", CPU_PACING_CLASS_LEGAL_VALUES);
  const windowContract = requireClosedChoiceField(manifest, "window_contract", WINDOW_CONTRACT_LEGAL_VALUES);
  closedFields(manifest, MANIFEST_FIELDS, "manifest");
  if (manifest["schema_version"] !== "ember-lab-dispatch-manifest-v3") {
    throw new Error("governed dispatch manifest schema is invalid");
  }
  if (manifest["source_commit"] !== expectedSourceCommit) {
    throw new Error("governed dispatch source commit does not match the Ember CLI");
  }
  if (manifest["resource_lease"] !== "gpu-q2-actual-update") {
    throw new Error("governed dispatch resource lease is invalid");
  }
  // governed_vertical is not CPU-paced and presents no window today (truth-declared, not
  // aspirational -- see runtime/ember-lab/scripts/c8_prelaunch/issue675/q2_dispatch_manifest.py).
  if (cpuPacingClass !== "unpaced") {
    throw new Error("governed dispatch cpu_pacing_class does not match the governed_vertical authority");
  }
  if (windowContract !== "headless_no_windows") {
    throw new Error("governed dispatch window_contract does not match the governed_vertical authority");
  }
  const profile = object(manifest["workload_profile"], "workload profile");
  closedFields(profile, PROFILE_FIELDS, "workload profile");
  if (
    profile["profile_id"] !== "governed_vertical"
    || profile["requires_ui_responsiveness"] !== false
    || profile["cpu_rate_percent"] !== 80
    || !Array.isArray(profile["pinned_host_producers"])
    || profile["pinned_host_producers"].length === 0
  ) {
    throw new Error("governed dispatch workload profile is invalid");
  }
  const args = manifest["args"];
  if (!Array.isArray(args) || args.length < 2 || args[1] !== "governed-vertical") {
    throw new Error("governed dispatch producer argv is invalid");
  }
  const custodyRoot = manifest["custody_root"];
  if (typeof custodyRoot !== "string" || !isAbsolute(custodyRoot)) {
    throw new Error("governed dispatch custody root must be absolute");
  }
  return resolve(custodyRoot);
}

function canonicalWin32Spelling(value: string): string {
  let spelling = value;
  if (/^\\\\\?\\[A-Za-z]:[\\/]/.test(spelling)) {
    spelling = spelling.slice(4);
  } else if (/^\\\\\?\\UNC\\/i.test(spelling)) {
    spelling = "\\\\" + spelling.slice(8);
  }
  return win32.normalize(spelling).toLowerCase();
}

export function sameCanonicalPath(
  left: string,
  right: string,
  platform = process.platform,
): boolean {
  return platform === "win32"
    ? canonicalWin32Spelling(left) === canonicalWin32Spelling(right)
    : left === right;
}

async function requireCanonicalPath(path: string, label: string): Promise<string> {
  const lexical = resolve(path);
  let canonical: string;
  try {
    canonical = await realpath(lexical);
  } catch {
    throw new Error(`governed dispatch ${label} is unreadable`);
  }
  if (!sameCanonicalPath(lexical, canonical)) {
    throw new Error(`governed dispatch ${label} contains a symlink or reparse component`);
  }
  return canonical;
}

async function verifyReceipt(
  result: Record<string, unknown>, custodyRoot: string,
): Promise<{ pid: number; path: string; sha256: string }> {
  const pid = result["pid"];
  const path = result["preflight_receipt_path"];
  const sha256 = result["preflight_receipt_sha256"];
  if (!Number.isSafeInteger(pid) || (pid as number) < 1) {
    throw new Error("governed dispatch result lacks a positive pid");
  }
  if (
    typeof path !== "string" || !isAbsolute(path)
    || typeof sha256 !== "string" || !/^[0-9a-f]{64}$/.test(sha256)
  ) {
    throw new Error("governed dispatch result lacks preflight receipt custody");
  }
  const receiptPath = await requireCanonicalPath(path, "preflight receipt");
  const inside = relative(custodyRoot, receiptPath);
  if (!isStrictContainedRelative(inside)) {
    throw new Error("governed dispatch preflight receipt escapes custody");
  }
  let bytes: Buffer;
  try {
    bytes = await readFile(receiptPath);
  } catch {
    throw new Error("governed dispatch preflight receipt is unreadable");
  }
  if (createHash("sha256").update(bytes).digest("hex") !== sha256) {
    throw new Error("governed dispatch preflight receipt hash does not match custody bytes");
  }
  return { pid: pid as number, path: receiptPath, sha256 };
}

export async function runGovernedDispatch(
  options: GovernedDispatchOptions,
): Promise<GovernedDispatchResult> {
  if (!isAbsolute(options.manifestPath)) {
    throw new Error("governed dispatch manifest path must be absolute");
  }
  const pipeName = configuredEmberLabPipe({ EMBER_LAB_PIPE: options.pipeName });
  const manifestBytes = await readFile(options.manifestPath);
  const manifest = decodeManifest(manifestBytes);
  const custodyRoot = await requireCanonicalPath(
    validateManifest(manifest, options.expectedSourceCommit),
    "custody root",
  );
  const manifestSha256 = createHash("sha256").update(manifestBytes).digest("hex");
  const result = await (options.callEmberLab ?? callResidentEmberLab)({
    pipeName,
    method: "dispatch_manifest",
    params: {
      manifest_utf8: new TextDecoder("utf-8", { fatal: true }).decode(manifestBytes),
      manifest_sha256: manifestSha256,
    },
  });
  const receipt = await verifyReceipt(result, custodyRoot);
  return {
    pid: receipt.pid,
    preflight_receipt_path: receipt.path,
    preflight_receipt_sha256: receipt.sha256,
    manifest_sha256: manifestSha256,
  };
}
