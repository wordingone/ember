// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { writeHardeningReceipt } from "./hardening-receipts.ts";

describe("writeHardeningReceipt", () => {
  let scratchDir: string;
  let receiptsPath: string;

  beforeEach(() => {
    scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hardening-receipts-"));
    receiptsPath = path.join(scratchDir, "hardening-receipts.jsonl");
  });

  afterEach(() => {
    fs.rmSync(scratchDir, { recursive: true, force: true });
  });

  it("appends one JSONL row with ts/suite/cell/outcome", async () => {
    await writeHardeningReceipt({ suite: "boot-matrix", cell: "missing-models-json", outcome: "pass" }, receiptsPath);

    const raw = fs.readFileSync(receiptsPath, "utf-8").trim();
    const row = JSON.parse(raw) as Record<string, unknown>;
    expect(row["suite"]).toBe("boot-matrix");
    expect(row["cell"]).toBe("missing-models-json");
    expect(row["outcome"]).toBe("pass");
    expect(typeof row["ts"]).toBe("string");
  });

  it("appends multiple rows across calls (one line per cell, never overwritten)", async () => {
    await writeHardeningReceipt({ suite: "boot-matrix", cell: "a", outcome: "pass" }, receiptsPath);
    await writeHardeningReceipt({ suite: "boot-matrix", cell: "b", outcome: "fail", detail: "boom" }, receiptsPath);

    const lines = fs.readFileSync(receiptsPath, "utf-8").trim().split("\n");
    expect(lines.length).toBe(2);
    const second = JSON.parse(lines[1]!) as Record<string, unknown>;
    expect(second["cell"]).toBe("b");
    expect(second["outcome"]).toBe("fail");
    expect(second["detail"]).toBe("boom");
  });

  it("never throws when the receipts path cannot be written (best-effort)", async () => {
    // A path whose parent is actually a FILE, not a directory -- mkdir(recursive) fails.
    const blockerFile = path.join(scratchDir, "blocker");
    fs.writeFileSync(blockerFile, "x");
    const badPath = path.join(blockerFile, "receipts", "hardening-receipts.jsonl");

    await expect(writeHardeningReceipt({ suite: "s", cell: "c", outcome: "pass" }, badPath)).resolves.toBeUndefined();
  });
});
