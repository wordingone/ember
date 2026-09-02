// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/train.test.ts — unit tests for the /train command.
//
// Both subprocess runners are fully injected: no real subprocess, CPU model,
// or training launch occurs. Default-mode tests prove only launch_packet.py is
// requested; certified-mode tests separately prove the one fixed consumer argv.

import { afterEach, describe, it, expect } from "bun:test";
import {
  PREFLIGHT_TIMEOUT_MS,
  _defaultCertifiedLaunchRunner,
  _defaultLaunchPacketRunner,
  createTrainCommand,
  type LaunchPacketRunResult,
  type CertifiedLaunchHandle,
} from "./train.ts";
import type { CommandContext } from "../types/command-types.ts";
import { tryDispatchSlashCommand } from "../services/slash-dispatch.ts";
import {
  getActivityFeedState,
  startActivityFeed,
} from "../services/activity-feed.ts";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const mockCtx: CommandContext = {
  sessionId: "test-session",
  mode: "test",
  cwd: "/test",
};

/** A recorded spawn: what the command asked the (mock) runner to run. */
interface RecordedSpawn {
  executable: string;
  args: string[];
}

function governedHandle(
  pid: number,
  completion: Promise<LaunchPacketRunResult>,
): CertifiedLaunchHandle {
  return {
    kind: "background",
    pid,
    jobId: "run-1-launch-1800000000000",
    preflightReceipt: "B:\\run\\launch.preflight.json",
    preflightReceiptSha256: "a".repeat(64),
    completion,
  };
}

/** The real launch command string launch_packet.py names on an all-green packet. */
const REAL_LAUNCH_COMMAND =
  "python tools/ember-restart-3b/run_vertical_slice.py semantic " +
  "--seed <launch-seed> --artifact-root ckpt/<run-id> " +
  "--receipt <manifest-bound-stream-receipt.json> --shards-root <token-shard-dir> " +
  "--tokenizer <tokenizer-path> --steps <N> --sequence-length <seq-len> " +
  "--checkpoint-interval 50 --write-budget-gib <write-budget-gib>";

/** A well-formed all-green launch_packet.py stdout (JSONL rows + summary + comments). */
function allGreenStdout(command: string = REAL_LAUNCH_COMMAND): string {
  return [
    JSON.stringify({ record: "preflight", name: "storage", status: "pass", free_disk_gib: 400 }),
    JSON.stringify({ record: "preflight", name: "resource", status: "pass", peak_gpu_mem_gib: 21.5 }),
    JSON.stringify({ record: "preflight", name: "no-sub-3B", status: "pass", computed_total_parameters: 3_100_000_000 }),
    JSON.stringify({ record: "preflight", name: "recovery", status: "pass" }),
    JSON.stringify({ record: "preflight", name: "clean-genesis", status: "pass" }),
    JSON.stringify({
      record: "launch-packet-summary",
      config: "ember-restart-3b.json",
      overall_ready: true,
      implemented_all_pass: true,
      any_deferred: false,
      named_ember02_command: {
        note: "scripts/timeshare_pretrain.py is EXECUTION-DENIED; the real governed entry is run_vertical_slice.py semantic.",
        command,
        library_entrypoint: "tools/ember-restart-3b/run_vertical_slice.py::run_semantic",
      },
    }),
    "# receipt: receipts/ember-01-launch-packet/20260721T000000Z/packet.jsonl",
    "# EMBER-02 launch command:",
    command,
  ].join("\n");
}

/** A launch_packet.py stdout for a FAILED packet (one preflight fails, exit 1). */
function failingStdout(): string {
  return [
    JSON.stringify({ record: "preflight", name: "storage", status: "pass" }),
    JSON.stringify({
      record: "preflight",
      name: "resource",
      status: "fail",
      reason: "projected peak 25.100 GiB > ceiling 24.0 GiB",
    }),
    JSON.stringify({ record: "preflight", name: "no-sub-3B", status: "pass" }),
    JSON.stringify({
      record: "launch-packet-summary",
      overall_ready: false,
      implemented_all_pass: false,
      any_deferred: false,
      named_ember02_command: null,
    }),
    "# receipt: receipts/ember-01-launch-packet/20260721T000000Z/packet.jsonl",
  ].join("\n");
}

/** Build a command + a spawn recorder that never runs a real subprocess. */
function makeCmd(
  runner: (spawns: RecordedSpawn[]) => LaunchPacketRunResult,
  repoRoot: string = "/fake/ember",
) {
  const spawns: RecordedSpawn[] = [];
  const cmd = createTrainCommand({
    pythonBin: "python",
    repoRoot,
    launchAuthorityRoot: canonicalDir(repoRoot),
    runLaunchPacket: (executable, args) => {
      spawns.push({ executable, args });
      return runner(spawns);
    },
  });
  return { cmd, spawns };
}

const authorityTestDirs = new Set<string>();

afterEach(() => {
  for (const dir of authorityTestDirs) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  authorityTestDirs.clear();
});

/** Test-only external launch-authority custody adjacent to a synthetic repo root. */
function canonicalDir(repoRoot: string): string {
  const dir = `${repoRoot}-live-launch-authority`;
  authorityTestDirs.add(dir);
  return dir;
}

/** Writes a valid launch-authority candidate packet at the
 *  test-only external launch-authority location. Content is minimal-but-well-formed --
 *  the CLI-level check is existence + parseability, not the certified consumer's own deep
 *  schema validation (that lives in certified_train_launch.py and is exercised separately). */
function writeCanonicalArtifacts(repoRoot: string): void {
  const dir = canonicalDir(repoRoot);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, "certificate.json"),
    JSON.stringify({ certificate_sha256: "a".repeat(64), certificate_legs: {} }),
  );
  fs.writeFileSync(
    path.join(dir, "declaration-ledger.jsonl"),
    [
      JSON.stringify({ schema_version: "ember-spine-declaration-ledger-row-v1", row: 0 }),
      JSON.stringify({ schema_version: "ember-spine-declaration-ledger-row-v1", row: 1 }),
    ].join("\n") + "\n",
  );
  fs.writeFileSync(
    path.join(dir, "run-spec.json"),
    JSON.stringify({ mode: "bounded-canary", steps: 1 }),
  );
  fs.writeFileSync(
    path.join(dir, "launch-authority-custody.json"),
    JSON.stringify({ schema_version: "ember-launch-authority-external-custody-v1" }) + "\n",
  );
}

function makeExecuteCmd(
  preflight: LaunchPacketRunResult,
  certified: LaunchPacketRunResult,
) {
  const preflightSpawns: RecordedSpawn[] = [];
  const certifiedSpawns: RecordedSpawn[] = [];
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-execute-"));
  authorityTestDirs.add(repoRoot);
  fs.writeFileSync(
    path.join(repoRoot, "launch-authority-custody.json"),
    JSON.stringify({ schema_version: "ember-launch-authority-external-custody-v1" }) + "\n",
  );
  const cmd = createTrainCommand({
    pythonBin: "python",
    emberLabBinary: "ember-lab",
    repoRoot,
    runLaunchPacket: (executable, args) => {
      preflightSpawns.push({ executable, args });
      return preflight;
    },
    runCertifiedLaunch: (executable, args) => {
      certifiedSpawns.push({ executable, args });
      return certified;
    },
  });
  return { cmd, preflightSpawns, certifiedSpawns, repoRoot };
}

