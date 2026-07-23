// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/train.test.ts — unit tests for the /train command.
//
// Both subprocess runners are fully injected: no real subprocess, CPU model,
// or training launch occurs. Default-mode tests prove only launch_packet.py is
// requested; certified-mode tests separately prove the one fixed consumer argv.

import { describe, it, expect } from "bun:test";
import { createHash } from "crypto";
import {
  CERTIFIED_LAUNCH_TIMEOUT_MS,
  PREFLIGHT_TIMEOUT_MS,
  createTrainCommand,
  type LaunchPacketRunResult,
} from "./train.ts";
import type { CommandContext } from "../types/command-types.ts";

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

/** The real launch command string launch_packet.py names on an all-green packet. */
const REAL_LAUNCH_COMMAND =
  "python tools/ember-restart-3b/certified_train_launch.py " +
  "--root . --certificate <spine-certified-declaration.json> " +
  "--declaration-ledger <declaration-ledger.jsonl> " +
  "--run-spec <certified-train-run.json>";
const EXECUTION_RECEIPT_PATH = "B:\\custody\\runner-certified-launch.json";
const ARTIFACT_ROOT = "B:\\artifacts\\run";

function validExecutionReceiptBytes(): Buffer {
  return Buffer.from(JSON.stringify({
    schema_version: "ember-certified-train-execution-v1",
    certificate_sha256: "a".repeat(64),
    run_spec_sha256: "b".repeat(64),
    public_master_sha: "c".repeat(40),
    argv: ["python", "disk_budget_runner.py"],
    exit_code: 0,
    artifact_root: ARTIFACT_ROOT,
    runner_receipt: "B:\\custody\\runner.json",
    claim_scope: {
      capability_claimed: false,
      admission_claimed: false,
      sufficient_pretraining_claimed: false,
      verified_expert_accretion_claimed: false,
      competitiveness_claimed: false,
    },
  }));
}

function validCertifiedResponse(): string {
  const bytes = validExecutionReceiptBytes();
  return JSON.stringify({
    outcome: "COMPLETED",
    execution_receipt: EXECUTION_RECEIPT_PATH,
    execution_receipt_sha256: createHash("sha256").update(bytes).digest("hex"),
    artifact_root: ARTIFACT_ROOT,
  });
}

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
        note: "scripts/timeshare_pretrain.py is EXECUTION-DENIED; training authority enters only through certified_train_launch.py.",
        command,
        library_entrypoint: "tools/ember-restart-3b/certified_train_launch.py::certify_and_execute",
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
function makeCmd(runner: (spawns: RecordedSpawn[]) => LaunchPacketRunResult) {
  const spawns: RecordedSpawn[] = [];
  const cmd = createTrainCommand({
    pythonBin: "python",
    repoRoot: "/fake/ember",
    runLaunchPacket: (executable, args) => {
      spawns.push({ executable, args });
      return runner(spawns);
    },
  });
  return { cmd, spawns };
}

function makeExecuteCmd(
  preflight: LaunchPacketRunResult,
  certified: LaunchPacketRunResult,
  executionReceiptBytes: Buffer = validExecutionReceiptBytes(),
) {
  const preflightSpawns: RecordedSpawn[] = [];
  const certifiedSpawns: RecordedSpawn[] = [];
  const cmd = createTrainCommand({
    pythonBin: "python",
    repoRoot: "/fake/ember",
    certifiedLaunchScriptPath:
      "/fake/ember/tools/ember-restart-3b/certified_train_launch.py",
    runLaunchPacket: (executable, args) => {
      preflightSpawns.push({ executable, args });
      return preflight;
    },
    runCertifiedLaunch: (executable, args) => {
      certifiedSpawns.push({ executable, args });
      return certified;
    },
    readExecutionReceipt: (path) => {
      if (path !== EXECUTION_RECEIPT_PATH) throw new Error("unexpected receipt path");
      return executionReceiptBytes;
    },
  });
  return { cmd, preflightSpawns, certifiedSpawns };
}

