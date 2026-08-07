// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
  buildIssue303TerminalReceipt,
  verifyIssue303Evidence,
} from "./verify-issue-303-layout.ts";

const evidenceRoot = resolve(import.meta.dir, "../../../../receipts/ember-cli/issue-303");

describe("issue #303 terminal layout evidence", () => {
  test("reopens current-master resize and half-screen captures", () => {
    const verified = verifyIssue303Evidence(evidenceRoot);
    expect(verified.source_commit).toMatch(/^[0-9a-f]{40}$/);
    expect(verified.binary_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(verified.resize_dimensions).toEqual(["80x24", "40x24", "80x24"]);
    expect(verified.restored_prompt_geometry).toBe(true);
    expect(verified.half_screen_dimensions).toBe("190x85");
    expect(verified.left_panel_right_column).toBe(110);
    expect(verified.prompt_right_column).toBe(110);
  });

  test("emits a closed path-free terminal disposition", () => {
    const receipt = buildIssue303TerminalReceipt(verifyIssue303Evidence(evidenceRoot));
    expect(receipt.schema_version).toBe("ember-cli-issue-303-terminal-layout-v1");
    expect(receipt.issue_id).toBe(303);
    expect(receipt.result).toBe("PASS");
    expect(receipt.zero_activity_obligation).toEqual({
      disposition: "TRANSFERRED",
      canonical_issue: 485,
    });
    expect(JSON.stringify(receipt)).not.toContain("B:\\");
    expect(JSON.stringify(receipt)).not.toContain("C:\\");
  });

  test("rejects changed frame bytes and cross-binary evidence", () => {
    const root = mkdtempSync(join(tmpdir(), "ember-303-evidence-"));
    try {
      cpSync(evidenceRoot, root, { recursive: true });
      const frame = join(root, "current-master-half-screen", "frame-1.txt");
      writeFileSync(frame, `${readFileSync(frame, "utf8")}tamper`, "utf8");
      expect(() => verifyIssue303Evidence(root)).toThrow("frame-1 frame sha256 mismatch");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }

    const root2 = mkdtempSync(join(tmpdir(), "ember-303-cross-binary-"));
    try {
      cpSync(evidenceRoot, root2, { recursive: true });
      const receiptPath = join(root2, "current-master-resize", "prompt-resize-receipt.json");
      const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
      receipt.binary.sha256 = "0".repeat(64);
      receipt.binary.reproducible_rebuild.sha256 = "0".repeat(64);
      writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
      expect(() => verifyIssue303Evidence(root2)).toThrow("capture receipts bind different binaries");
    } finally {
      rmSync(root2, { recursive: true, force: true });
    }
  });
});
