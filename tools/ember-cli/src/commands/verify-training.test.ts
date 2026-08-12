// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/verify-training.test.ts — unit tests for the /verify-training command.
//
// The command's daemon RPC and receipt reader are injected. No test-only direct process seam
// exists: every successful path must cross the same dispatch_manifest boundary as production.

import { describe, it, expect } from "bun:test";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { existsSync, mkdirSync, mkdtempSync, realpathSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
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
  it("dispatches one CPU-only EvidenceVerifier job through the resident daemon without a direct process", async () => {
    const root = mkdtempSync(join(tmpdir(), "verify-training-dispatch-"));
    try {
      const binary = join(root, "runtime", "ember-lab", "target", "release", "ember-lab.exe");
      const cargo = join(root, "runtime", "ember-lab", "Cargo.toml");
      const closure = join(root, "manifests", "training-dependency-closure.json");
      mkdirSync(join(root, "runtime", "ember-lab", "target", "release"), { recursive: true });
      mkdirSync(join(root, "manifests"), { recursive: true });
      writeFileSync(binary, "binary");
      writeFileSync(cargo, "[package]\nname='ember-lab'\n");
      writeFileSync(closure, "{}\n");
      writeFileSync(join(root, "README.md"), "# fixture\n");
      const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
      const command = createVerifyTrainingCommand({
        repoRoot: root,
        emberLabBinary: binary,
        env: { EMBER_LAB_PIPE: "\\\\.\\pipe\\ember-lab-test" },
        sourceCommit: "a".repeat(40),
        nowMs: () => 1_000,
        sleep: async () => {},
        callLab: async ({ method, params }) => {
          calls.push({ method, params });
          if (method === "dispatch_manifest") {
            const manifest = JSON.parse(params["manifest_utf8"] as string);
            const receiptArgument = manifest.args[manifest.args.indexOf("--receipt") + 1] as string;
            expect(existsSync(receiptArgument)).toBe(true);
            const preflight = manifest.preflight_receipt as string;
            mkdirSync(dirname(preflight), { recursive: true });
            writeFileSync(preflight, "preflight\n");
            return {
              pid: 123,
              preflight_receipt_path: process.platform === "win32" ? `\\\\?\\${preflight}` : realpathSync.native(preflight),
              preflight_receipt_sha256: createHash("sha256").update("preflight\n").digest("hex"),
            };
          }
          if (method === "job_state") return { state: "exited" };
          if (method === "job_exit_code") return { exit_code: 0 };
          throw new Error(`unexpected method ${method}`);
        },
        readReceipt: () => PASS_RECEIPT as any,
      });

      const result = await command.execute("", { ...mockCtx, cwd: root });

      expect(calls.map((call) => call.method)).toEqual(["dispatch_manifest", "job_state", "job_exit_code"]);
      const manifest = JSON.parse((calls[0]!.params["manifest_utf8"] as string));
      expect(manifest.workload_profile.profile_id).toBe("evidence_verifier");
      expect(manifest.minimum_free_vram_bytes).toBe(0);
      expect(manifest.program.path).toBe(binary);
      expect(manifest.args.slice(0, 3)).toEqual(["verify-training", "--root", root]);
      expect(manifest.env["EMBER_LAB_PIPE"]).toBe("\\\\.\\pipe\\ember-lab-test");
      expect(manifest.env["EMBER_LAB_DISPATCH_TOKEN"]).toBeUndefined();
      expect(manifest.custody_root).toContain(manifest.job_id);
      expect(result && "message" in result ? result.message : "").toContain("verify-training: PASS");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects malformed arguments before any daemon call", async () => {
    let called = false;
    const command = createVerifyTrainingCommand({
      repoRoot: "/repo",
      callLab: async () => {
        called = true;
        return {};
      },
    });
    const result = await command.execute("--bogus", mockCtx);
    expect(called).toBe(false);
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  });

  it("refuses when no resident daemon pipe is configured", async () => {
    const command = createVerifyTrainingCommand({ repoRoot: "/repo", env: {} });
    const result = await command.execute("", mockCtx);
    expect(result && "message" in result ? result.message : "").toContain("direct verify-training launch is forbidden");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
  });

  it("stops and verifies terminal settlement exactly once when a dispatched verifier times out", async () => {
    const root = mkdtempSync(join(tmpdir(), "verify-training-timeout-cleanup-"));
    try {
      const binary = join(root, "runtime", "ember-lab", "target", "release", "ember-lab.exe");
      mkdirSync(dirname(binary), { recursive: true });
      mkdirSync(join(root, "manifests"), { recursive: true });
      writeFileSync(binary, "binary");
      writeFileSync(join(root, "runtime", "ember-lab", "Cargo.toml"), "[package]\nname='ember-lab'\n");
      writeFileSync(join(root, "manifests", "training-dependency-closure.json"), "{}\n");
      writeFileSync(join(root, "README.md"), "# fixture\n");
      const methods: string[] = [];
      let clock = 999;
      let receiptReads = 0;
      let terminal = false;
      const command = createVerifyTrainingCommand({
        repoRoot: root,
        emberLabBinary: binary,
        env: { EMBER_LAB_PIPE: "\\\\.\\pipe\\ember-lab-test" },
        sourceCommit: "a".repeat(40),
        nowMs: () => ++clock,
        timeoutMs: 0,
        sleep: async () => {},
        callLab: async ({ method, params }) => {
          methods.push(method);
          if (method === "dispatch_manifest") {
            const manifest = JSON.parse(params["manifest_utf8"] as string);
            const preflight = manifest.preflight_receipt as string;
            mkdirSync(dirname(preflight), { recursive: true });
            writeFileSync(preflight, "preflight\n");
            return {
              pid: 123,
              preflight_receipt_path: preflight,
              preflight_receipt_sha256: createHash("sha256").update("preflight\n").digest("hex"),
            };
          }
          if (method === "stop_job") {
            terminal = true;
            return { stopped: true };
          }
          if (method === "job_state") return { state: terminal ? "stopped" : "running" };
          throw new Error(`unexpected method ${method}`);
        },
        readReceipt: () => {
          receiptReads += 1;
          return PASS_RECEIPT as any;
        },
      });
      const result = await command.execute("", { ...mockCtx, cwd: root });
      expect(methods).toEqual(["dispatch_manifest", "job_state", "stop_job", "job_state"]);
      expect(receiptReads).toBe(0);
      expect(result && "message" in result ? result.message : "").toContain("job timed out");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("refuses a forged daemon preflight response before polling or reading a result", async () => {
    const root = mkdtempSync(join(tmpdir(), "verify-training-preflight-refusal-"));
    try {
      const binary = join(root, "runtime", "ember-lab", "target", "release", "ember-lab.exe");
      mkdirSync(dirname(binary), { recursive: true });
      mkdirSync(join(root, "manifests"), { recursive: true });
      writeFileSync(binary, "binary");
      writeFileSync(join(root, "runtime", "ember-lab", "Cargo.toml"), "[package]\nname='ember-lab'\n");
      writeFileSync(join(root, "manifests", "training-dependency-closure.json"), "{}\n");
      writeFileSync(join(root, "README.md"), "# fixture\n");
      const methods: string[] = [];
      let terminal = false;
      const command = createVerifyTrainingCommand({
        repoRoot: root,
        emberLabBinary: binary,
        env: { EMBER_LAB_PIPE: "\\\\.\\pipe\\ember-lab-test" },
        sourceCommit: "a".repeat(40),
        nowMs: () => 1_000,
        callLab: async ({ method }) => {
          methods.push(method);
          if (method === "dispatch_manifest") {
            return { pid: 123, preflight_receipt_path: join(root, "foreign.json"), preflight_receipt_sha256: "b".repeat(64) };
          }
          if (method === "stop_job") {
            terminal = true;
            return { stopped: true };
          }
          if (method === "job_state") return { state: terminal ? "stopped" : "running" };
          throw new Error(`unexpected method ${method}`);
        },
        readReceipt: () => { throw new Error("must not read result receipt"); },
      });
      const result = await command.execute("", { ...mockCtx, cwd: root });
      expect(methods).toEqual(["dispatch_manifest", "stop_job", "job_state"]);
      expect(result && "message" in result ? result.message : "").toContain("preflight receipt path");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