/** Assert the only subprocess ever spawned was the launch_packet.py preflight. */
function assertOnlyPreflightSpawned(spawns: RecordedSpawn[]): void {
  expect(spawns.length).toBe(1);
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

    it("keeps the certified canary timeout above the 15-minute run budget", () => {
      expect(PREFLIGHT_TIMEOUT_MS).toBe(600_000);
      expect(CERTIFIED_LAUNCH_TIMEOUT_MS).toBeGreaterThan(15 * 60_000);
    });
  });

  // =========================================================================
  // POSITIVE: all preflights green (exit 0) -> surface the launch command
  // =========================================================================
  describe("POSITIVE: all-green packet surfaces the launch command", () => {
    it("exit 0 + valid summary -> surfaces the fixed certified-consumer command, exitCode success, no GPU spawn", async () => {
      const { cmd, spawns } = makeCmd(() => ({ status: 0, stdout: allGreenStdout() }));

      const result = await cmd.execute("", mockCtx);

      expect(result?.type).toBe("message");
      // Success => no error exitCode.
      expect(result?.exitCode).toBeUndefined();
      // The exact launch command string is surfaced.
      expect(result?.message).toContain(REAL_LAUNCH_COMMAND);
      expect(result?.message).toContain("launch-ready");
      // It must be clear the CLI did NOT launch training.
      expect(result?.message).toContain("does NOT launch training");
      // Only the preflight ever ran; the training launch was never spawned.
      assertOnlyPreflightSpawned(spawns);
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

      const result = await cmd.execute("", mockCtx);

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
      assertOnlyPreflightSpawned(spawns);
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
      const { cmd, preflightSpawns, certifiedSpawns } = makeExecuteCmd(
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

    it("green preflight invokes exactly one certified consumer with fixed argv", async () => {
      const { cmd, preflightSpawns, certifiedSpawns } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        {
          status: 0,
          stdout: validCertifiedResponse(),
        },
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(result?.exitCode).toBeUndefined();
      expect(preflightSpawns).toHaveLength(1);
      expect(certifiedSpawns).toHaveLength(1);
      expect(certifiedSpawns[0]!.executable).toBe("python");
      expect(certifiedSpawns[0]!.args).toEqual([
        "/fake/ember/tools/ember-restart-3b/certified_train_launch.py",
        "--root",
        "/fake/ember",
        "--certificate",
        "c.json",
        "--declaration-ledger",
        "d.jsonl",
        "--run-spec",
        "r.json",
      ]);
      expect(certifiedSpawns[0]!.args.join(" ")).not.toContain(
        REAL_LAUNCH_COMMAND,
      );
      expect(result?.message).toContain(EXECUTION_RECEIPT_PATH);
      expect(result?.message).not.toContain("capability");
    });

    it("refuses a zero-exit certified response that supplies only an unverified receipt path", async () => {
      const { cmd, certifiedSpawns } = makeExecuteCmd(
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

      expect(certifiedSpawns).toHaveLength(1);
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("receipt bytes");
    });

    it("refuses an execution receipt with an empty claim boundary", async () => {
      const receipt = JSON.parse(
        validExecutionReceiptBytes().toString("utf8"),
      ) as Record<string, unknown>;
      receipt["claim_scope"] = {};
      const bytes = Buffer.from(JSON.stringify(receipt));
      const { cmd } = makeExecuteCmd(
        { status: 0, stdout: allGreenStdout() },
        {
          status: 0,
          stdout: JSON.stringify({
            outcome: "COMPLETED",
            execution_receipt: EXECUTION_RECEIPT_PATH,
            execution_receipt_sha256: createHash("sha256")
              .update(bytes)
              .digest("hex"),
            artifact_root: ARTIFACT_ROOT,
          }),
        },
        bytes,
      );

      const result = await cmd.execute(
        "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
        mockCtx,
      );

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("claim boundary");
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
