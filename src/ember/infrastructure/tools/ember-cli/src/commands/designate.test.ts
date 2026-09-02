// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import { describe, expect, it } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createDesignateCommand } from "./designate.ts";

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

describe("/designate command", () => {
  it("fails closed on missing or unknown options without verifying anything", async () => {
    let calls = 0;
    const command = createDesignateCommand({
      verifyReceipt() {
        calls += 1;
        return null;
      },
    });

    const result = await command.execute(
      "--output-root C:/candidates --unknown value",
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("usage:");
    expect(calls).toBe(0);
  });

  it("refuses invalid candidate ids without verifying the bundle", async () => {
    let calls = 0;
    const command = createDesignateCommand({
      verifyReceipt() {
        calls += 1;
        return null;
      },
    });

    for (const candidateId of ["current.json", "Candidate-One", "../escape", "1abc", "_abc"]) {
      const result = await command.execute(
        `--output-root C:/candidates --candidate-id ${candidateId} ` +
          `--candidate-sha256 ${SHA_A} --producer-receipt-sha256 ${SHA_B}`,
        { sessionId: "s", mode: "local", cwd: "C:/ember" },
      );
      expect(result?.exitCode).toBe(2);
      expect(result?.message).toContain("invalid candidate id");
    }
    expect(calls).toBe(0);
  });

  it("refuses malformed sha256 authority evidence without verifying the bundle", async () => {
    let calls = 0;
    const command = createDesignateCommand({
      verifyReceipt() {
        calls += 1;
        return null;
      },
    });

    const result = await command.execute(
      `--output-root C:/candidates --candidate-id candidate-one ` +
        `--candidate-sha256 not-a-hash --producer-receipt-sha256 ${SHA_B}`,
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("invalid candidate authority evidence");
    expect(calls).toBe(0);
  });

  it("refuses when the bundle fails integrity verification", async () => {
    const command = createDesignateCommand({
      verifyReceipt: () => null,
    });

    const result = await command.execute(
      `--output-root C:/candidates --candidate-id candidate-one ` +
        `--candidate-sha256 ${SHA_A} --producer-receipt-sha256 ${SHA_B}`,
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("failed integrity verification");
  });

  it("refuses when the verifier's recomputed digest disagrees with the claimed candidate_sha256", async () => {
    const command = createDesignateCommand({
      verifyReceipt: () => "c".repeat(64), // does not equal the claimed candidateSha256
    });

    const result = await command.execute(
      `--output-root C:/candidates --candidate-id candidate-one ` +
        `--candidate-sha256 ${SHA_A} --producer-receipt-sha256 ${SHA_B}`,
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("failed integrity verification");
  });

  it("refuses a verified bundle whose receipt has no restart_run_manifest role", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-norole-"));
    const outputRoot = path.join(root, "candidates");
    const receiptRoot = path.join(outputRoot, "candidate-one", "producer-receipts");
    fs.mkdirSync(receiptRoot, { recursive: true });
    const receiptBytes = Buffer.from(`${JSON.stringify({ output_identities: { checkpoint: { relative_path: "checkpoint.bin", sha256: "d".repeat(64), bytes: 1 } } })}\n`);
    const receiptSha256 = createHash("sha256").update(receiptBytes).digest("hex");
    fs.writeFileSync(path.join(receiptRoot, `${receiptSha256}.json`), receiptBytes);

    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const command = createDesignateCommand({
      getConfigHome: () => configHome,
      verifyReceipt: () => SHA_A, // pretend the bundle verified as authentic
    });

    const result = await command.execute(
      `--output-root ${outputRoot} --candidate-id candidate-one ` +
        `--candidate-sha256 ${SHA_A} --producer-receipt-sha256 ${receiptSha256}`,
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("no restart_run_manifest role");
    expect(fs.existsSync(path.join(configHome, "owned", "current.json"))).toBe(false);
  });
});
