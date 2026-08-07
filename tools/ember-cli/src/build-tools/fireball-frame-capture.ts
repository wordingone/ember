// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import {
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";

const { Terminal } = xtermHeadless;
const COLS = 190;
const ROWS = 85;
const MIN_CAPTURE_GAP_MS = 2_000;
const CAPTURE_GAP_MS = 2_200;
const TIMEOUT_MS = 20_000;
const SHA_RE = /^[0-9a-f]{64}$/;
const COMMIT_RE = /^[0-9a-f]{40}$/;
const NEXT_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember";

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function exactKeys(value: JsonObject, expected: string[], label: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
    throw new Error(`${label} keys must be exactly ${wanted.join(",")}`);
  }
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${label} must be a nonempty string`);
  return value;
}

function integer(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) throw new Error(`${label} must be an integer`);
  return value;
}

function sha(value: unknown, label: string): string {
  const digest = string(value, label);
  if (!SHA_RE.test(digest)) throw new Error(`${label} must be lowercase sha256`);
  return digest;
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value as JsonObject).sort().map((key) =>
      `${JSON.stringify(key)}:${canonical((value as JsonObject)[key])}`
    ).join(",")}}`;
  }
  return JSON.stringify(value);
}

function validateCell(value: unknown, label: string, includeStyle: boolean): JsonObject {
  const cell = object(value, label);
  exactKeys(cell, includeStyle ? ["row", "col", "char", "fg", "bg"] : ["row", "col", "char"], label);
  const row = integer(cell.row, `${label}.row`);
  const col = integer(cell.col, `${label}.col`);
  if (row < 0 || col < 0) throw new Error(`${label} coordinates must be nonnegative`);
  const char = string(cell.char, `${label}.char`);
  if (char !== "▀" && char !== "▄") throw new Error(`${label}.char must be a fireball half-block`);
  if (includeStyle) {
    for (const key of ["fg", "bg"] as const) {
      const color = integer(cell[key], `${label}.${key}`);
      if (color < 0 || color > 0xffffff) throw new Error(`${label}.${key} must be a 24-bit color`);
    }
  }
  return cell;
}

function boundsFor(occupancy: JsonObject[]) {
  const rows = occupancy.map((cell) => cell.row as number);
  const cols = occupancy.map((cell) => cell.col as number);
  const minRow = Math.min(...rows);
  const maxRow = Math.max(...rows);
  const minCol = Math.min(...cols);
  const maxCol = Math.max(...cols);
  return {
    min_row: minRow,
    max_row: maxRow,
    min_col: minCol,
    max_col: maxCol,
    width: maxCol - minCol + 1,
    height: maxRow - minRow + 1,
  };
}

