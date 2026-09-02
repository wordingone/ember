// github-receipts.test.ts — JSONL receipt writer tests for GitHub write
// actions (ember issue #507). Mirrors goal-receipts.test.ts's conventions.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  compactUtcStamp,
  createGithubReceiptWriter,
  getGithubReceiptWriter,
  _resetGithubReceiptWriterForTests,
  GITHUB_RECEIPT_ACTOR,
} from "./github-receipts.ts";

let scratchDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-github-receipts-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
  _resetGithubReceiptWriterForTests();
});

describe("compactUtcStamp", () => {
  test("strips dashes, colons, and milliseconds from an ISO timestamp", () => {
    const d = new Date("2026-07-08T05:05:25.000Z");
    expect(compactUtcStamp(d)).toBe("20260708T050525Z");
  });
});

describe("createGithubReceiptWriter", () => {
  test("creates receipts/github-actions/actions-<UTC>.jsonl under the given root", () => {
    const bootTime = new Date("2026-07-08T05:05:25.000Z");
    const writer = createGithubReceiptWriter({ repoRoot: scratchDir, bootTime });

    expect(writer.filePath).toBe(path.join(scratchDir, "receipts", "github-actions", "actions-20260708T050525Z.jsonl"));
    expect(fs.existsSync(path.dirname(writer.filePath))).toBe(true);
  });

  test("append() writes one JSONL row per call, in the exact spec shape", () => {
    const writer = createGithubReceiptWriter({ repoRoot: scratchDir, bootTime: new Date("2026-07-08T05:05:25.000Z") });

    writer.append("issue_create", "#42", true);
    writer.append("pr_create", "feat/507-gh-identity", false);

    const lines = fs.readFileSync(writer.filePath, "utf8").trim().split("\n");
    expect(lines.length).toBe(2);

    const row1 = JSON.parse(lines[0]!);
    expect(row1.actor).toBe(GITHUB_RECEIPT_ACTOR);
    expect(row1.action).toBe("issue_create");
    expect(row1.target).toBe("#42");
    expect(row1.ok).toBe(true);
    expect(typeof row1.ts).toBe("string");

    const row2 = JSON.parse(lines[1]!);
    expect(row2.action).toBe("pr_create");
    expect(row2.ok).toBe(false);
  });

  test("append() never throws even when the directory can't be created (fail-open contract)", () => {
    // Point repoRoot at a file (not a directory) so mkdirSync fails inside the
    // writer -- append() must still swallow the error, not crash the caller.
    const blockerFile = path.join(scratchDir, "not-a-dir");
    fs.writeFileSync(blockerFile, "x");
    const writer = createGithubReceiptWriter({ repoRoot: blockerFile, bootTime: new Date() });

    expect(() => writer.append("issue_create", "#1", true)).not.toThrow();
  });
});

describe("getGithubReceiptWriter", () => {
  test("returns the same writer instance across calls (lazy singleton)", () => {
    const a = getGithubReceiptWriter();
    const b = getGithubReceiptWriter();
    expect(a).toBe(b);
  });

  test("_resetGithubReceiptWriterForTests() forces a fresh instance on next access", () => {
    const a = getGithubReceiptWriter();
    _resetGithubReceiptWriterForTests();
    const b = getGithubReceiptWriter();
    expect(a).not.toBe(b);
  });
});
