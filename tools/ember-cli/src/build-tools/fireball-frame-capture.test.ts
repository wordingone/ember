// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  redactInstalledFrame,
  validateInstalledCaptureReceipt,
  verifyInstalledCaptureDirectory,
  waitForDistinctCells,
} from "./fireball-frame-capture.ts";

const SHA = "a".repeat(64);
const COMMIT = "b".repeat(40);
const digest = (value: string) => createHash("sha256").update(value).digest("hex");

function receipt() {
  const cells = [
    { row: 2, col: 4, char: "▀", fg: 0xff7d1a, bg: 0x7a1f0a },
    { row: 3, col: 3, char: "▀", fg: 0xd4541c, bg: -1 },
  ];
  return {
    schema_version: "ember-fireball-installed-capture-receipt-v1",
    ticket: "EMBER-CLI-ISSUE-54-FIREBALL-CAPTURE",
    ts: "2026-08-07T15:00:00.000Z",
    sha_convention: "sha256 over exact on-disk file bytes, no normalization",
    invariant_sha256: "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6",
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    issue_id: 54,
    result: "MEASURED",
    source_commit: COMMIT,
    binary_sha256: SHA,
    capture_tool_sha256: SHA,
    viewport: {
      desktop_width_px: 1720,
      desktop_height_px: 1440,
      snapped_side: "left",
      terminal_columns: 190,
      terminal_rows: 85,
    },
    captures: [0, 1, 2].map((index) => ({
      capture_id: `frame-${index + 1}`,
      captured_at: `2026-08-07T15:00:0${index * 3}.000Z`,
      elapsed_ms_from_previous: index === 0 ? null : 3000,
      frame_file: `frame-${index + 1}.txt`,
      frame_sha256: SHA,
      cells_file: `frame-${index + 1}.cells.json`,
      cells_sha256: SHA,
      bounds: { min_row: 2, max_row: 3, min_col: 3, max_col: 4, width: 2, height: 2 },
      occupancy: cells.map(({ row, col, char }) => ({ row, col, char })),
      cells: cells.map((cell) => ({ ...cell, fg: cell.fg + index })),
    })),
    geometry: {
      identical_bounds: true,
      identical_occupancy: true,
      distinct_style_frames: 3,
    },
    art_quality_obligation: {
      disposition: "TRANSFER_TO_CURRENT_PARENT",
      successor_issue: 1117,
    },
    claim_boundary: ["installed UI geometry only", "no model or capability claim"],
  };
}

describe("issue #54 installed fireball capture receipt", () => {
  test("redacts absolute host paths from committed installed frames without changing bytes", () => {
    const privateFrame = "root B:\\tmp\\ember-303 data B:\\tmp\\ember-303\\data\n";
    const publicFrame = redactInstalledFrame(privateFrame, "B:\\tmp\\ember-303");
    expect(publicFrame).not.toContain("B:\\");
    expect(Buffer.byteLength(publicFrame)).toBe(Buffer.byteLength(privateFrame));
  });

  test("waits past a cadence alias until the real terminal style changes", async () => {
    const frames = [
      [{ row: 2, col: 4, char: "▀", fg: 1, bg: -1 }],
      [{ row: 2, col: 4, char: "▀", fg: 1, bg: -1 }],
      [{ row: 2, col: 4, char: "▀", fg: 2, bg: -1 }],
    ];
    let index = 0;
    const observed = await waitForDistinctCells(
      frames[0]!,
      () => frames[Math.min(++index, frames.length - 1)]!,
      async () => undefined,
      3,
    );
    expect(observed).toEqual(frames[2]!);
  });

  test("accepts exactly three source-bound captures at least two seconds apart", () => {
    expect(validateInstalledCaptureReceipt(receipt())).toBeUndefined();
  });

  test("reopens and hashes every referenced frame artifact", () => {
    const directory = mkdtempSync(join(tmpdir(), "ember-fireball-receipt-"));
    try {
      const candidate = receipt();
      for (const capture of candidate.captures) {
        const frame = `${capture.capture_id}\n`;
        const cells = JSON.stringify(capture.cells) + "\n";
        writeFileSync(join(directory, capture.frame_file), frame, "utf8");
        writeFileSync(join(directory, capture.cells_file), cells, "utf8");
        capture.frame_sha256 = digest(frame);
        capture.cells_sha256 = digest(cells);
      }
      writeFileSync(join(directory, "receipt.json"), JSON.stringify(candidate), "utf8");
      expect(verifyInstalledCaptureDirectory(directory)).toBeUndefined();
      writeFileSync(join(directory, candidate.captures[1]!.frame_file), "tampered\n", "utf8");
      expect(() => verifyInstalledCaptureDirectory(directory)).toThrow("frame-2 frame sha256 mismatch");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  test("rejects timing, occupancy, style, hash, viewport, and unknown-field drift", () => {
    const cases: unknown[] = [];
    const tooFast = receipt();
    tooFast.captures[1]!.elapsed_ms_from_previous = 1999;
    cases.push(tooFast);

    const moved = receipt();
    moved.captures[2]!.occupancy[0]!.col += 1;
    cases.push(moved);

    const frozen = receipt();
    frozen.captures[1]!.cells = frozen.captures[0]!.cells.map((cell) => ({ ...cell }));
    frozen.captures[2]!.cells = frozen.captures[0]!.cells.map((cell) => ({ ...cell }));
    frozen.geometry.distinct_style_frames = 1;
    cases.push(frozen);

    const badHash = receipt();
    badHash.binary_sha256 = "A".repeat(64);
    cases.push(badHash);

    const wrongViewport = receipt();
    wrongViewport.viewport.terminal_columns = 189;
    cases.push(wrongViewport);

    const extra = { ...receipt(), surprise: true };
    cases.push(extra);

    const invalidDefaultColor = receipt();
    invalidDefaultColor.captures[0]!.cells[0]!.bg = -2;
    cases.push(invalidDefaultColor);

    for (const candidate of cases) {
      expect(() => validateInstalledCaptureReceipt(candidate)).toThrow();
    }
  });
});