/** Assert the only subprocess ever spawned was the launch_packet.py preflight. */
function assertOnlyPreflightSpawned(spawns: RecordedSpawn[], expectedCount = 1): void {
  expect(spawns.length).toBe(expectedCount);
  const joined = spawns[0]!.args.join(" ");
  expect(joined).toContain("launch_packet.py");
  // Load-bearing: the training/GPU launch entrypoint is NEVER spawned.
  for (const s of spawns) {
    const a = s.args.join(" ");
    expect(a).not.toContain("run_vertical_slice.py");
    expect(a).not.toContain("timeshare_pretrain.py");
    expect(a).not.toContain("run_semantic");
    expect(a).not.toContain("pretrain.py");
  }
}

describe("train command", () => {
  it("keeps the event loop live while the certified consumer is running", async () => {
    let eventLoopTurnRan = false;
    setTimeout(() => {
      eventLoopTurnRan = true;
    }, 0);

    const started = await _defaultCertifiedLaunchRunner(process.execPath, [
      "-e",
      `console.log(JSON.stringify({schema_version:"ember-lab-certified-launch-start-v1",job_id:"run-1",governed_pid:4321,preflight_receipt:"B:/run/preflight.json",preflight_receipt_sha256:"${"a".repeat(64)}"}));setTimeout(() => { console.log(JSON.stringify({schema_version:"ember-lab-certified-launch-completion-v1",exit_code:0,operational_receipt:"B:/run/receipt.json"})); console.log("trailing diagnostic"); process.exit(0); }, 100)`,
    ]);

    expect("kind" in started && started.kind === "background").toBe(true);
    if (!("kind" in started) || started.kind !== "background") {
      throw new Error("certified child did not start");
    }
    expect(started.pid).toBe(4321);
    expect(started.preflightReceiptSha256).toBe("a".repeat(64));
    await Bun.sleep(10);
    expect(eventLoopTurnRan).toBe(true);
    expect((await started.completion).status).toBe(0);
  });

  it("keeps the render loop ticking while the launch-packet preflight evaluates (regression #1487: the EARLIER preflight+custody leg, ahead of the confirm dispatch #1649 already fixed, still ran synchronously on the UI thread)", async () => {
    // screens/repl.ts drives both the busy spinner and the #413 liveness heartbeat off the
    // same primitive: a setInterval-based render tick (useInterval). A synchronous spawnSync
    // preflight call freezes the whole single JS thread for its entire duration, so that tick
    // cannot fire even once until the child process exits -- which is exactly the frozen
    // clock/heartbeat a live-run probe reproduced (2026-08-12, cold ~8.5s / warm ~2.2s,
    // recovery coinciding with the post-preflight custody banner). An off-thread preflight
    // lets the render tick keep firing throughout.
    let frameTicks = 0;
    const frameCadence = setInterval(() => {
      frameTicks += 1;
    }, 100);
    try {
      const result = await _defaultLaunchPacketRunner(process.execPath, [
        "-e",
        "setTimeout(() => process.exit(0), 2200)",
      ]);
      expect(result.status).toBe(0);
      // ~22 ticks are possible in the 2.2s window; a wide floor tolerates scheduler jitter
      // while staying far above the ~0 a blocking spawnSync call would leave this at.
      expect(frameTicks).toBeGreaterThanOrEqual(10);
    } finally {
      clearInterval(frameCadence);
    }
  });

  it("returns /train confirm after spawn while the certified consumer continues in background", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-async-confirm-"));
    try {
      writeCanonicalArtifacts(scratch);
      let finishCertifiedLaunch: ((result: LaunchPacketRunResult) => void) | undefined;
      const completion = new Promise<LaunchPacketRunResult>((resolve) => {
        finishCertifiedLaunch = resolve;
      });
      const cmd = createTrainCommand({
        repoRoot: scratch,
        launchAuthorityRoot: canonicalDir(scratch),
        runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        runCertifiedLaunch: () => governedHandle(4321, completion),
      });
      const dispatchDeps = {
        getCommands: async () => [cmd],
        findCommand: (name: string) => (name === "train" ? cmd : undefined),
      };
      const offer = await tryDispatchSlashCommand("/train", mockCtx, dispatchDeps);
      const offerId = offer?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
      expect(offerId).toBeDefined();

      let childFinished = false;
      void completion.then(() => { childFinished = true; });
      const confirmation = await tryDispatchSlashCommand(
        `/train confirm ${offerId}`,
        mockCtx,
        dispatchDeps,
      );
      expect(confirmation?.message).toContain("started in background");
      expect(confirmation?.message).toContain("governed child pid: 4321");
      expect(confirmation?.message).toContain("preflight receipt sha256");
      expect(confirmation?.message).toContain("activity feed");
      expect(childFinished).toBe(false);

      finishCertifiedLaunch?.({
        status: 0,
        stdout: JSON.stringify({ execution_receipt: "receipt.json", artifact_root: "artifacts/run" }),
      });
      await completion;
      expect(childFinished).toBe(true);
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("hands receipt-less background terminal failures to the cockpit monitor exactly once", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-background-failure-"));
    try {
      writeCanonicalArtifacts(scratch);
      for (const terminal of [
        { status: 9, stdout: "" },
        { status: null, stdout: "" },
        { status: 0, stdout: "not-a-certified-response" },
        { status: 0, stdout: JSON.stringify({ operational_receipt: "untrusted.json" }) },
        {
          status: 0,
          stdout: [
            JSON.stringify({ execution_receipt: "first.json", artifact_root: "artifacts/run" }),
            JSON.stringify({ execution_receipt: "second.json", artifact_root: "artifacts/run" }),
          ].join("\n"),
        },
      ] satisfies LaunchPacketRunResult[]) {
        let finish: ((result: LaunchPacketRunResult) => void) | undefined;
        const completion = new Promise<LaunchPacketRunResult>((resolve) => { finish = resolve; });
        const failures: Array<{ pid: number; status: number | null; message: string }> = [];
        const cmd = createTrainCommand({
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
          runCertifiedLaunch: () => governedHandle(4321, completion),
          reportCertifiedLaunchFailure: (failure) => failures.push(failure),
        });
        const dispatchDeps = {
          getCommands: async () => [cmd],
          findCommand: (name: string) => (name === "train" ? cmd : undefined),
        };
        const offer = await tryDispatchSlashCommand("/train", mockCtx, dispatchDeps);
        const offerId = offer?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
        expect(offerId).toBeDefined();
        await tryDispatchSlashCommand(`/train confirm ${offerId}`, mockCtx, dispatchDeps);

        finish?.(terminal);
        await completion;
        await Promise.resolve();

        expect(failures).toHaveLength(1);
        expect(failures[0]?.pid).toBe(4321);
        expect(failures[0]?.status).toBe(terminal.status);
        expect(failures[0]?.message).toContain("certified train consumer");
      }
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("routes a rejected certified completion through the mounted activity feed exactly once", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-background-rejection-"));
    const monitor = startActivityFeed({
      receiptsDir: path.join(scratch, "receipts"),
      totalityDir: path.join(scratch, "totality"),
      outageMarkerPath: path.join(scratch, "planned-outage.json"),
      restartLogPath: path.join(scratch, "restart-log.jsonl"),
      watchdogStatePath: path.join(scratch, "watchdog-state.json"),
      ledgerPath: path.join(scratch, "ledger.jsonl"),
    });
    try {
      writeCanonicalArtifacts(scratch);
      let rejectCompletion: ((error: Error) => void) | undefined;
      const completion = new Promise<LaunchPacketRunResult>((_resolve, reject) => {
        rejectCompletion = reject;
      });
      const cmd = createTrainCommand({
        repoRoot: scratch,
        launchAuthorityRoot: canonicalDir(scratch),
        runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        runCertifiedLaunch: () => governedHandle(2468, completion),
      });
      const dispatchDeps = {
        getCommands: async () => [cmd],
        findCommand: (name: string) => (name === "train" ? cmd : undefined),
      };
      const offer = await tryDispatchSlashCommand("/train", mockCtx, dispatchDeps);
      const offerId = offer?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
      expect(offerId).toBeDefined();
      await tryDispatchSlashCommand(`/train confirm ${offerId}`, mockCtx, dispatchDeps);

      rejectCompletion?.(new Error("child monitor transport failed"));
      await completion.catch(() => undefined);
      await Bun.sleep(20);

      const matching = getActivityFeedState().recentLines.filter((line) =>
        line.text.includes("completion monitor failed") && line.text.includes("child pid=2468"),
      );
      expect(matching).toHaveLength(1);
      const ledger = fs.readFileSync(path.join(scratch, "ledger.jsonl"), "utf8");
      expect(ledger.match(/completion monitor failed/g)).toHaveLength(1);
      expect(ledger).not.toContain("execution_receipt");
    } finally {
      monitor.stop();
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("leaves a valid certified background completion to the receipt watcher", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-background-success-"));
    try {
      writeCanonicalArtifacts(scratch);
      let finish: ((result: LaunchPacketRunResult) => void) | undefined;
      const completion = new Promise<LaunchPacketRunResult>((resolve) => { finish = resolve; });
      const failures: Array<{ pid: number; status: number | null; message: string }> = [];
      const cmd = createTrainCommand({
        repoRoot: scratch,
        launchAuthorityRoot: canonicalDir(scratch),
        runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        runCertifiedLaunch: () => governedHandle(9876, completion),
        reportCertifiedLaunchFailure: (failure) => failures.push(failure),
      });
      const dispatchDeps = {
        getCommands: async () => [cmd],
        findCommand: (name: string) => (name === "train" ? cmd : undefined),
      };
      const offer = await tryDispatchSlashCommand("/train", mockCtx, dispatchDeps);
      const offerId = offer?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
      expect(offerId).toBeDefined();
      await tryDispatchSlashCommand(`/train confirm ${offerId}`, mockCtx, dispatchDeps);

      finish?.({
        status: 0,
        stdout: [
          JSON.stringify({ schema_version: "ember-lab-certified-launch-start-v1" }),
          JSON.stringify({ schema_version: "ember-lab-certified-launch-completion-v1", exit_code: 0, operational_receipt: "receipt.json" }),
          "trailing diagnostic",
        ].join("\n"),
      });
      await completion;
      await Promise.resolve();

      expect(failures).toEqual([]);
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("routes the displayed /train confirm instruction through the production slash dispatcher", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-dispatch-"));
    try {
      writeCanonicalArtifacts(scratch);
      const certifiedSpawns: RecordedSpawn[] = [];
      const cmd = createTrainCommand({
        pythonBin: "python",
        repoRoot: scratch,
        launchAuthorityRoot: canonicalDir(scratch),
        emberLabBinary: path.join(scratch, "runtime", "ember-lab", "target", "release", "ember-lab"),
        runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        runCertifiedLaunch: (executable, args) => {
          certifiedSpawns.push({ executable, args });
          return {
            status: 0,
            stdout: JSON.stringify({
              execution_receipt: "receipt.json",
              artifact_root: "artifacts/run",
            }),
          };
        },
      });
      const dispatchDeps = {
        getCommands: async () => [cmd],
        findCommand: (name: string) => (name === "train" ? cmd : undefined),
      };

      const offerResult = await tryDispatchSlashCommand("/train", mockCtx, dispatchDeps);
      const offerId = offerResult?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
      expect(offerId).toBeDefined();
      expect(offerResult?.message).toContain(`type "/train confirm ${offerId}"`);

      // Bare text is a model turn, never a slash-command confirmation.
      expect(
        await tryDispatchSlashCommand(`confirm ${offerId}`, mockCtx, dispatchDeps),
      ).toBeNull();

      const confirmResult = await tryDispatchSlashCommand(
        `/train confirm ${offerId}`,
        mockCtx,
        dispatchDeps,
      );
      expect(confirmResult?.exitCode).toBeUndefined();
      expect(confirmResult?.message).toContain("receipt.json");
      expect(certifiedSpawns).toHaveLength(1);
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  it("binds each offer to the session that minted it without spending it on foreign confirmation", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-session-"));
    try {
      writeCanonicalArtifacts(scratch);
      const certifiedSpawns: RecordedSpawn[] = [];
      const cmd = createTrainCommand({
        pythonBin: "python",
        repoRoot: scratch,
        launchAuthorityRoot: canonicalDir(scratch),
        emberLabBinary: path.join(scratch, "runtime", "ember-lab", "target", "release", "ember-lab"),
        runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        runCertifiedLaunch: (executable, args) => {
          certifiedSpawns.push({ executable, args });
          return {
            status: 0,
            stdout: JSON.stringify({
              execution_receipt: "receipt.json",
              artifact_root: "artifacts/run",
            }),
          };
        },
      });
      const dispatchDeps = {
        getCommands: async () => [cmd],
        findCommand: (name: string) => (name === "train" ? cmd : undefined),
      };
      const mintingCtx = { ...mockCtx, sessionId: "minting-session" };
      const foreignCtx = { ...mockCtx, sessionId: "foreign-session" };

      const offerResult = await tryDispatchSlashCommand(
        "/train",
        mintingCtx,
        dispatchDeps,
      );
      const offerId = offerResult?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
      expect(offerId).toBeDefined();

      const foreignResult = await tryDispatchSlashCommand(
        `/train confirm ${offerId}`,
        foreignCtx,
        dispatchDeps,
      );
      expect(foreignResult?.exitCode).toBe(1);
      expect(foreignResult?.message).toContain("not valid for this session");
      expect(certifiedSpawns).toHaveLength(0);

      const ownerResult = await tryDispatchSlashCommand(
        `/train confirm ${offerId}`,
        mintingCtx,
        dispatchDeps,
      );
      expect(ownerResult?.exitCode).toBeUndefined();
      expect(ownerResult?.message).toContain("receipt.json");
      expect(certifiedSpawns).toHaveLength(1);
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  // =========================================================================
  // Registration
  // =========================================================================
  describe("registration", () => {
    it("has name 'train' and is enabled", () => {
      const cmd = createTrainCommand();
      expect(cmd.name).toBe("train");
      expect(cmd.isEnabled()).toBe(true);
      expect(cmd.description.toLowerCase()).toContain("train");
    });

    it("keeps only the CPU preflight timeout in the cockpit", () => {
      expect(PREFLIGHT_TIMEOUT_MS).toBe(600_000);
    });
  });

  // =========================================================================
  // POSITIVE: all preflights green (exit 0) -> surface the launch command
  // =========================================================================
  describe("POSITIVE: all-green packet + resolved artifacts offers the launch", () => {
    it("resolves the default launch authority only from explicit external custody", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-external-authority-"));
      try {
        const externalRoot = canonicalDir(scratch);
        writeCanonicalArtifacts(scratch);

        const cmd = createTrainCommand({
          repoRoot: scratch,
          launchAuthorityRoot: externalRoot,
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        });

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBeUndefined();
        expect(result?.message).toContain(path.join(externalRoot, "certificate.json"));
        expect(result?.message).not.toContain(
          path.join(scratch, "receipts", "ember-02-launch-authority"),
        );
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("refuses the committed historical record when external custody is absent", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-no-live-authority-"));
      try {
        const historical = path.join(scratch, "receipts", "ember-02-launch-authority");
        fs.mkdirSync(historical, { recursive: true });
        fs.writeFileSync(path.join(historical, "certificate.json"), "{}\n");
        fs.writeFileSync(path.join(historical, "declaration-ledger.jsonl"), "{}\n");
        fs.writeFileSync(path.join(historical, "run-spec.json"), "{}\n");
        const cmd = createTrainCommand({
          repoRoot: scratch,
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        });

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).toContain("EMBER_LAUNCH_AUTHORITY_ROOT is required");
        expect(result?.message).toContain("historical only");
        expect(result?.message).toContain("No offer minted");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("refuses a live launch-authority root contained by the repository", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-contained-authority-"));
      try {
        const contained = path.join(scratch, "live", "run-1506", "launch-authority");
        fs.mkdirSync(contained, { recursive: true });
        const cmd = createTrainCommand({
          repoRoot: scratch,
          launchAuthorityRoot: contained,
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        });

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).toContain("must be outside the Ember repository");
        expect(result?.message).toContain("No offer minted");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("exit 0 + valid summary + canonical artifacts present -> mints an OFFER instead of a paste-able command, no GPU spawn", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-offer-"));
      try {
        writeCanonicalArtifacts(scratch);
        const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.type).toBe("message");
        // Success => no error exitCode.
        expect(result?.exitCode).toBeUndefined();
        // The command is offered through the confirm-only membrane, not handed over as
        // text to paste -- the raw command string is no longer surfaced by default.
        expect(result?.message).not.toContain(REAL_LAUNCH_COMMAND);
        expect(result?.message).toContain("launch-ready");
        expect(result?.message).toMatch(/OFFER \S+ action=train-launch/);
        expect(result?.message).toContain('type "/train confirm');
        // Only the preflight ever ran; the training launch was never spawned.
        assertOnlyPreflightSpawned(spawns);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("spawns launch_packet.py with --config pointing at the ember-restart-3b config", async () => {
      const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }));

      await cmd.execute("", mockCtx);

      expect(spawns.length).toBe(1);
      expect(spawns[0]!.executable).toBe("python");
      const args = spawns[0]!.args;
      expect(args.some((a) => a.includes("launch_packet.py"))).toBe(true);
      expect(args).toContain("--config");
      expect(args.some((a) => a.includes("ember-restart-3b.json"))).toBe(true);
    });
  });

  // =========================================================================
  // NEGATIVE: nonzero exit (a preflight failed) -> fail closed
  // =========================================================================
  describe("NEGATIVE: preflight failure fails closed", () => {
    it("nonzero exit -> fail closed, non-zero exitCode, NO launch command, reasons surfaced", async () => {
      const { cmd, spawns } = makeCmd(() => ({ status: 1, stdout: failingStdout() }));

      const result = await cmd.execute("", { ...mockCtx, sessionId: "legacy-null-failure-session" });

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("BLOCKED");
      // Fail-closed: the launch command string is NEVER present on failure.
      expect(result?.message).not.toContain("run_vertical_slice.py");
      expect(result?.message).toContain("No launch command surfaced");
      // The specific failing preflight + reason is surfaced to the operator.
      expect(result?.message).toContain("resource");
      expect(result?.message).toContain("ceiling");
      // Only the preflight ran; nothing was launched.
      assertOnlyPreflightSpawned(spawns);
    });
  });

  // =========================================================================
  // NEGATIVE: malformed / empty JSON -> fail closed
  // =========================================================================
  describe("NEGATIVE: unparseable/empty output fails closed", () => {
    it("exit 0 but empty stdout -> fail closed (no summary to validate), NO launch command", async () => {
      const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout: "" }));

      const result = await cmd.execute("", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("BLOCKED");
      expect(result?.message).not.toContain("run_vertical_slice.py");
      assertOnlyPreflightSpawned(spawns);
    });

    it("exit 0 but malformed JSON stdout -> fail closed, NO launch command", async () => {
      const { cmd, spawns } = makeCmd(() => ({
        status: 0,
        stdout: "not json at all {{{\n# garbage\n}}} broken",
      }));

      const result = await cmd.execute("", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("BLOCKED");
      expect(result?.message).not.toContain("run_vertical_slice.py");
      assertOnlyPreflightSpawned(spawns);
    });

    it("exit 0 with a summary but overall_ready=false -> fail closed (defensive), NO launch command", async () => {
      const stdout = [
        JSON.stringify({
          record: "launch-packet-summary",
          overall_ready: false,
          named_ember02_command: null,
        }),
      ].join("\n");
      const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout }));

      const result = await cmd.execute("", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).not.toContain("run_vertical_slice.py");
      assertOnlyPreflightSpawned(spawns);
    });

    it("exit 0 with overall_ready=true but a missing command string -> fail closed (never surface an unvalidated command)", async () => {
      const stdout = [
        JSON.stringify({
          record: "launch-packet-summary",
          overall_ready: true,
          named_ember02_command: { note: "n", library_entrypoint: "e" }, // no `command`
        }),
      ].join("\n");
      const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout }));

      const result = await cmd.execute("", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("BLOCKED");
      assertOnlyPreflightSpawned(spawns);
    });
  });

  // =========================================================================
  // NEGATIVE: runner reports a crash (status null) -> fail closed
  // =========================================================================
  describe("NEGATIVE: runner crash fails closed", () => {
    it("status null (subprocess never ran / crashed / timed out) -> fail closed, NO launch command", async () => {
      const { cmd, spawns } = makeCmd(() => ({ status: null, stdout: "" }));

      const result = await cmd.execute("", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("BLOCKED");
      expect(result?.message).not.toContain("run_vertical_slice.py");
      expect(spawns).toHaveLength(2);
      expect(spawns[1]).toEqual(spawns[0]);
    });

    it("a runner that THROWS is caught and fails closed (never crashes the command)", async () => {
      const cmd = createTrainCommand({
        pythonBin: "python",
        repoRoot: "/fake/ember",
        runLaunchPacket: () => {
          throw new Error("spawnSync exploded");
        },
      });

      const result = await cmd.execute("", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("BLOCKED");
      expect(result?.message).not.toContain("run_vertical_slice.py");
    });

    it("fresh-session status:null retries once with identical spawn identity and then mints an OFFER when green", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-null-retry-green-"));
      try {
        writeCanonicalArtifacts(scratch);
        const spawns: RecordedSpawn[] = [];
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: (executable, args) => {
            spawns.push({ executable, args });
            return spawns.length === 1
              ? { status: null, stdout: "" }
              : { status: 0, stdout: allGreenStdout() };
          },
        });

        const result = await cmd.execute("", { ...mockCtx, sessionId: "null-retry-green-session" });

        expect(result?.exitCode).toBeUndefined();
        expect(result?.message).toContain("OFFER");
        expect(spawns).toHaveLength(2);
        expect(spawns[1]).toEqual(spawns[0]);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("fresh-session status:null then status:null refuses after exactly one attributed retry", async () => {
      const spawns: RecordedSpawn[] = [];
      const cmd = createTrainCommand({
        pythonBin: "python",
        repoRoot: "/fake/ember",
        runLaunchPacket: (executable, args) => {
          spawns.push({ executable, args });
          return { status: null, stdout: "" };
        },
      });

      const result = await cmd.execute("", { ...mockCtx, sessionId: "null-retry-null-session" });

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("attempt 1");
      expect(result?.message).toContain("attempt 2");
      expect(result?.message).toContain("No launch command surfaced.");
      expect(spawns).toHaveLength(2);
      expect(spawns[1]).toEqual(spawns[0]);
    });

    it("shares the one-null-retry budget across command instances in one session", async () => {
      const spawns: RecordedSpawn[] = [];
      const makeSessionCommand = () =>
        createTrainCommand({
          pythonBin: "python",
          repoRoot: "/fake/ember",
          runLaunchPacket: (executable, args) => {
            spawns.push({ executable, args });
            return { status: null, stdout: "" };
          },
        });
      const first = makeSessionCommand();
      const second = makeSessionCommand();
      const sessionCtx = { ...mockCtx, sessionId: "shared-null-retry-budget-session" };

      const firstResult = await first.execute("", sessionCtx);
      const secondResult = await second.execute("", sessionCtx);

      expect(firstResult?.message).toContain("attempt 2");
      expect(secondResult?.message).not.toContain("attempt 2");
      expect(spawns).toHaveLength(3);
    });

    it("does not consume the null-retry budget after an earlier green preflight", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-green-then-null-"));
      try {
        writeCanonicalArtifacts(scratch);
        const spawns: RecordedSpawn[] = [];
        const results: LaunchPacketRunResult[] = [
          { status: 0, stdout: allGreenStdout() },
          { status: null, stdout: "" },
          { status: 0, stdout: allGreenStdout() },
        ];
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: (executable, args) => {
            spawns.push({ executable, args });
            return results.shift()!;
          },
        });

        const session = { ...mockCtx, sessionId: "green-then-null-session" };
        await cmd.execute("", session);
        const second = await cmd.execute("", session);

        expect(second?.message).toContain("OFFER");
        expect(spawns).toHaveLength(3);
        expect(spawns[2]).toEqual(spawns[1]);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("does not retry or invoke the certified consumer for a null execute preflight", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-execute-null-"));
      try {
        writeCanonicalArtifacts(scratch);
        const preflightSpawns: RecordedSpawn[] = [];
        const certifiedSpawns: RecordedSpawn[] = [];
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          runLaunchPacket: (executable, args) => {
            preflightSpawns.push({ executable, args });
            return { status: null, stdout: "" };
          },
          runCertifiedLaunch: (executable, args) => {
            certifiedSpawns.push({ executable, args });
            return { kind: "terminal", status: 0, stdout: "{}" };
          },
        });

        const result = await cmd.execute(
          "--execute --certificate cert.json --declaration-ledger ledger.json --run-spec spec.json",
          { ...mockCtx, sessionId: "execute-null-session" },
        );

        expect(result?.exitCode).toBe(1);
        expect(result?.message).toContain("BLOCKED");
        expect(preflightSpawns).toHaveLength(1);
        expect(certifiedSpawns).toHaveLength(0);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("nonzero preflight never consumes the null retry or invokes a second spawn", async () => {
      const spawns: RecordedSpawn[] = [];
      const cmd = createTrainCommand({
        pythonBin: "python",
        repoRoot: "/fake/ember",
        runLaunchPacket: (executable, args) => {
          spawns.push({ executable, args });
          return { status: 1, stdout: failingStdout() };
        },
      });

      const result = await cmd.execute("", { ...mockCtx, sessionId: "nonzero-no-retry-session" });

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("preflight FAILED");
      expect(spawns).toHaveLength(1);
    });
  });

  // =========================================================================
  // Load-bearing default-mode invariant: no training process is spawned.
  // =========================================================================
  describe("default-mode invariant: never invokes a training process", () => {
    it("across default success and failure paths, only launch_packet.py is requested", async () => {
      const scenarios: Array<() => LaunchPacketRunResult> = [
        () => ({ status: 0, stdout: allGreenStdout() }),
        () => ({ status: 1, stdout: failingStdout() }),
        () => ({ status: 0, stdout: "" }),
        () => ({ status: null, stdout: "" }),
      ];
      for (const scenario of scenarios) {
        const { cmd, spawns } = makeCmd(scenario);
        await cmd.execute("", mockCtx);
        assertOnlyPreflightSpawned(spawns);
      }
    });
  });

  describe("certified execution mode", () => {
    it("requires all three explicit authority paths before any spawn", async () => {
      const { cmd, preflightSpawns, certifiedSpawns, repoRoot } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 0, stdout: "{}" },
      );

      const result = await cmd.execute(
        "--execute --certificate certificate.json",
        mockCtx,
      );

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("--declaration-ledger");
      expect(preflightSpawns).toHaveLength(0);
      expect(certifiedSpawns).toHaveLength(0);
    });

    it("green preflight invokes exactly one Ember Lab composer with fixed authority argv", async () => {
      const { cmd, preflightSpawns, certifiedSpawns, repoRoot } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        {
          status: 0,
          stdout: JSON.stringify({
            outcome: "COMPLETED",
            execution_receipt: "receipt.json",
            artifact_root: "artifacts/run",
          }),
        },
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(result?.exitCode).toBeUndefined();
      expect(preflightSpawns).toHaveLength(1);
      expect(certifiedSpawns).toHaveLength(1);
      expect(certifiedSpawns[0]!.executable).toBe("ember-lab");
      expect(certifiedSpawns[0]!.args).toEqual([
        "launch",
        "--root",
        repoRoot,
        "--certificate",
        "c.json",
        "--declaration-ledger",
        "d.jsonl",
        "--run-spec",
        "r.json",
        "--custody-receipt-sha256",
        expect.stringMatching(/^[0-9a-f]{64}$/),
      ]);
      expect(certifiedSpawns[0]!.args.join(" ")).not.toContain(
        REAL_LAUNCH_COMMAND,
      );
      expect(result?.message).toContain("receipt.json");
      expect(result?.message).not.toContain("capability");
    });

    it("registers COMPLETED when a noisy child's log lines precede the JSON handshake (#1408)", async () => {
      // Regression: even though the fixed consumer now redirects its child's
      // stdout away from its own (issue #1408), the cockpit must still fail
      // open on any leftover noise ahead of the handshake line rather than
      // failing the whole parse -- a successful certified launch must never
      // be reported as an error.
      const noisyStdout = [
        "epoch 1/10 loss=0.42",
        "epoch 2/10 loss=0.31",
        "checkpoint saved: checkpoint-vertical-slice-seed-830001",
        JSON.stringify({
          outcome: "COMPLETED",
          execution_receipt: "receipt.json",
          artifact_root: "artifacts/run",
        }),
      ].join("\n");
      const { cmd, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 0, stdout: noisyStdout },
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(certifiedSpawns).toHaveLength(1);
      expect(result?.exitCode).toBeUndefined();
      expect(result?.message).toContain("certified bounded canary process completed");
      expect(result?.message).toContain("receipt.json");
      expect(result?.message).not.toContain(
        "without a valid execution receipt response",
      );
    });

    it("preflight failure prevents certified consumer execution", async () => {
      const { cmd, preflightSpawns, certifiedSpawns } = makeExecuteCmd(
        { status: 1, stdout: failingStdout() },
        { status: 0, stdout: "{}" },
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(result?.exitCode).toBe(1);
      expect(preflightSpawns).toHaveLength(1);
      expect(certifiedSpawns).toHaveLength(0);
    });

    it("certified consumer failure propagates without surfacing launch text", async () => {
      const { cmd, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 23, stdout: "scope exceeds certificate: max_records" },
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(result?.exitCode).toBe(23);
      expect(certifiedSpawns).toHaveLength(1);
      expect(result?.message).toContain("scope exceeds certificate");
      expect(result?.message).not.toContain(REAL_LAUNCH_COMMAND);
    });

    it("unknown and duplicate options fail before either spawn", async () => {
      for (const args of [
        "--execute --unknown x --certificate c --declaration-ledger d --run-spec r",
        "--execute --execute --certificate c --declaration-ledger d --run-spec r",
      ]) {
        const { cmd, preflightSpawns, certifiedSpawns } = makeExecuteCmd(
          { status: 0, stdout: allGreenStdout() },
          { status: 0, stdout: "{}" },
        );
        const result = await cmd.execute(args, mockCtx);
        expect(result?.exitCode).toBe(1);
        expect(preflightSpawns).toHaveLength(0);
        expect(certifiedSpawns).toHaveLength(0);
      }
    });
  });
});

// =============================================================================
// SPEC-train-launch-operability-v1.md acceptance map -- O1-O4, C1-C8, S1-S5, over-closure.
// Every row here is a row in that frozen spec's acceptance map; the row id is in the test
// name so a reviewer can bind test <-> row directly.
// =============================================================================
describe("acceptance map: train-launch-operability v1", () => {
  describe("order invariants", () => {
    it("O1: the preflight runs before any artifact resolution -- resolution never precedes it", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-o1-"));
      try {
        // Deliberately do NOT pre-write the canonical artifacts. The mock runner writes
        // them itself, the instant it is invoked, then reports green. If resolution ran
        // BEFORE the preflight, the artifacts would not exist yet and the command would
        // fail closed on "absent" -- so an OFFER here is only possible if resolution ran
        // strictly after this runner executed.
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => {
            writeCanonicalArtifacts(scratch);
            return { status: 0, stdout: allGreenStdout() };
          },
        });

        const result = await cmd.execute("", mockCtx);

        expect(result?.message).toMatch(/OFFER \S+/);
        expect(result?.exitCode).toBeUndefined();
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("O2: an OFFER is emitted only after preflight green AND all three artifacts resolved", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-o2-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.rmSync(path.join(canonicalDir(scratch), "run-spec.json"));
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.message).not.toContain("OFFER");
        expect(result?.exitCode).toBe(1);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("O3: confirm invokes the consumer only for an id minted by a green preflight in this session", async () => {
      const { cmd, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 0, stdout: JSON.stringify({ execution_receipt: "r.json", artifact_root: "a/" }) },
      );
      const result = await cmd.execute("confirm never-minted-1", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(certifiedSpawns).toHaveLength(0);
      expect(result?.message.toLowerCase()).toContain("no outstanding");
    });

    it("O4: preflight red short-circuits -- no resolution, no offer, no consumer invocation", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-o4-"));
      try {
        // Artifacts ARE present and valid; if resolution ran despite the red preflight,
        // it would succeed and (wrongly) mint an OFFER. It must not.
        writeCanonicalArtifacts(scratch);
        const { cmd } = makeCmd(() => ({ status: 1, stdout: failingStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).toContain("BLOCKED");
        expect(result?.message).not.toContain("OFFER");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("O5: an offer minted through one command instance is confirmable through another (spine-panel.ts:695 builds a fresh instance per drive call with no injected dep)", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-o5-"));
      try {
        writeCanonicalArtifacts(scratch);
        const certifiedSpawns: RecordedSpawn[] = [];

        // Two SEPARATE createTrainCommand() calls over the same repoRoot -- exactly what
        // components/spine-panel.ts:695/698 does on every drive() call for the "train"
        // key, since no trainCommand dep is normally injected there.
        const mintingInstance = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        });
        const confirmingInstance = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
          runCertifiedLaunch: (executable, args) => {
            certifiedSpawns.push({ executable, args });
            return {
              status: 0,
              stdout: JSON.stringify({ execution_receipt: "r.json", artifact_root: "a/" }),
            };
          },
        });

        const offerResult = await mintingInstance.execute("", mockCtx);
        const offerId = offerResult?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
        expect(offerId).toBeDefined();

        const confirmResult = await confirmingInstance.execute(`confirm ${offerId}`, mockCtx);

        expect(confirmResult?.exitCode).toBeUndefined();
        expect(confirmResult?.message.toLowerCase()).not.toContain("no outstanding");
        expect(certifiedSpawns).toHaveLength(1);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("O6: two instances minting concurrently produce distinct offer ids", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-o6-"));
      try {
        writeCanonicalArtifacts(scratch);
        const instanceA = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        });
        const instanceB = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
        });

        const [resultA, resultB] = await Promise.all([
          instanceA.execute("", mockCtx),
          instanceB.execute("", mockCtx),
        ]);
        const idA = resultA?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
        const idB = resultB?.message.match(/OFFER (\S+) action=train-launch/)?.[1];

        expect(idA).toBeDefined();
        expect(idB).toBeDefined();
        expect(idA).not.toBe(idB);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });
  });

  describe("conjunction rows", () => {
    it("C1: preflight green + all three artifacts present -> OFFER emitted, no consumer invoked yet", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c1-"));
      try {
        writeCanonicalArtifacts(scratch);
        const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.message).toMatch(/OFFER \S+ action=train-launch/);
        expect(result?.exitCode).toBeUndefined();
        assertOnlyPreflightSpawned(spawns);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C2: preflight green + certificate missing -> fail closed naming the certificate", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c2-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.rmSync(path.join(canonicalDir(scratch), "certificate.json"));
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).not.toContain("OFFER");
        expect(result?.message.toLowerCase()).toContain("certificate");
        expect(result?.message).not.toContain("declaration ledger:");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C3: preflight green + ledger missing -> fail closed naming the ledger", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c3-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.rmSync(path.join(canonicalDir(scratch), "declaration-ledger.jsonl"));
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).not.toContain("OFFER");
        expect(result?.message.toLowerCase()).toContain("declaration ledger");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C4: preflight green + run-spec missing -> fail closed naming the run spec", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c4-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.rmSync(path.join(canonicalDir(scratch), "run-spec.json"));
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).not.toContain("OFFER");
        expect(result?.message.toLowerCase()).toContain("run spec");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C5: preflight red + all three artifacts present -> fail closed on the preflight; no offer", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c5-"));
      try {
        writeCanonicalArtifacts(scratch);
        const { cmd } = makeCmd(() => ({ status: 1, stdout: failingStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).toContain("BLOCKED");
        expect(result?.message).not.toContain("OFFER");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C6: preflight red + artifacts missing -> fail closed on the preflight; no offer", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c6-"));
      try {
        const { cmd } = makeCmd(() => ({ status: 1, stdout: failingStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).toContain("BLOCKED");
        expect(result?.message).not.toContain("OFFER");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C7: preflight green, artifacts present, but the runner throws -> fail closed, no offer left behind", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-c7-"));
      try {
        writeCanonicalArtifacts(scratch);
        const certifiedSpawns: RecordedSpawn[] = [];
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
          runCertifiedLaunch: (executable, args) => {
            certifiedSpawns.push({ executable, args });
            throw new Error("spawnSync exploded");
          },
        });

        const offerResult = await cmd.execute("", mockCtx);
        const offerId = offerResult?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
        expect(offerId).toBeDefined();

        const confirmResult = await cmd.execute(`confirm ${offerId}`, mockCtx);
        expect(confirmResult?.exitCode).toBe(1);
        expect(certifiedSpawns).toHaveLength(1);

        // The offer is spent -- a throw during confirm never leaves a reusable offer.
        const secondConfirm = await cmd.execute(`confirm ${offerId}`, mockCtx);
        expect(secondConfirm?.message.toLowerCase()).toContain("no outstanding");
        expect(certifiedSpawns).toHaveLength(1);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("C8: --execute with explicit paths + preflight green -> consumer invoked with the explicit paths, canonical resolution not consulted", async () => {
      // repoRoot does not exist on disk at all -- canonical resolution (fs reads under
      // repoRoot/receipts/ember-02-launch-authority) would throw/fail if it were consulted.
      // The explicit --execute path must never touch the default custody root.
      const { cmd, preflightSpawns, certifiedSpawns, repoRoot } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        {
          status: 0,
          stdout: JSON.stringify({ execution_receipt: "receipt.json", artifact_root: "artifacts/run" }),
        },
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(result?.exitCode).toBeUndefined();
      expect(preflightSpawns).toHaveLength(1);
      expect(certifiedSpawns[0]!.args).toEqual([
        "launch",
        "--root",
        repoRoot,
        "--certificate",
        "c.json",
        "--declaration-ledger",
        "d.jsonl",
        "--run-spec",
        "r.json",
        "--custody-receipt-sha256",
        expect.stringMatching(/^[0-9a-f]{64}$/),
      ]);
    });
  });

  describe("skip-path rows", () => {
    it("S1: confirm <id> with no prior /train this session -> no consumer invocation; unknown-offer message", async () => {
      const { cmd, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 0, stdout: "{}" },
      );

      const result = await cmd.execute("confirm train-1", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(certifiedSpawns).toHaveLength(0);
      expect(result?.message.toLowerCase()).toContain("no outstanding");
    });

    it("S2: confirm <id> for a spent id -> no second invocation", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-s2-"));
      try {
        writeCanonicalArtifacts(scratch);
        const certifiedSpawns: RecordedSpawn[] = [];
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
          runCertifiedLaunch: (executable, args) => {
            certifiedSpawns.push({ executable, args });
            return { status: 0, stdout: JSON.stringify({ execution_receipt: "r.json", artifact_root: "a/" }) };
          },
        });

        const offerResult = await cmd.execute("", mockCtx);
        const offerId = offerResult?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
        expect(offerId).toBeDefined();

        const first = await cmd.execute(`confirm ${offerId}`, mockCtx);
        expect(first?.exitCode).toBeUndefined();
        expect(certifiedSpawns).toHaveLength(1);

        const second = await cmd.execute(`confirm ${offerId}`, mockCtx);
        expect(second?.exitCode).toBe(1);
        expect(second?.message.toLowerCase()).toContain("no outstanding");
        expect(certifiedSpawns).toHaveLength(1);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("S3: confirm with a malformed or absent id -> no action", async () => {
      const { cmd, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 0, stdout: "{}" },
      );

      for (const args of ["confirm", "confirm  ", "confirm a b"]) {
        const result = await cmd.execute(args, mockCtx);
        expect(certifiedSpawns).toHaveLength(0);
        expect(result?.exitCode).toBe(1);
      }
    });

    it("S4: an artifact path exists but is an empty file -> fail closed, existence is not validity", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-s4-empty-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.writeFileSync(path.join(canonicalDir(scratch), "certificate.json"), "");
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).not.toContain("OFFER");
        expect(result?.message.toLowerCase()).toContain("certificate");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("S4: an artifact path exists but is unparseable -> fail closed, existence is not validity", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-s4-unparse-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.writeFileSync(path.join(canonicalDir(scratch), "run-spec.json"), "{not json at all");
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).not.toContain("OFFER");
        expect(result?.message.toLowerCase()).toContain("run spec");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("S4: a declaration-ledger.jsonl with one unparseable line -> fail closed", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-s4-jsonl-"));
      try {
        writeCanonicalArtifacts(scratch);
        fs.writeFileSync(
          path.join(canonicalDir(scratch), "declaration-ledger.jsonl"),
          JSON.stringify({ row: 0 }) + "\nnot json\n",
        );
        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);

        const result = await cmd.execute("", mockCtx);

        expect(result?.exitCode).toBe(1);
        expect(result?.message).not.toContain("OFFER");
        expect(result?.message.toLowerCase()).toContain("declaration ledger");
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });

    it("S5: --execute with only some of the three flags -> the existing usage error, unchanged", async () => {
      const { cmd, preflightSpawns, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        { status: 0, stdout: "{}" },
      );

      const result = await cmd.execute("--execute --certificate certificate.json", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("--declaration-ledger");
      expect(preflightSpawns).toHaveLength(0);
      expect(certifiedSpawns).toHaveLength(0);
    });
  });

  describe("over-closure guard", () => {
    it("an unmodified real artifact set at the canonical paths produces an OFFER, not a false failure", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-overclosure-"));
      try {
        // Deliberately richer / more realistic content than the minimal C1 fixture, to
        // catch a cure that fails closed on anything it doesn't recognize.
        const dir = canonicalDir(scratch);
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(
          path.join(dir, "certificate.json"),
          JSON.stringify(
            {
              certificate_sha256: "b".repeat(64),
              certificate_legs: { storage: "pass", resource: "pass" },
              authorized_scope: { mode: "bounded-canary", max_records: 100 },
            },
            null,
            2,
          ),
        );
        fs.writeFileSync(
          path.join(dir, "declaration-ledger.jsonl"),
          [
            JSON.stringify({
              schema_version: "ember-spine-declaration-ledger-row-v1",
              event: "declared",
              role: "operator",
              certificate_sha256: "b".repeat(64),
            }),
            JSON.stringify({
              schema_version: "ember-spine-declaration-ledger-row-v1",
              event: "countersigned",
              role: "witness",
              certificate_sha256: "b".repeat(64),
            }),
          ].join("\n") + "\n",
        );
        fs.writeFileSync(
          path.join(dir, "run-spec.json"),
          JSON.stringify({ mode: "bounded-canary", steps: 10, sequence_length: 4096 }, null, 2),
        );
        fs.writeFileSync(
          path.join(dir, "launch-authority-custody.json"),
          JSON.stringify({ schema_version: "ember-launch-authority-external-custody-v1" }) + "\n",
        );

        const { cmd } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }), scratch);
        const result = await cmd.execute("", mockCtx);

        expect(result?.message).toMatch(/OFFER \S+ action=train-launch/);
        expect(result?.exitCode).toBeUndefined();
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });
  });

  describe("full happy path: OFFER -> confirm invokes the real fixed consumer", () => {
    it("confirm <id> invokes the same Ember Lab composer as --execute with resolved canonical paths", async () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-confirm-"));
      try {
        writeCanonicalArtifacts(scratch);
        const certifiedSpawns: RecordedSpawn[] = [];
        const cmd = createTrainCommand({
          pythonBin: "python",
          repoRoot: scratch,
          launchAuthorityRoot: canonicalDir(scratch),
          emberLabBinary: path.join(scratch, "runtime", "ember-lab", "target", "release", "ember-lab"),
          runLaunchPacket: () => ({ status: 0, stdout: allGreenStdout() }),
          runCertifiedLaunch: (executable, args) => {
            certifiedSpawns.push({ executable, args });
            return {
              status: 0,
              stdout: JSON.stringify({ execution_receipt: "receipt.json", artifact_root: "artifacts/run" }),
            };
          },
        });

        const offerResult = await cmd.execute("", mockCtx);
        const offerId = offerResult?.message.match(/OFFER (\S+) action=train-launch/)?.[1];
        expect(offerId).toBeDefined();

        const confirmResult = await cmd.execute(`confirm ${offerId}`, mockCtx);

        expect(confirmResult?.exitCode).toBeUndefined();
        expect(confirmResult?.message).toContain("receipt.json");
        expect(certifiedSpawns).toHaveLength(1);
        expect(certifiedSpawns[0]!.args).toEqual([
          "launch",
          "--root",
          scratch,
          "--certificate",
          path.join(canonicalDir(scratch), "certificate.json"),
          "--declaration-ledger",
          path.join(canonicalDir(scratch), "declaration-ledger.jsonl"),
          "--run-spec",
          path.join(canonicalDir(scratch), "run-spec.json"),
          "--custody-receipt-sha256",
          expect.stringMatching(/^[0-9a-f]{64}$/),
        ]);
        // The raw named launch command string is never present in argv or the response.
        expect(certifiedSpawns[0]!.args.join(" ")).not.toContain(REAL_LAUNCH_COMMAND);
      } finally {
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    });
  });
});