export function validateInstalledCaptureReceipt(value: unknown): void {
  const receipt = object(value, "receipt");
  exactKeys(receipt, [
    "schema_version", "goal_id", "workstream_id", "next_executed_outcome", "issue_id",
    "result", "source_commit", "binary_sha256", "capture_tool_sha256", "viewport",
    "captures", "geometry", "art_quality_obligation", "claim_boundary",
  ], "receipt");
  if (receipt.schema_version !== "ember-fireball-installed-capture-receipt-v1") throw new Error("wrong receipt schema");
  if (receipt.goal_id !== "EMBER-02" || receipt.workstream_id !== "EMBER-02A") throw new Error("wrong goal binding");
  if (receipt.next_executed_outcome !== NEXT_OUTCOME) throw new Error("wrong next outcome");
  if (receipt.issue_id !== 54 || receipt.result !== "MEASURED") throw new Error("wrong issue/result");
  if (!COMMIT_RE.test(string(receipt.source_commit, "source_commit"))) throw new Error("source_commit must be lowercase Git SHA");
  sha(receipt.binary_sha256, "binary_sha256");
  sha(receipt.capture_tool_sha256, "capture_tool_sha256");

  const viewport = object(receipt.viewport, "viewport");
  exactKeys(viewport, ["desktop_width_px", "desktop_height_px", "snapped_side", "terminal_columns", "terminal_rows"], "viewport");
  if (viewport.desktop_width_px !== 1720 || viewport.desktop_height_px !== 1440 || viewport.snapped_side !== "left") {
    throw new Error("viewport must bind the operator's 1720x1440 left-snapped layout");
  }
  if (viewport.terminal_columns !== COLS || viewport.terminal_rows !== ROWS) throw new Error("terminal viewport must be 190x85");

  if (!Array.isArray(receipt.captures) || receipt.captures.length !== 3) throw new Error("exactly three captures required");
  let priorOccupancy: string | undefined;
  let priorBounds: string | undefined;
  const styleFrames = new Set<string>();
  for (let index = 0; index < receipt.captures.length; index++) {
    const capture = object(receipt.captures[index], `captures[${index}]`);
    exactKeys(capture, [
      "capture_id", "captured_at", "elapsed_ms_from_previous", "frame_file", "frame_sha256",
      "cells_file", "cells_sha256", "bounds", "occupancy", "cells",
    ], `captures[${index}]`);
    if (capture.capture_id !== `frame-${index + 1}`) throw new Error("capture ids must be ordered");
    if (Number.isNaN(Date.parse(string(capture.captured_at, "captured_at")))) throw new Error("captured_at must be ISO time");
    if (index === 0) {
      if (capture.elapsed_ms_from_previous !== null) throw new Error("first capture gap must be null");
    } else if (integer(capture.elapsed_ms_from_previous, "capture gap") < MIN_CAPTURE_GAP_MS) {
      throw new Error("captures must be at least two seconds apart");
    }
    for (const key of ["frame_file", "cells_file"] as const) {
      const file = string(capture[key], key);
      if (basename(file) !== file || file.includes("..")) throw new Error(`${key} must be a path-free basename`);
    }
    sha(capture.frame_sha256, "frame_sha256");
    sha(capture.cells_sha256, "cells_sha256");
    if (!Array.isArray(capture.occupancy) || capture.occupancy.length === 0) throw new Error("capture occupancy must be nonempty");
    if (!Array.isArray(capture.cells) || capture.cells.length !== capture.occupancy.length) throw new Error("capture cells must match occupancy count");
    const occupancy = capture.occupancy.map((cell, cellIndex) => validateCell(cell, `occupancy[${cellIndex}]`, false));
    const cells = capture.cells.map((cell, cellIndex) => validateCell(cell, `cells[${cellIndex}]`, true));
    const coordinates = occupancy.map((cell) => `${cell.row}:${cell.col}:${cell.char}`);
    if (new Set(coordinates).size !== coordinates.length) throw new Error("duplicate occupancy cell");
    const cellOccupancy = cells.map((cell) => `${cell.row}:${cell.col}:${cell.char}`);
    if (JSON.stringify(coordinates) !== JSON.stringify(cellOccupancy)) throw new Error("styled cells must exactly match occupancy");
    const computedBounds = boundsFor(occupancy);
    const bounds = object(capture.bounds, "bounds");
    exactKeys(bounds, ["min_row", "max_row", "min_col", "max_col", "width", "height"], "bounds");
    if (canonical(bounds) !== canonical(computedBounds)) throw new Error("capture bounds do not match occupancy");
    const occupancyKey = canonical(occupancy);
    const boundsKey = canonical(bounds);
    priorOccupancy ??= occupancyKey;
    priorBounds ??= boundsKey;
    if (occupancyKey !== priorOccupancy || boundsKey !== priorBounds) throw new Error("fireball geometry moved between captures");
    styleFrames.add(canonical(cells));
  }

  const geometry = object(receipt.geometry, "geometry");
  exactKeys(geometry, ["identical_bounds", "identical_occupancy", "distinct_style_frames"], "geometry");
  if (geometry.identical_bounds !== true || geometry.identical_occupancy !== true) throw new Error("geometry verdict must be fixed");
  if (geometry.distinct_style_frames !== styleFrames.size || styleFrames.size < 2) throw new Error("installed animation must show at least two style frames");

  const art = object(receipt.art_quality_obligation, "art_quality_obligation");
  exactKeys(art, ["disposition", "successor_issue"], "art_quality_obligation");
  if (art.disposition !== "TRANSFER_TO_CURRENT_PARENT" || art.successor_issue !== 1117) throw new Error("art obligation must transfer losslessly to #1117");
  if (!Array.isArray(receipt.claim_boundary) || receipt.claim_boundary.length === 0 ||
      receipt.claim_boundary.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new Error("claim_boundary must be nonempty strings");
  }
}

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function frameText(terminal: InstanceType<typeof Terminal>): string {
  const buffer = terminal.buffer.active;
  const lines: string[] = [];
  for (let row = 0; row < ROWS; row++) {
    lines.push(buffer.getLine(buffer.viewportY + row)?.translateToString(false) ?? " ".repeat(COLS));
  }
  return lines.join("\n") + "\n";
}

function fireballCells(terminal: InstanceType<typeof Terminal>) {
  const buffer = terminal.buffer.active;
  const cells: Array<{ row: number; col: number; char: string; fg: number; bg: number }> = [];
  for (let row = 0; row < Math.min(16, ROWS); row++) {
    const line = buffer.getLine(buffer.viewportY + row);
    if (!line) continue;
    for (let col = 0; col < Math.min(24, COLS); col++) {
      const cell = line.getCell(col);
      const char = cell?.getChars() ?? "";
      if (char === "▀" || char === "▄") {
        cells.push({ row, col, char, fg: cell!.getFgColor(), bg: cell!.getBgColor() });
      }
    }
  }
  if (cells.length === 0) throw new Error("no panel fireball cells found in installed frame");
  return cells;
}

