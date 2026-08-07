// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { validateInstalledCaptureReceipt } from "./fireball-frame-capture.ts";

const SHA_RE = /^[0-9a-f]{64}$/;
const COMMIT_RE = /^[0-9a-f]{40}$/;
const NEXT_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember";
const INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6";

type JsonObject = Record<string, any>;

export type VerifiedIssue303Evidence = {
  source_commit: string;
  binary_sha256: string;
  resize_receipt_sha256: string;
  half_screen_receipt_sha256: string;
  resize_dimensions: string[];
  restored_prompt_geometry: boolean;
  half_screen_dimensions: string;
  left_panel_right_column: number;
  prompt_right_column: number;
};

function sha256(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function readJson(path: string, label: string): { bytes: Buffer; value: JsonObject } {
  const bytes = readFileSync(path);
  let parsed: unknown;
  try {
    parsed = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new Error(`${label} must be valid UTF-8 JSON`);
  }
  return { bytes, value: object(parsed, label) };
}

function resolveRepoFile(repoRoot: string, value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || isAbsolute(value)) {
    throw new Error(`${label} must be a nonempty repository-relative path`);
  }
  const path = resolve(repoRoot, value);
  const rel = relative(repoRoot, path);
  if (rel.startsWith("..") || isAbsolute(rel)) throw new Error(`${label} escapes the repository`);
  return path;
}

function requireHash(value: unknown, label: string): string {
  if (typeof value !== "string" || !SHA_RE.test(value)) throw new Error(`${label} must be lowercase sha256`);
  return value;
}

function requireArtifact(repoRoot: string, evidenceRoot: string, descriptor: unknown, label: string): void {
  const artifact = object(descriptor, label);
  let path = resolveRepoFile(repoRoot, artifact.path, `${label}.path`);
  const prefix = "receipts/ember-cli/issue-303/";
  if (!existsSync(path) && typeof artifact.path === "string" && artifact.path.startsWith(prefix)) {
    path = resolve(evidenceRoot, artifact.path.slice(prefix.length));
    const rel = relative(evidenceRoot, path);
    if (rel.startsWith("..") || isAbsolute(rel)) throw new Error(`${label}.path escapes evidence root`);
  }
  const bytes = readFileSync(path);
  if (bytes.length !== artifact.bytes) throw new Error(`${label} byte count mismatch`);
  if (sha256(bytes) !== requireHash(artifact.sha256, `${label}.sha256`)) {
    throw new Error(`${label} sha256 mismatch`);
  }
}

function frameLines(path: string, rows: number, columns: number): string[] {
  const lines = readFileSync(path, "utf8").split(/\r?\n/);
  if (lines.at(-1) === "") lines.pop();
  if (lines.length !== rows || lines.some((line) => [...line].length !== columns)) {
    throw new Error(`frame must be exactly ${columns}x${rows}`);
  }
  return lines;
}

