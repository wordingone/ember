// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/verify-training.test.ts — unit tests for the /verify-training command.
//
// runProcess/readReceipt are injected so most of these tests never spawn the real ember-lab
// binary or touch the filesystem; the Rust implementation itself is covered separately in
// runtime/ember-lab's own test suite (cargo test), including the byte-parity golden fixture.
//
// ONE exception, load-bearing (rev-1400 finding): "still reads and renders the receipt on a
// genuine completed-red run" drives the REAL compiled ember-lab.exe through a REAL FAIL case
// (a certificate with a deliberately wrong closure_sha256/public_master_sha) instead of
// fabricating an error object by hand. The original version of this test hand-built an Error
// whose .message matched a regex the production code used to classify a completed-red run --
// but Node's real child_process rejection carries the exit code as a NUMBER on `.code`, and
// its real .message is just "Command failed: <cmd>\n", which never matched that regex. The
// hand-fabricated test therefore passed while every genuine FAIL in production rendered as an
// infra crash. Driving the real binary is the only way this shape of bug cannot recur here:
// the test's error object is whatever Node's child_process module actually produces, not a
// guess at its shape.

import { describe, it, expect } from "bun:test";
import { join, resolve } from "node:path";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import {
  createVerifyTrainingCommand,
  resolveEmberLabBinary,
  renderVerifyTrainingResult,
} from "./verify-training.ts";
import type { CommandContext } from "../types/command-types.ts";

// tools/ember-cli/src/commands/ -> tools/ember-cli/src -> tools/ember-cli -> tools -> repo root
const REPO_ROOT = resolve(import.meta.dir, "..", "..", "..", "..");

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

  it("classifies a completed-red run by the NUMERIC .code Node's child_process actually attaches, never by message text", async () => {
    // Node's real rejection for a nonzero exit carries `code` as a number and a message of
    // just "Command failed: <cmd>\n" -- never the strings "code: 1" or "exit code 1" the
    // pre-fix classifier regex looked for. This mock is honest about that shape (numeric
    // .code, unrelated message text) specifically so it cannot pass the way the old
    // message-regex classifier's own hand-fabricated test used to.
    const redReceipt = {
      ...PASS_RECEIPT,
      ok: false,
      checks: [{ name: "closure_members_present", ok: false, detail: "missing: tools/x.py" }],
    };
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      runProcess: async () => {
        throw Object.assign(new Error("Command failed: ember-lab verify-training ...\n"), { code: 1 });
      },
      readReceipt: () => redReceipt as any,
    });
    const result = await command.execute("", mockCtx);
    expect(result && "message" in result ? result.message : "").toContain("verify-training: FAIL");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  });

  it("drives the REAL compiled ember-lab.exe through a genuine completed-red run (rev-1400 regression test)", async () => {
    // No mocks at all below this line except readReceipt's path is whatever the command
    // computes -- this is the actual binary, the actual repo tree, an actual subprocess exit.
    const scratchDir = mkdtempSync(join(tmpdir(), "verify-training-red-run-"));
    const wrongCertificatePath = join(scratchDir, "wrong-certificate.json");
    writeFileSync(
      wrongCertificatePath,
      JSON.stringify({
        // Deliberately wrong on both fields the certificate check binds: neither will match
        // the live closure hash nor be an ancestor of HEAD, so ember-lab genuinely completes
        // with ok=false and exits 1 -- not a crash, a real red verdict.
        closure_sha256: "0".repeat(64),
        public_master_sha: "0".repeat(40),
      }),
    );

    const command = createVerifyTrainingCommand({ repoRoot: REPO_ROOT });
    const result = await command.execute(`--certificate ${wrongCertificatePath}`, {
      sessionId: "real-binary-test",
      mode: "test",
      cwd: REPO_ROOT,
    });

    rmSync(scratchDir, { recursive: true, force: true });

    const message = result && "message" in result ? result.message : "";
    expect(message).toContain("verify-training: FAIL");
    expect(message).toContain("closure_sha256_matches=false");
    expect(message).toContain("pin_is_ancestor=false");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  }, 30_000);

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
