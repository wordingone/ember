// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// operator-receipts.test.ts — JSONL receipt writer tests.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  compactUtcStamp,
  createOperatorReceiptWriter,
  defaultRepoRoot,
} from "./operator-receipts.ts";

let scratchDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-operator-receipts-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
});

describe("compactUtcStamp", () => {
  test("strips dashes, colons, and milliseconds from an ISO timestamp", () => {
    const d = new Date("2026-07-05T16:01:01.581Z");
    expect(compactUtcStamp(d)).toBe("20260705T160101Z");
  });
});

describe("defaultRepoRoot", () => {
  test("resolves to a directory containing docs/domains/governance/authority/GOAL.md (the real repo root)", () => {
    const root = defaultRepoRoot();
    expect(fs.existsSync(path.join(root, "docs/domains/governance/authority/GOAL.md"))).toBe(true);
  });
});

describe("createOperatorReceiptWriter", () => {
  test("creates receipts/operator-sessions/session-<UTC>.jsonl under the given root", () => {
    const bootTime = new Date("2026-07-05T18:21:01.000Z");
    const writer = createOperatorReceiptWriter({ repoRoot: scratchDir, bootTime });

    expect(writer.filePath).toBe(
      path.join(scratchDir, "receipts", "operator-sessions", "session-20260705T182101Z.jsonl"),
    );
    expect(fs.existsSync(path.dirname(writer.filePath))).toBe(true);
  });

  test("append() writes one JSON row per line, in order, role always 'system'", () => {
    const writer = createOperatorReceiptWriter({ repoRoot: scratchDir });

    writer.append("pipe_connected");
    writer.append("prompt_injected", "hello from the operator");
    writer.append("command_completed", "watch");
    writer.append("response_rendered");

    const lines = fs.readFileSync(writer.filePath, "utf8").trim().split("\n");
    expect(lines.length).toBe(4);

    const rows = lines.map((l) => JSON.parse(l));
    expect(rows[0].event).toBe("pipe_connected");
    expect(rows[0].role).toBe("system");
    expect(typeof rows[0].ts).toBe("string");
    expect(rows[1].event).toBe("prompt_injected");
    expect(rows[1].detail).toBe("hello from the operator");
    expect(rows[2].event).toBe("command_completed");
    expect(rows[2].detail).toBe("watch");
    expect(rows[3].event).toBe("response_rendered");
  });

  test("fails open: append() never throws even when the target directory cannot be created", () => {
    // Create a plain FILE where the writer expects to make a directory, so
    // mkdirSync collides (ENOTDIR-shaped failure) — a realistic disk problem.
    const blockerPath = path.join(scratchDir, "receipts");
    fs.writeFileSync(blockerPath, "not a directory");

    expect(() => {
      const writer = createOperatorReceiptWriter({ repoRoot: scratchDir });
      writer.append("pipe_connected");
      writer.append("prompt_injected", "should not crash the CLI");
    }).not.toThrow();
  });
});
