// services/run-progress-scanner.test.ts — issue #447: active-run progress-file scanning.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  findNewestProgressFile,
  readLastJsonlLine,
  parseProgressLine,
  pollActiveRun,
  isActiveRunFresh,
  formatActiveRunLine,
  ACTIVE_RUN_FRESHNESS_TTL_MS,
} from "./run-progress-scanner.ts";

let scratchDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-run-progress-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
});

describe("findNewestProgressFile", () => {
  test("finds a progress file nested two levels deep (real convention: receipts/<lane>/<run>-progress-<ts>.jsonl)", () => {
    const laneDir = path.join(scratchDir, "ember-c-scale");
    fs.mkdirSync(laneDir, { recursive: true });
    const filePath = path.join(laneDir, "w1-live-progress-20260707T135344Z.jsonl");
    fs.writeFileSync(filePath, '{"step":0}\n');

    return findNewestProgressFile(scratchDir).then((result) => {
      expect(result?.path).toBe(filePath);
    });
  });

  test("picks the file with the newest mtime among several", async () => {
    const laneDir = path.join(scratchDir, "lane");
    fs.mkdirSync(laneDir, { recursive: true });
    const older = path.join(laneDir, "run-a-progress-1.jsonl");
    const newer = path.join(laneDir, "run-b-progress-2.jsonl");
    fs.writeFileSync(older, "{}");
    fs.utimesSync(older, new Date(1000), new Date(1000));
    fs.writeFileSync(newer, "{}");
    fs.utimesSync(newer, new Date(5000), new Date(5000));

    const result = await findNewestProgressFile(scratchDir);
    expect(result?.path).toBe(newer);
  });

  test("ignores non-matching files (wrong extension, no 'progress' substring)", async () => {
    const laneDir = path.join(scratchDir, "lane");
    fs.mkdirSync(laneDir, { recursive: true });
    fs.writeFileSync(path.join(laneDir, "board-receipt.json"), "{}");
    fs.writeFileSync(path.join(laneDir, "notes.jsonl"), "{}");

    const result = await findNewestProgressFile(scratchDir);
    expect(result).toBeNull();
  });

  test("returns null when the root directory doesn't exist", async () => {
    const result = await findNewestProgressFile(path.join(scratchDir, "does-not-exist"));
    expect(result).toBeNull();
  });

  test("returns null for an empty tree", async () => {
    const result = await findNewestProgressFile(scratchDir);
    expect(result).toBeNull();
  });
});

describe("readLastJsonlLine", () => {
  test("returns the last non-empty line", async () => {
    const filePath = path.join(scratchDir, "f.jsonl");
    fs.writeFileSync(filePath, '{"step":0}\n{"step":1}\n{"step":2}\n');
    expect(await readLastJsonlLine(filePath)).toBe('{"step":2}');
  });

  test("ignores a trailing blank line", async () => {
    const filePath = path.join(scratchDir, "f.jsonl");
    fs.writeFileSync(filePath, '{"step":0}\n{"step":1}\n\n');
    expect(await readLastJsonlLine(filePath)).toBe('{"step":1}');
  });

  test("returns null for a missing file", async () => {
    expect(await readLastJsonlLine(path.join(scratchDir, "missing.jsonl"))).toBeNull();
  });

  test("returns null for an empty file", async () => {
    const filePath = path.join(scratchDir, "empty.jsonl");
    fs.writeFileSync(filePath, "");
    expect(await readLastJsonlLine(filePath)).toBeNull();
  });
});

describe("parseProgressLine", () => {
  test("parses the real observed shape", () => {
    const line = '{"step": 1800, "tokens_so_far": 920000, "eval_loss": 4.9375, "target_eval_loss": 4.0, "ts": "20260707T141940Z"}';
    expect(parseProgressLine(line)).toEqual({
      step: 1800,
      tokensSoFar: 920000,
      evalLoss: 4.9375,
      targetEvalLoss: 4.0,
      ts: "20260707T141940Z",
    });
  });

  test("degrades gracefully when fields are missing (no throw, absent fields)", () => {
    expect(parseProgressLine('{"step": 5}')).toEqual({ step: 5 });
  });

  test("degrades gracefully when a field has the wrong type", () => {
    expect(parseProgressLine('{"step": "five", "eval_loss": 1.5}')).toEqual({ evalLoss: 1.5 });
  });

  test("returns null for invalid JSON", () => {
    expect(parseProgressLine("not json")).toBeNull();
  });

  test("returns null for a JSON array (not an object)", () => {
    expect(parseProgressLine("[1,2,3]")).toBeNull();
  });
});