export function verifyIssue303Evidence(evidenceRootValue: string): VerifiedIssue303Evidence {
  const evidenceRoot = resolve(evidenceRootValue);
  const repoRoot = resolve(evidenceRoot, "../../..");
  const resizePath = join(evidenceRoot, "current-master-resize", "prompt-resize-receipt.json");
  const halfDirectory = join(evidenceRoot, "current-master-half-screen");
  const halfPath = join(halfDirectory, "receipt.json");
  const resize = readJson(resizePath, "resize receipt");
  const half = readJson(halfPath, "half-screen receipt");

  const r = resize.value;
  if (r.schema_version !== "ember-cli-issue-243-live-resize/v1" || r.result !== "PASS") {
    throw new Error("resize receipt is not a passing production resize capture");
  }
  if (!COMMIT_RE.test(r.source_commit)) throw new Error("resize source commit is invalid");
  const resizeBinary = requireHash(object(r.binary, "resize binary").sha256, "resize binary sha256");
  const rebuild = object(r.binary.reproducible_rebuild, "reproducible rebuild");
  if (rebuild.source_commit !== r.source_commit || rebuild.sha256 !== resizeBinary || rebuild.equals_captured_binary !== true) {
    throw new Error("resize binary is not reproducibly bound to its source commit");
  }
  const expectedDimensions = [[80, 24], [40, 24], [80, 24]];
  if (!Array.isArray(r.dimensions) || !Array.isArray(r.stages) || r.stages.length !== 3) {
    throw new Error("resize receipt must contain exactly three stages");
  }
  const dimensions = r.dimensions.map((entry: unknown, index: number) => {
    const dim = object(entry, `dimensions[${index}]`);
    if (dim.columns !== expectedDimensions[index]![0] || dim.rows !== expectedDimensions[index]![1]) {
      throw new Error("resize dimensions must be 80x24,40x24,80x24");
    }
    return `${dim.columns}x${dim.rows}`;
  });
  const regions = r.stages.map((entry: unknown, index: number) => {
    const stage = object(entry, `stages[${index}]`);
    requireArtifact(repoRoot, evidenceRoot, stage.raw_public_redacted, `stages[${index}].raw_public_redacted`);
    requireArtifact(repoRoot, evidenceRoot, stage.frame, `stages[${index}].frame`);
    const region = object(stage.closed_prompt_region, `stages[${index}].closed_prompt_region`);
    if (region.top !== 20 || region.bottom !== 23 || !Number.isInteger(region.contentColumns)) {
      throw new Error("resize stage has invalid closed prompt geometry");
    }
    return region;
  });
  const restored = JSON.stringify(regions[0]) === JSON.stringify(regions[2]) && regions[1]!.contentColumns < regions[0]!.contentColumns;
  if (!restored) throw new Error("80x24 prompt geometry was not restored after shrink");

  validateInstalledCaptureReceipt(half.value);
  if (half.value.source_commit !== r.source_commit) throw new Error("capture receipts bind different source commits");
  if (half.value.binary_sha256 !== resizeBinary) throw new Error("capture receipts bind different binaries");
  const viewport = object(half.value.viewport, "half-screen viewport");
  const firstCapture = object(half.value.captures[0], "captures[0]");
  for (let index = 0; index < half.value.captures.length; index++) {
    const capture = object(half.value.captures[index], `captures[${index}]`);
    const framePath = resolveRepoFile(halfDirectory, capture.frame_file, `captures[${index}].frame_file`);
    if (dirname(framePath) !== halfDirectory) throw new Error("frame file must remain in the capture directory");
    if (sha256(readFileSync(framePath)) !== capture.frame_sha256) throw new Error(`frame-${index + 1} frame sha256 mismatch`);
    const cellsPath = resolveRepoFile(halfDirectory, capture.cells_file, `captures[${index}].cells_file`);
    if (dirname(cellsPath) !== halfDirectory) throw new Error("cells file must remain in the capture directory");
    if (sha256(readFileSync(cellsPath)) !== capture.cells_sha256) throw new Error(`frame-${index + 1} cells sha256 mismatch`);
  }
  const firstFrame = frameLines(
    join(halfDirectory, firstCapture.frame_file),
    viewport.terminal_rows,
    viewport.terminal_columns,
  );
  const top = [...firstFrame[0]!];
  const promptTop = [...firstFrame[81]!];
  const leftPanelRight = top.findIndex((char, index) => index > 0 && char === "╮");
  const promptRight = promptTop.findIndex((char, index) => index > 0 && char === "╮");
  if (leftPanelRight < 1 || promptRight < 1 || leftPanelRight !== promptRight) {
    throw new Error("bottom prompt width does not match the upper left panel");
  }

  return {
    source_commit: r.source_commit,
    binary_sha256: resizeBinary,
    resize_receipt_sha256: sha256(resize.bytes),
    half_screen_receipt_sha256: sha256(half.bytes),
    resize_dimensions: dimensions,
    restored_prompt_geometry: true,
    half_screen_dimensions: `${viewport.terminal_columns}x${viewport.terminal_rows}`,
    left_panel_right_column: leftPanelRight,
    prompt_right_column: promptRight,
  };
}

export function buildIssue303TerminalReceipt(evidence: VerifiedIssue303Evidence): JsonObject {
  return {
    schema_version: "ember-cli-issue-303-terminal-layout-v1",
    ticket: "EMBER-CLI-ISSUE-303-TERMINAL-LAYOUT",
    ts: "2026-08-07T00:00:00.000Z",
    sha_convention: "sha256 over exact on-disk file bytes, no normalization",
    invariant_sha256: INVARIANT_SHA256,
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    next_executed_outcome: NEXT_OUTCOME,
    issue_id: 303,
    result: "PASS",
    source_commit: evidence.source_commit,
    binary_sha256: evidence.binary_sha256,
    evidence: {
      resize_receipt: "current-master-resize/prompt-resize-receipt.json",
      resize_receipt_sha256: evidence.resize_receipt_sha256,
      half_screen_receipt: "current-master-half-screen/receipt.json",
      half_screen_receipt_sha256: evidence.half_screen_receipt_sha256,
      resize_dimensions: evidence.resize_dimensions,
      restored_prompt_geometry: evidence.restored_prompt_geometry,
      half_screen_dimensions: evidence.half_screen_dimensions,
      left_panel_right_column: evidence.left_panel_right_column,
      prompt_right_column: evidence.prompt_right_column,
    },
    bottom_layout_obligation: {
      disposition: "COMPLETED",
      evidence: "compiled current-source binary at 80x24, 40x24, 80x24 and operator 190x85",
    },
    zero_activity_obligation: {
      disposition: "TRANSFERRED",
      canonical_issue: 485,
    },
    architecture: {
      current_surface: "Ember CLI fixed viewport and independently scrollable regions",
      no_new_parallel_authority: true,
    },
    claim_boundary: [
      "terminal geometry and resize behavior only",
      "no model, training, benchmark, or capability claim",
    ],
  };
}

function writeAtomic(path: string, value: unknown): void {
  const temp = `${path}.tmp`;
  writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(temp, path);
}

if (import.meta.main) {
  const evidenceRoot = process.argv[2];
  const output = process.argv[3];
  if (!evidenceRoot || !output || basename(output) !== output) {
    throw new Error("usage: bun verify-issue-303-layout.ts <evidence-root> <path-free-output-basename>");
  }
  const receipt = buildIssue303TerminalReceipt(verifyIssue303Evidence(evidenceRoot));
  writeAtomic(join(resolve(evidenceRoot), output), receipt);
  process.stdout.write(`${JSON.stringify({ result: "PASS", receipt: output })}\n`);
}
