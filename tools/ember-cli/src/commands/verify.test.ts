// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/verify.test.ts — unit tests for the /verify command.
//
// startVerifyRunFn/getVerifyStateFn are injected so these tests never touch the real
// services/verify-watch.ts singleton or spawn a subprocess; the pipeline itself is
// covered separately in services/verify-watch.test.ts.

import { describe, it, expect } from "bun:test";
import {
  buildEnvBindingReport,
  renderEnvBindingBlock,
  renderVerifyStatus,
  createVerifyCommand,
} from "./verify.ts";
import type { CommandContext } from "../types/command-types.ts";
import { writeRootBinding, type CustodyBindingsDeps } from "../services/custody-bindings.ts";
import type { VerifyJobState } from "../services/verify-watch.ts";

const mockCtx: CommandContext = { sessionId: "test-session", mode: "test", cwd: "/repo" };

const ALL_SET_ENV: NodeJS.ProcessEnv = {
  EMBER_VERIFY_SELECTION: "/test-operator-root/goal-resume/EMBER-GOAL-RESUME.md",
  EMBER_VERIFY_IDENTITY_MANIFEST: "/test-operator-root/receipts/model-identity.json",
  EMBER_VERIFY_CHECKPOINT_MANIFEST: "/test-operator-root/receipts/checkpoint-manifest.json",
  EMBER_VERIFY_MODEL_CONFIG: "/test-operator-root/receipts/config.json",
};

function makeMemBindingsFs(initial: Record<string, string> = {}): CustodyBindingsDeps {
  const files: Record<string, string> = { ...initial };
  const dirs = new Set<string>();
  return {
    existsSync: (p: string) => p in files || dirs.has(p),
    readFileSync: (p: string) => {
      if (!(p in files)) throw new Error(`ENOENT: ${p}`);
      return files[p]!;
    },
    writeFileSync: (p: string, data: string) => {
      files[p] = data;
    },
    mkdirSync: (p: string) => {
      dirs.add(p);
    },
  };
}

// ---------------------------------------------------------------------------
// buildEnvBindingReport / renderEnvBindingBlock
// ---------------------------------------------------------------------------

describe("buildEnvBindingReport", () => {
  it("reports all four vars SET and no unresolved-leg consequence when all are present", () => {
    const report = buildEnvBindingReport(ALL_SET_ENV);
    expect(report.selection.set).toBe(true);
    expect(report.identityManifest.set).toBe(true);
    expect(report.checkpointManifest.set).toBe(true);
    expect(report.modelConfig.set).toBe(true);
    expect(report.unresolvedLegLines).toEqual([]);
  });

  it("names legs 3 and 4 as UNRESOLVED when any identity-path var is unset, and lists exactly which vars", () => {
    const report = buildEnvBindingReport({
      EMBER_VERIFY_SELECTION: "/x",
      EMBER_VERIFY_IDENTITY_MANIFEST: "/y",
      // checkpoint + model-config both unset
    });
    expect(report.unresolvedLegLines).toHaveLength(1);
    expect(report.unresolvedLegLines[0]).toContain("legs 3");
    expect(report.unresolvedLegLines[0]).toContain("legs 3");
    expect(report.unresolvedLegLines[0]).toContain("4");
    expect(report.unresolvedLegLines[0]).toContain("EMBER_VERIFY_CHECKPOINT_MANIFEST");
    expect(report.unresolvedLegLines[0]).toContain("EMBER_VERIFY_MODEL_CONFIG");
    expect(report.unresolvedLegLines[0]).not.toContain("EMBER_VERIFY_IDENTITY_MANIFEST unset");
  });

  it("treats an empty-string env var as unset, never as a set-but-blank binding", () => {
    const report = buildEnvBindingReport({ EMBER_VERIFY_SELECTION: "   " });
    expect(report.selection.set).toBe(false);
  });
});

describe("renderEnvBindingBlock", () => {
  it("always shows all four vars and the unresolved-leg consequence line, loud by construction", () => {
    const report = buildEnvBindingReport({ EMBER_VERIFY_SELECTION: "/x" });
    const rendered = renderEnvBindingBlock(report);
    expect(rendered).toContain("EMBER_VERIFY_SELECTION: SET");
    expect(rendered).toContain("EMBER_VERIFY_IDENTITY_MANIFEST: UNSET");
    expect(rendered).toContain("unresolved-leg consequences");
    expect(rendered).toContain("legs 3");
  });
});

// ---------------------------------------------------------------------------
// createVerifyCommand
// ---------------------------------------------------------------------------

