// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/verify-training.test.ts — unit tests for the /verify-training command.
//
// runProcess/readReceipt are injected so these tests never spawn the real ember-lab binary
// or touch the filesystem; the Rust implementation itself is covered separately in
// runtime/ember-lab's own test suite (cargo test), including the byte-parity golden fixture.

import { describe, it, expect } from "bun:test";
import { join } from "node:path";
import {
  createVerifyTrainingCommand,
  resolveEmberLabBinary,
  renderVerifyTrainingResult,
} from "./verify-training.ts";
import type { CommandContext } from "../types/command-types.ts";

const mockCtx: CommandContext = { sessionId: "test-session", mode: "test", cwd: "/repo" };

const PASS_RECEIPT = {
  schema_version: "ember-lab-training-verify-receipt-v1",
  ok: true,
  duration_ms: 120,
  closure: { declared_files: 39, closure_sha256: "e8287af1551d6115c4bd5355bab73f1b8452ca21ed6b31b6de25a0a10c4a09bc" },
  checks: [
    { name: "closure_members_present", ok: true, detail: "39 declared files present" },
    { name: "input_identity_admission_chain", ok: true, detail: "artifact_id=owned-four-domain-production-rung-v1" },
    { name: "model_tokenizer_identity", ok: true, detail: "tokenizer and config hashed" },
  ],
  certificate: null,
};

// ---------------------------------------------------------------------------
// resolveEmberLabBinary
// ---------------------------------------------------------------------------

describe("resolveEmberLabBinary", () => {
  it("prefers EMBER_LAB_BIN when set", () => {
    const resolved = resolveEmberLabBinary("/repo", { EMBER_LAB_BIN: "/custom/ember-lab.exe" }, () => false);
    expect(resolved).toBe("/custom/ember-lab.exe");
  });

  it("falls back to the release build output when it exists", () => {
    const exists = (p: string) => p.includes("target/release") || p.includes("target\\release");
    const resolved = resolveEmberLabBinary("/repo", {}, exists);
    expect(resolved).toContain("release");
  });

  it("falls back to the debug build output when release is absent", () => {
    const exists = (p: string) => p.includes("target/debug") || p.includes("target\\debug");
    const resolved = resolveEmberLabBinary("/repo", {}, exists);
    expect(resolved).toContain("debug");
  });

  it("returns the release path (never silently a bare binary name) when neither build exists", () => {
    const resolved = resolveEmberLabBinary("/repo", {}, () => false);
    expect(resolved).toContain("release");
    expect(resolved.startsWith("/repo") || resolved.startsWith("\\repo")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// renderVerifyTrainingResult
// ---------------------------------------------------------------------------

describe("renderVerifyTrainingResult", () => {
  it("renders PASS with closure hash, per-check detail, and receipt path", () => {
    const rendered = renderVerifyTrainingResult(PASS_RECEIPT as any, "/repo/.ember/verify-training-receipt.json");
    expect(rendered).toContain("verify-training: PASS -- 120 ms");
    expect(rendered).toContain("closure_sha256=e8287af1551d6115c4bd5355bab73f1b8452ca21ed6b31b6de25a0a10c4a09bc");
    expect(rendered).toContain("ok  closure_members_present: 39 declared files present");
    expect(rendered).toContain("receipt: /repo/.ember/verify-training-receipt.json");
  });

  it("marks a failed check with FAIL and never hides which check failed", () => {
    const receipt = {
      ...PASS_RECEIPT,
      ok: false,
      checks: [{ name: "closure_members_present", ok: false, detail: "missing: tools/x.py" }],
    };
    const rendered = renderVerifyTrainingResult(receipt as any, "/repo/.ember/verify-training-receipt.json");
    expect(rendered).toContain("verify-training: FAIL");
    expect(rendered).toContain("FAIL  closure_members_present: missing: tools/x.py");
  });

  it("renders the certificate block only when present", () => {
    const withCert = {
      ...PASS_RECEIPT,
      certificate: { path: "/repo/cert.json", closure_sha256_matches: true, pin_is_ancestor: true },
    };
    const rendered = renderVerifyTrainingResult(withCert as any, "/repo/.ember/verify-training-receipt.json");
    expect(rendered).toContain("certificate: closure_sha256_matches=true pin_is_ancestor=true");

    const withoutCert = renderVerifyTrainingResult(PASS_RECEIPT as any, "/repo/.ember/verify-training-receipt.json");
    expect(withoutCert).not.toContain("certificate:");
  });
});

// ---------------------------------------------------------------------------
// createVerifyTrainingCommand
// ---------------------------------------------------------------------------

describe("createVerifyTrainingCommand", () => {
  it("invokes ember-lab with exactly --root/--receipt and no --certificate when none is given", async () => {
    let capturedArgs: string[] | undefined;
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      emberLabBinary: "/repo/runtime/ember-lab/target/release/ember-lab.exe",
      runProcess: async (binary, args) => {
        capturedArgs = args;
        return { stdout: "", stderr: "" };
      },
      readReceipt: () => PASS_RECEIPT as any,
    });
    const result = await command.execute("", mockCtx);
    expect(capturedArgs).toEqual([
      "verify-training",
      "--root",
      "/repo",
      "--receipt",
      join("/repo", ".ember", "verify-training-receipt.json"),
    ]);
    expect(result && "message" in result ? result.message : "").toContain("verify-training: PASS");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBeUndefined();
  });

  it("forwards --certificate only when the flag is passed", async () => {
    let capturedArgs: string[] | undefined;
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      emberLabBinary: "/repo/ember-lab.exe",
      runProcess: async (binary, args) => {
        capturedArgs = args;
        return { stdout: "", stderr: "" };
      },
      readReceipt: () => PASS_RECEIPT as any,
    });
    await command.execute("--certificate /repo/receipts/cert.json", mockCtx);
    expect(capturedArgs).toContain("--certificate");
    expect(capturedArgs).toContain("/repo/receipts/cert.json");
  });

  it("rejects malformed arguments before ever spawning a process", async () => {
    let spawned = false;
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      runProcess: async () => {
        spawned = true;
        return { stdout: "", stderr: "" };
      },
      readReceipt: () => PASS_RECEIPT as any,
    });
    const result = await command.execute("--bogus", mockCtx);
    expect(spawned).toBe(false);
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  });

  it("still reads and renders the receipt when ember-lab exits 1 for a completed red run", async () => {
    const redReceipt = {
      ...PASS_RECEIPT,
      ok: false,
      checks: [{ name: "closure_members_present", ok: false, detail: "missing: tools/x.py" }],
    };
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      runProcess: async () => {
        const error = new Error("Command failed with exit code 1: ember-lab verify-training ...");
        throw error;
      },
      readReceipt: () => redReceipt as any,
    });
    const result = await command.execute("", mockCtx);
    expect(result && "message" in result ? result.message : "").toContain("verify-training: FAIL");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  });

  it("reports an infra error (never a fabricated receipt) when the process cannot start at all", async () => {
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      runProcess: async () => {
        throw new Error("ENOENT: spawn ember-lab.exe");
      },
      readReceipt: () => {
        throw new Error("should never be called");
      },
    });
    const result = await command.execute("", mockCtx);
    expect(result && "message" in result ? result.message : "").toContain("could not run");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  });
});