async function main(): Promise<void> {
  const binary = resolve(process.argv[2] ?? "");
  const outDir = resolve(process.argv[3] ?? "");
  const sourceCommit = process.argv[4] ?? "";
  if (!binary || !outDir || !COMMIT_RE.test(sourceCommit)) {
    throw new Error("usage: fireball-frame-capture.ts <binary> <out-dir> <source-commit>");
  }
  mkdirSync(outDir, { recursive: true });
  const version = spawnSync(binary, ["--version", "--json"], { encoding: "utf8", windowsHide: true, timeout: 15_000 });
  if (version.status !== 0) throw new Error("compiled Ember version probe failed");
  const identity = JSON.parse(version.stdout ?? "{}") as JsonObject;
  if (identity.source_binding !== "BOUND" || identity.source_commit !== sourceCommit) throw new Error("binary source identity mismatch");

  const repo = spawnSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8", windowsHide: true });
  if (repo.status !== 0) throw new Error("cannot resolve repository root");
  const repoRoot = (repo.stdout ?? "").trim();
  const home = mkdtempSync(join(tmpdir(), "ember-fireball-54-"));
  const terminal = new Terminal({ cols: COLS, rows: ROWS, allowProposedApi: true });
  let raw = "";
  let writes = Promise.resolve();
  let child: IPty | undefined;
  const captures: JsonObject[] = [];
  try {
    child = spawnPty(binary, [], {
      name: "xterm-256color",
      cols: COLS,
      rows: ROWS,
      cwd: repoRoot,
      env: {
        ...process.env,
        EMBER_HOME: home,
        EMBER_REPO_ROOT: repoRoot,
        EMBER_SOURCE_ROOT: repoRoot,
        EMBER_GPU_FREE: "1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
        EMBER_CLI_HEADLESS_CAPTURE: "1",
      },
    });
    child.onData((data) => {
      raw += data;
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    const started = Date.now();
    while (!raw.includes(READY_OSC)) {
      if (Date.now() - started > TIMEOUT_MS) throw new Error("readiness marker was not observed");
      await sleep(50);
    }
    await writes;
    await sleep(500);
    let priorAt: number | undefined;
    for (let index = 0; index < 3; index++) {
      if (index > 0) await sleep(CAPTURE_GAP_MS);
      await writes;
      const capturedAt = Date.now();
      const text = frameText(terminal);
      const cells = fireballCells(terminal);
      const occupancy = cells.map(({ row, col, char }) => ({ row, col, char }));
      const frameFile = `frame-${index + 1}.txt`;
      const cellsFile = `frame-${index + 1}.cells.json`;
      writeFileSync(join(outDir, frameFile), text, "utf8");
      writeFileSync(join(outDir, cellsFile), JSON.stringify(cells) + "\n", "utf8");
      captures.push({
        capture_id: `frame-${index + 1}`,
        captured_at: new Date(capturedAt).toISOString(),
        elapsed_ms_from_previous: priorAt === undefined ? null : capturedAt - priorAt,
        frame_file: frameFile,
        frame_sha256: sha256File(join(outDir, frameFile)),
        cells_file: cellsFile,
        cells_sha256: sha256File(join(outDir, cellsFile)),
        bounds: boundsFor(occupancy),
        occupancy,
        cells,
      });
      priorAt = capturedAt;
    }

    const styleFrames = new Set(captures.map((capture) => canonical(capture.cells)));
    const receipt = {
      schema_version: "ember-fireball-installed-capture-receipt-v1",
      goal_id: "EMBER-02",
      workstream_id: "EMBER-02A",
      next_executed_outcome: NEXT_OUTCOME,
      issue_id: 54,
      result: "MEASURED",
      source_commit: sourceCommit,
      binary_sha256: sha256File(binary),
      capture_tool_sha256: sha256File(fileURLToPath(import.meta.url)),
      viewport: {
        desktop_width_px: 1720,
        desktop_height_px: 1440,
        snapped_side: "left",
        terminal_columns: COLS,
        terminal_rows: ROWS,
      },
      captures,
      geometry: {
        identical_bounds: new Set(captures.map((capture) => canonical(capture.bounds))).size === 1,
        identical_occupancy: new Set(captures.map((capture) => canonical(capture.occupancy))).size === 1,
        distinct_style_frames: styleFrames.size,
      },
      art_quality_obligation: {
        disposition: "TRANSFER_TO_CURRENT_PARENT",
        successor_issue: 1117,
      },
      claim_boundary: [
        "installed Ember UI geometry and color-pulse evidence only",
        "no model, training, benchmark, or capability claim",
        "art-quality redesign remains owned by current EMBER-03 parent issue #1117",
      ],
    };
    validateInstalledCaptureReceipt(receipt);
    writeFileSync(join(outDir, "receipt.json"), JSON.stringify(receipt, null, 2) + "\n", "utf8");
    console.log(JSON.stringify({ result: "MEASURED", receipt: "receipt.json", binary_sha256: receipt.binary_sha256 }));
  } finally {
    if (child) {
      try {
        appendFileSync(join(outDir, "kill-receipts.jsonl"), JSON.stringify({
          ts: new Date().toISOString(),
          pids: [child.pid],
          match_rule: "exact PID returned by this capture process's node-pty spawn",
          survivors_expected: "none",
        }) + "\n", "utf8");
      } finally {
        spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
      }
    }
    terminal.dispose();
    rmSync(home, { recursive: true, force: true });
  }
}

if (import.meta.main) {
  main().then(
    () => process.exit(0),
    (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    },
  );
}