describe("createVerifyCommand", () => {
  it("refuses to start when EMBER_VERIFY_SELECTION is unset, and never calls startVerifyRunFn", async () => {
    let startCalls = 0;
    const cmd = createVerifyCommand({
      repoRoot: "/repo",
      env: { EMBER_VERIFY_IDENTITY_MANIFEST: "/y" },
      bindingsFs: makeMemBindingsFs(),
      getVerifyStateFn: () => null,
      startVerifyRunFn: (() => {
        startCalls += 1;
        throw new Error("should never be called");
      }) as never,
    });
    const result = await cmd.execute("", mockCtx);
    expect(result && "message" in result ? result.message : "").toContain("EMBER_VERIFY_SELECTION is unset");
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
    expect(startCalls).toBe(0);
  });

  it("starts a job, forwards custody-bindings-store entries, and reports the env-binding block", async () => {
    const bindingsFs = makeMemBindingsFs();
    // Seed one binding through the real production write path (writeRootBinding), the
    // exact function /custody set itself calls -- proves /verify reads the SAME store,
    // not a second reimplementation.
    writeRootBinding("/repo", "public-repository", "B:/tmp/public", bindingsFs);

    let capturedDeps: unknown;
    const canned: VerifyJobState = {
      jobId: "job-xyz",
      status: "running",
      phase: "fetching-issues",
      startedAt: "2026-08-03T00:00:00.000Z",
      envBindings: buildEnvBindingReport(ALL_SET_ENV),
      stdoutTail: "",
    };
    const cmd = createVerifyCommand({
      repoRoot: "/repo",
      env: ALL_SET_ENV,
      bindingsFs,
      mintJobId: () => "job-xyz",
      getVerifyStateFn: () => null,
      startVerifyRunFn: (deps) => {
        capturedDeps = deps;
        return canned;
      },
    });
    const result = await cmd.execute("", mockCtx);
    const message = result && "message" in result ? result.message : "";
    expect(message).toContain("job-xyz started");
    expect(message).toContain("EMBER_VERIFY_SELECTION: SET");
    expect((capturedDeps as { jobDir: string }).jobDir).toContain("verify-receipts");
    expect((capturedDeps as { jobDir: string }).jobDir).toContain("job-xyz");
    expect((capturedDeps as { bindings: string[] }).bindings).toContain(
      "public-repository=B:/tmp/public",
    );
  });

  it("refuses to start a second job while one is already running", async () => {
    let startCalls = 0;
    const running: VerifyJobState = {
      jobId: "job-already",
      status: "running",
      phase: "verifying",
      startedAt: "2026-08-03T00:00:00.000Z",
      envBindings: buildEnvBindingReport(ALL_SET_ENV),
      stdoutTail: "",
    };
    const cmd = createVerifyCommand({
      repoRoot: "/repo",
      env: ALL_SET_ENV,
      bindingsFs: {},
      getVerifyStateFn: () => running,
      startVerifyRunFn: (() => {
        startCalls += 1;
        throw new Error("should never be called");
      }) as never,
    });
    const result = await cmd.execute("", mockCtx);
    const message = result && "message" in result ? result.message : "";
    expect(message).toContain("job-already is already running");
    expect(startCalls).toBe(0);
  });

  it("/verify status renders the current job snapshot including the env-binding block and leg vector", async () => {
    const done: VerifyJobState = {
      jobId: "job-done",
      status: "done",
      phase: "done",
      startedAt: "2026-08-03T00:00:00.000Z",
      finishedAt: "2026-08-03T00:05:00.000Z",
      envBindings: buildEnvBindingReport(ALL_SET_ENV),
      stdoutTail: "",
      receiptPath: "/state/verify-receipts/job-done/receipt.json",
      preservedCustodyOutputPath: "/state/verify-receipts/job-done/custody-census-output.json",
      receiptSummary: {
        ok: false,
        legs: { "1": { status: "resolved-false", title: "custody root census (operator-machine roots)" } },
      },
    };
    const cmd = createVerifyCommand({
      repoRoot: "/repo",
      env: ALL_SET_ENV,
      bindingsFs: {},
      getVerifyStateFn: () => done,
    });
    const result = await cmd.execute("status", mockCtx);
    const message = result && "message" in result ? result.message : "";
    expect(message).toContain("job-done");
    expect(message).toContain("resolved-false");
    expect(message).toContain("EMBER_VERIFY_SELECTION: SET");
    expect(message).toContain("custody-census-output.json");
  });

  it("/verify status with no prior job reports that plainly rather than crashing", async () => {
    const cmd = createVerifyCommand({
      repoRoot: "/repo",
      env: ALL_SET_ENV,
      bindingsFs: {},
      getVerifyStateFn: () => null,
    });
    const result = await cmd.execute("status", mockCtx);
    const message = result && "message" in result ? result.message : "";
    expect(message).toContain("no verification job has been run this session");
  });

  it("rejects an unknown subcommand", async () => {
    const cmd = createVerifyCommand({
      repoRoot: "/repo",
      env: ALL_SET_ENV,
      bindingsFs: {},
      getVerifyStateFn: () => null,
    });
    const result = await cmd.execute("bogus", mockCtx);
    expect(result && "exitCode" in result ? result.exitCode : undefined).toBe(1);
    expect(result && "message" in result ? result.message : "").toContain("usage:");
  });
});

// renderVerifyStatus is exercised indirectly above via createVerifyCommand's "status"
// path; this direct call proves the null case never throws when called standalone too.
describe("renderVerifyStatus", () => {
  it("never throws on a null snapshot", () => {
    expect(() => renderVerifyStatus(null)).not.toThrow();
  });
});
