// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/verify-watch.test.ts — unit tests for the /verify pipeline singleton.
//
// The subprocess runner is fully injected: no real gh or python subprocess ever runs.
// Each test writes the receipt file itself where the real verify_ember01_completion.py
// would, mirroring how the real process reports its result back to the cli.

import { describe, it, expect, beforeEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  startVerifyRun,
  getVerifyState,
  _setVerifyStateForTest,
  type EnvBindingReport,
  type EnvBindingStatus,
  type VerifyProcessResult,
} from "./verify-watch.ts";

function envSet(name: string, value = `/path/${name}`): EnvBindingStatus {
  return { envVar: name, set: true, value };
}
function envUnset(name: string): EnvBindingStatus {
  return { envVar: name, set: false };
}

function baseEnvBindings(overrides: Partial<EnvBindingReport> = {}): EnvBindingReport {
  return {
    selection: envSet("EMBER_VERIFY_SELECTION"),
    identityManifest: envSet("EMBER_VERIFY_IDENTITY_MANIFEST"),
    checkpointManifest: envSet("EMBER_VERIFY_CHECKPOINT_MANIFEST"),
    modelConfig: envSet("EMBER_VERIFY_MODEL_CONFIG"),
    unresolvedLegLines: [],
    ...overrides,
  };
}

function tmpJobDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "verify-watch-test-"));
}

async function waitForSettled(timeoutMs = 2000): Promise<void> {
  const start = Date.now();
  while (getVerifyState()?.status === "running") {
    if (Date.now() - start > timeoutMs) throw new Error("waitForSettled timed out");
    await new Promise((r) => setTimeout(r, 5));
  }
}

beforeEach(() => {
  _setVerifyStateForTest(null);
});

describe("startVerifyRun", () => {
  it("runs gh -> issue_census.py -> verify_ember01_completion.py in order with the expected args, and parses the receipt on completion", async () => {
    const jobDir = tmpJobDir();
    const calls: { executable: string; args: string[] }[] = [];
    const runProcess = async (executable: string, args: string[]): Promise<VerifyProcessResult> => {
      calls.push({ executable, args });
      if (args.includes("scripts/verify_ember01_completion.py")) {
        const receiptPath = args[args.indexOf("--receipt") + 1]!;
        fs.writeFileSync(
          receiptPath,
          JSON.stringify({
            ok: true,
            legs: { "1": { status: "resolved-true", title: "custody root census (operator-machine roots)" } },
          }),
        );
      }
      return { status: 0, stdout: "ok", stderr: "" };
    };

    const initial = startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-1",
      envBindings: baseEnvBindings(),
      bindings: ["public-repository=/x"],
      pythonBin: "python",
      ghBin: "gh",
      runProcess,
    });
    expect(initial.status).toBe("running");
    expect(initial.phase).toBe("fetching-issues");

    await waitForSettled();

    const final = getVerifyState()!;
    expect(final.status).toBe("done");
    expect(final.phase).toBe("done");
    expect(final.receiptSummary?.ok).toBe(true);
    expect(final.receiptSummary?.legs["1"]?.status).toBe("resolved-true");

    expect(calls[0]!.executable).toBe("gh");
    expect(calls[0]!.args).toContain("wordingone/ember");
    expect(calls[1]!.args).toContain("scripts/ember_01_custody/issue_census.py");

    const verifierArgs = calls[2]!.args;
    expect(verifierArgs).toContain("--run-custody");
    expect(verifierArgs).toContain("--run-seat");
    expect(verifierArgs).toContain("--preserve-custody-output");
    expect(verifierArgs).toContain("--identity-manifest");
    const bindingIndex = verifierArgs.indexOf("--binding");
    expect(bindingIndex).toBeGreaterThan(-1);
    expect(verifierArgs[bindingIndex + 1]).toBe("public-repository=/x");
  });

  it("omits --identity-manifest/--checkpoint-manifest/--model-config when those env vars are unset, never substituting a default", async () => {
    const jobDir = tmpJobDir();
    let verifierArgs: string[] = [];
    const runProcess = async (_executable: string, args: string[]): Promise<VerifyProcessResult> => {
      if (args.includes("scripts/verify_ember01_completion.py")) {
        verifierArgs = args;
        const receiptPath = args[args.indexOf("--receipt") + 1]!;
        fs.writeFileSync(receiptPath, JSON.stringify({ ok: false, legs: {} }));
        return { status: 1, stdout: "", stderr: "" };
      }
      return { status: 0, stdout: "", stderr: "" };
    };

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-2",
      envBindings: baseEnvBindings({
        identityManifest: envUnset("EMBER_VERIFY_IDENTITY_MANIFEST"),
        checkpointManifest: envUnset("EMBER_VERIFY_CHECKPOINT_MANIFEST"),
        modelConfig: envUnset("EMBER_VERIFY_MODEL_CONFIG"),
      }),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      runProcess,
    });

    await waitForSettled();
    expect(verifierArgs).not.toContain("--identity-manifest");
    expect(verifierArgs).not.toContain("--checkpoint-manifest");
    expect(verifierArgs).not.toContain("--model-config");
    // verifier exit 1 is a COMPLETED run (not-ok), never treated as an infra failure.
    expect(getVerifyState()?.status).toBe("done");
    expect(getVerifyState()?.receiptSummary?.ok).toBe(false);
  });

  it("fails the job when gh issue-list exits non-zero, and never invokes the later legs", async () => {
    const jobDir = tmpJobDir();
    const calls: string[] = [];
    const runProcess = async (executable: string): Promise<VerifyProcessResult> => {
      calls.push(executable);
      return { status: 1, stdout: "", stderr: "gh: rate limited" };
    };

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-3",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    expect(final.status).toBe("failed");
    expect(final.phase).toBe("fetching-issues");
    expect(final.error).toContain("gh: rate limited");
    expect(calls).toEqual(["gh"]);
  });

  it("fails the job when the verifier itself crashes (exit code outside {0,1})", async () => {
    const jobDir = tmpJobDir();
    const runProcess = async (_executable: string, args: string[]): Promise<VerifyProcessResult> => {
      if (args.includes("scripts/verify_ember01_completion.py")) {
        return { status: 127, stdout: "", stderr: "python: command not found" };
      }
      return { status: 0, stdout: "", stderr: "" };
    };

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-4",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    expect(final.status).toBe("failed");
    expect(final.phase).toBe("verifying");
    expect(final.error).toContain("command not found");
  });
});