describe("/train source-byte authority", () => {
  it("runs launch_packet.py and its config from the selected linked worktree, not its main checkout", async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-train-source-root-"));
    try {
      const mainRoot = path.join(scratch, "main");
      const worktreeRoot = path.join(scratch, "worktree");
      fs.mkdirSync(path.join(mainRoot, ".git", "worktrees", "lane"), {
        recursive: true,
      });
      fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });
      fs.mkdirSync(path.join(mainRoot, "docs", "domains", "governance", "authority"), {
        recursive: true,
      });
      fs.writeFileSync(path.join(mainRoot, "docs/domains/governance/authority/GOAL.md"), "# main\n");
      fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), {
        recursive: true,
      });
      fs.mkdirSync(path.join(worktreeRoot, "docs", "domains", "governance", "authority"), {
        recursive: true,
      });
      fs.writeFileSync(path.join(worktreeRoot, "docs/domains/governance/authority/GOAL.md"), "# worktree\n");
      fs.writeFileSync(
        path.join(worktreeRoot, ".git"),
        `gitdir: ${path.join(mainRoot, ".git", "worktrees", "lane")}\n`,
      );
      // Not the subject of this test, but required for the default (no --execute) mode
      // to reach a success exitCode now that it offers through the canonical
      // launch-authority resolution instead of surfacing a paste-able command string.
      writeCanonicalArtifacts(worktreeRoot);

      const spawns: RecordedSpawn[] = [];
      const cmd = createTrainCommand({
        pythonBin: "python",
        launchAuthorityRoot: canonicalDir(worktreeRoot),
        runLaunchPacket: (executable, args) => {
          spawns.push({ executable, args });
          return { status: 0, stdout: allGreenStdout() };
        },
      });
      const result = await cmd.execute("", { ...mockCtx, cwd: worktreeRoot });

      expect(result?.exitCode).toBeUndefined();
      expect(spawns).toHaveLength(1);
      expect(spawns[0]!.args).toEqual([
        path.join(
          worktreeRoot,
          "tools",
          "ember-restart-3b",
          "launch_packet.py",
        ),
        "--config",
        path.join(worktreeRoot, "configs", "ember-restart-3b.json"),
      ]);
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });
});