describe("pollActiveRun", () => {
  test("returns the combined snapshot for a real run tree", async () => {
    const laneDir = path.join(scratchDir, "ember-c-scale");
    fs.mkdirSync(laneDir, { recursive: true });
    const filePath = path.join(laneDir, "w1-live-progress-20260707T135344Z.jsonl");
    fs.writeFileSync(filePath, '{"step": 0}\n{"step": 1800, "eval_loss": 4.9375, "ts": "20260707T141940Z"}\n');

    const result = await pollActiveRun(scratchDir);
    expect(result?.relativePath).toBe(path.join("ember-c-scale", "w1-live-progress-20260707T135344Z.jsonl"));
    expect(result?.phase).toEqual({ step: 1800, evalLoss: 4.9375, ts: "20260707T141940Z" });
    expect(typeof result?.mtimeMs).toBe("number");
  });

  test("returns null when no progress file exists anywhere", async () => {
    expect(await pollActiveRun(scratchDir)).toBeNull();
  });

  test("returns null when the newest progress file's last line isn't parseable", async () => {
    const laneDir = path.join(scratchDir, "lane");
    fs.mkdirSync(laneDir, { recursive: true });
    fs.writeFileSync(path.join(laneDir, "run-progress-1.jsonl"), "not json at all");

    expect(await pollActiveRun(scratchDir)).toBeNull();
  });
});

describe("isActiveRunFresh", () => {
  test("returns false when run is null", () => {
    expect(isActiveRunFresh(null)).toBe(false);
  });

  test("returns true when mtime is within the freshness TTL", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const run = { relativePath: "r.jsonl", mtimeMs: nowMs - 60_000, phase: {} };
    expect(isActiveRunFresh(run, nowMs)).toBe(true);
  });

  test("returns false when mtime is older than the freshness TTL", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const run = { relativePath: "r.jsonl", mtimeMs: nowMs - (ACTIVE_RUN_FRESHNESS_TTL_MS + 1_000), phase: {} };
    expect(isActiveRunFresh(run, nowMs)).toBe(false);
  });

  test("is exactly at the TTL boundary -> still fresh (inclusive)", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const run = { relativePath: "r.jsonl", mtimeMs: nowMs - ACTIVE_RUN_FRESHNESS_TTL_MS, phase: {} };
    expect(isActiveRunFresh(run, nowMs)).toBe(true);
  });
});

describe("formatActiveRunLine", () => {
  test("returns null when run is null", () => {
    expect(formatActiveRunLine(null)).toBeNull();
  });

  test("uses the lane name (parent dir), not the full filename -- avoids narrow-viewport collapse", () => {
    const nowMs = Date.parse("2026-07-07T14:25:00.000Z");
    const run = {
      relativePath: path.join("ember-c-scale", "w1-live-progress-20260707T135344Z.jsonl"),
      mtimeMs: Date.parse("2026-07-07T14:19:40.000Z"),
      phase: { step: 1800, evalLoss: 4.9375, ts: "20260707T141940Z" },
    };
    const result = formatActiveRunLine(run, nowMs);
    expect(result?.text).toBe("run: ember-c-scale step 1800, eval_loss 4.9375 \xB7 5m ago");
  });

  test("falls back to mtime-derived age when the line carries no ts", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 5, 0);
    const run = {
      relativePath: "lane/run.jsonl",
      mtimeMs: Date.UTC(2026, 6, 7, 12, 0, 0),
      phase: { step: 3 },
    };
    const result = formatActiveRunLine(run, nowMs);
    expect(result?.text).toBe("run: lane step 3 \xB7 5m ago");
  });

  test("shows 'running' when neither step nor eval_loss is present", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 5);
    const run = { relativePath: "lane/run.jsonl", mtimeMs: Date.UTC(2026, 6, 7, 12, 0, 0), phase: {} };
    const result = formatActiveRunLine(run, nowMs);
    expect(result?.text).toBe("run: lane running \xB7 just now");
  });

  test("falls back to the bare filename (minus extension) when the progress file has no lane subdirectory", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 5);
    const run = { relativePath: "flat-run.jsonl", mtimeMs: Date.UTC(2026, 6, 7, 12, 0, 0), phase: { step: 1 } };
    const result = formatActiveRunLine(run, nowMs);
    expect(result?.text).toBe("run: flat-run step 1 \xB7 just now");
  });
});
