// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import xtermHeadless from "@xterm/headless";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import {
  LIFECYCLE_ACTIONS,
  inspectLifecycleSurface,
  validateLifecycleReceipt,
  type LifecycleReceipt,
} from "./lifecycle-smoke.ts";

const GIT_COMMIT = "a".repeat(40);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);
const SHA_D = "d".repeat(64);

function validReceipt(): LifecycleReceipt {
  return {
    schema_version: "ember-cli-lifecycle-smoke/v2",
    evidence_class: "LIVE_COMPILED_BINARY_CONPTY",
    source_commit: GIT_COMMIT,
    binary: {
      artifact: "tools/ember-cli/dist/ember.exe",
      sha256_before: SHA_B,
      sha256_after: SHA_B,
    },
    reproducible_rebuild: {
      sha256: SHA_B,
      builder_basename: "bun.exe",
      builder_sha256_before: SHA_C,
      builder_sha256_after: SHA_C,
      builder_version: "1.2.3",
    },
    readiness: {
      marker: "EMBER_READY;v1",
      observed: true,
      elapsed_ms: 17,
      frame_sha256: SHA_D,
    },
    actions: LIFECYCLE_ACTIONS.map((action, index) => {
      const durable = ["pause", "resume", "save", "terminate"].includes(action);
      const command = action === "terminate" ? "stop" : action;
      const outcome =
        action === "train" ? "PREFLIGHT_ONLY"
          : action === "reload" ? "PASS"
            : action === "continue" ? "MISSING"
              : "PASS";
      const effectKind =
        action === "launch" ? "observable-readiness"
          : action === "train" ? "preflight-only"
            : action === "observe" ? "observable-product-effect"
              : action === "save" ? "durable-artifact-publication"
                : action === "reload" ? "observable-product-effect"
                : durable ? "durable-control-append"
                  : "observable-refusal";
      const deltaSha = String(index + 31).padStart(64, "0");
      return {
        action,
        ordinal: index + 1,
        input_sha256: String(index + 1).padStart(64, "0"),
        before_frame_sha256: String(index + 11).padStart(64, "0"),
        after_frame_sha256: String(index + 21).padStart(64, "0"),
        effect_evidence_sha256: deltaSha,
        effect_kind: effectKind,
        outcome,
        output_excerpt:
          action === "save"
            ? `modern governed sparse checkpoint saved: ${"a".repeat(64)}`
            : action === "reload"
              ? `checkpoint loaded; checkpoint selected: ${"a".repeat(64)}`
              : action === "continue"
                ? "Unknown command: /continue"
                : action === "train"
                  ? "This command does NOT launch training."
                  : `${action} effect observed`,
        state_evidence: durable
          ? {
            artifact: `receipts/ember-cli-lifecycle-smoke/action-${index + 1}.state`,
            before_exists: action !== "pause" && action !== "save",
            before_sha256:
              action === "pause" || action === "save"
                ? null
                : String(index + 41).padStart(64, "0"),
            after_exists: true,
            after_sha256: String(index + 51).padStart(64, "0"),
            delta_sha256: deltaSha,
            command: action === "save" ? null : command,
            run_id: action === "save" ? null : "smoke-run",
          }
          : null,
        frame_artifact: `receipts/ember-cli-lifecycle-smoke/action-${index + 1}.frame.txt`,
        delta_artifact: `receipts/ember-cli-lifecycle-smoke/action-${index + 1}.delta.txt`,
        delta_sha256: String(index + 61).padStart(64, "0"),
        repair_item: outcome === "PASS"
          ? null
          : `EMBER-CLI-${action.toUpperCase()}-OPERABILITY`,
      };
    }),
    termination: {
      explicit_requested: true,
      clean_exit_observed: true,
      clean_exit_wait_ms: 125,
      forced_cleanup_required: false,
      forced_cleanup_attempted: false,
      final_exit_observed: true,
      survivors: 0,
    },
    artifacts: {
      receipt: "receipts/ember-cli-lifecycle-smoke/receipt.json",
      diagnostics: "receipts/ember-cli-lifecycle-smoke/diagnostics",
    },
    operator_contract_mapping:
      "compiled launch -> /train -> /watch -> /finetune -> /model -> unregistered resume",
    accepted_instrument_run: true,
    claim_boundary: {
      model_capability: false,
      training_quality: false,
      checkpoint_sufficiency: false,
      benchmark: false,
    },
  };
}

const expected = {
  sourceCommit: GIT_COMMIT,
  binarySha256: SHA_B,
  builderSha256: SHA_C,
};

describe("validateLifecycleReceipt", () => {
  test("accepts the exact ordered effect-bearing lifecycle", () => {
    expect(validateLifecycleReceipt(validReceipt(), expected)).toEqual({
      ok: true,
      action_count: 9,
    });
  });

  test("refuses a successful modern save whose emitted bundle does not reload", () => {
    const receipt = validReceipt();
    const save = receipt.actions.find((row) => row.action === "save")!;
    save.output_excerpt = `modern governed sparse checkpoint saved: ${"a".repeat(64)}`;
    const reload = receipt.actions.find((row) => row.action === "reload")!;
    reload.outcome = "REFUSED";
    reload.effect_kind = "observable-refusal";
    reload.output_excerpt = "error: failed to load checkpoint";
    reload.repair_item = "EMBER-CLI-SAVE-RELOAD-COMPATIBILITY";

    expect(() => validateLifecycleReceipt(receipt, expected))
      .toThrow(/successful checkpoint save did not reload/i);
  });

  test("accepts a truthful paired save/reload refusal when no selected identity exists", () => {
    const receipt = validReceipt();
    const save = receipt.actions.find((row) => row.action === "save")!;
    save.outcome = "REFUSED";
    save.effect_kind = "observable-refusal";
    save.output_excerpt =
      "error: failed to save checkpoint: no durable selected owned checkpoint is available";
    save.repair_item = "EMBER-CLI-SAVE-RELOAD-COMPATIBILITY";
    save.state_evidence = null;
    const reload = receipt.actions.find((row) => row.action === "reload")!;
    reload.outcome = "REFUSED";
    reload.effect_kind = "observable-refusal";
    reload.output_excerpt =
      "error: failed to load checkpoint: checkpoint directory is missing or unreadable";
    reload.repair_item = "EMBER-CLI-SAVE-RELOAD-COMPATIBILITY";
    const continued = receipt.actions.find((row) => row.action === "continue")!;
    continued.outcome = "MISSING";
    continued.effect_kind = "observable-refusal";
    continued.output_excerpt = "Unknown command: /continue";
    continued.repair_item = "EMBER-CLI-CONTINUE-PRODUCTION-WIRING";

    expect(validateLifecycleReceipt(receipt, expected)).toEqual({
      ok: true,
      action_count: 9,
    });
  });

  test("rehashes public frame, delta, and durable state artifacts", async () => {
    const contract = await import("./lifecycle-smoke.ts");
    expect(contract.validateLifecycleActionArtifacts).toBeFunction();
    const validateLifecycleActionArtifacts =
      contract.validateLifecycleActionArtifacts!;
    const receipt = validReceipt();
    const launch = receipt.actions.find((row) => row.action === "launch")!;
    launch.after_frame_sha256 =
      "3c04009b8f1d7bee2e496be23c08761744b26c499ca15f3c125643be85c86e0c";
    launch.delta_sha256 =
      "673953e0ad7fc53247f4feadc2c2d4506396840d1f8796526f48d47333ac7652";
    expect(validateLifecycleActionArtifacts(launch, (artifact) => {
      if (artifact === launch.frame_artifact) return Buffer.from("frame\n");
      if (artifact === launch.delta_artifact) return Buffer.from("delta\n");
      throw new Error("unexpected artifact");
    })).toEqual({ ok: true });
    expect(() => validateLifecycleActionArtifacts(launch, (artifact) => {
      if (artifact === launch.frame_artifact) return Buffer.from("forged\n");
      return Buffer.from("delta\n");
    })).toThrow("frame artifact");

    const pause = receipt.actions.find((row) => row.action === "pause")!;
    pause.after_frame_sha256 = launch.after_frame_sha256;
    pause.delta_sha256 = launch.delta_sha256;
    pause.effect_evidence_sha256 =
      "927489cb2fcdb32e302713f6a720397868b71dd2128c734181983f367d622c24";
    pause.state_evidence!.delta_sha256 = pause.effect_evidence_sha256;
    expect(validateLifecycleActionArtifacts(pause, (artifact) => {
      if (artifact === pause.frame_artifact) return Buffer.from("frame\n");
      if (artifact === pause.delta_artifact) return Buffer.from("delta\n");
      if (artifact === pause.state_evidence!.artifact) return Buffer.from("state\n");
      throw new Error("unexpected artifact");
    })).toEqual({ ok: true });
  });

  test("refuses NO_EFFECT because it is an instrument failure", () => {
    const receipt = validReceipt();
    const continued = receipt.actions.find((row) => row.action === "continue")!;
    continued.outcome = "NO_EFFECT";
    expect(() => validateLifecycleReceipt(receipt, expected)).toThrow(
      "instrument",
    );
  });

  test("refuses synthetic or wrong durable state evidence", () => {
    const sameBytes = validReceipt();
    const pause = sameBytes.actions.find((row) => row.action === "pause")!;
    pause.state_evidence!.before_exists = true;
    pause.state_evidence!.before_sha256 = pause.state_evidence!.after_sha256;
    expect(() => validateLifecycleReceipt(sameBytes, expected)).toThrow(
      "durable state",
    );

    const wrongCommand = validReceipt();
    const resumed = wrongCommand.actions.find((row) => row.action === "resume")!;
    resumed.state_evidence!.command = "pause";
    expect(() => validateLifecycleReceipt(wrongCommand, expected)).toThrow(
      "control command",
    );
  });

  test("refuses lexical-only credit", () => {
    const receipt = validReceipt();
    (receipt.actions[0] as unknown as { effect_kind: string }).effect_kind =
      "command-echo";
    expect(() => validateLifecycleReceipt(receipt, expected)).toThrow("effect");
  });

  test("refuses sleep-only readiness", () => {
    const receipt = validReceipt();
    receipt.readiness.observed = false;
    expect(() => validateLifecycleReceipt(receipt, expected)).toThrow("readiness");
  });

  test("refuses a missing frame delta", () => {
    const receipt = validReceipt();
    receipt.actions[3]!.after_frame_sha256 =
      receipt.actions[3]!.before_frame_sha256;
    expect(() => validateLifecycleReceipt(receipt, expected)).toThrow("frame delta");
  });

  test("refuses skipped or reordered verbs", () => {
    const skipped = validReceipt();
    skipped.actions.splice(4, 1);
    expect(() => validateLifecycleReceipt(skipped, expected)).toThrow("ordered actions");

    const reordered = validReceipt();
    [reordered.actions[1], reordered.actions[2]] = [
      reordered.actions[2]!,
      reordered.actions[1]!,
    ];
    expect(() => validateLifecycleReceipt(reordered, expected)).toThrow("ordered actions");
  });

  test("refuses a leaked child", () => {
    const receipt = validReceipt();
    receipt.termination.survivors = 1;
    expect(() => validateLifecycleReceipt(receipt, expected)).toThrow("termination");

    const incoherent = validReceipt();
    incoherent.termination.clean_exit_observed = false;
    expect(() => validateLifecycleReceipt(incoherent, expected)).toThrow(
      "termination",
    );

    const forced = validReceipt();
    forced.termination.clean_exit_observed = false;
    forced.termination.forced_cleanup_required = true;
    forced.termination.forced_cleanup_attempted = true;
    expect(() => validateLifecycleReceipt(forced, expected)).toThrow(
      "clean operator exit",
    );
  });

  test("measures clean exit before deciding whether forced cleanup is required", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.terminateLifecycleChild).toBeFunction();
    let forced = 0;
    let observed = false;
    const result = await driver.terminateLifecycleChild!(
      () => undefined,
      () => observed,
      () => { forced += 1; },
      async () => { observed = true; },
      (() => { let now = 0; return () => (now += 25); })(),
      100,
    );
    expect(result.clean_exit_observed).toBe(true);
    expect(result.forced_cleanup_required).toBe(false);
    expect(result.forced_cleanup_attempted).toBe(false);
    expect(result.final_exit_observed).toBe(true);
    expect(result.survivors).toBe(0);
    expect(forced).toBe(0);

    let forcedAfterTimeout = 0;
    let observedAfterTimeout = false;
    const forcedResult = await driver.terminateLifecycleChild!(
      () => undefined,
      () => observedAfterTimeout,
      () => {
        forcedAfterTimeout += 1;
        observedAfterTimeout = true;
      },
      async () => undefined,
      (() => { let now = 0; return () => (now += 25); })(),
      100,
    );
    expect(forcedResult.clean_exit_observed).toBe(false);
    expect(forcedResult.forced_cleanup_required).toBe(true);
    expect(forcedResult.forced_cleanup_attempted).toBe(true);
    expect(forcedResult.final_exit_observed).toBe(true);
    expect(forcedResult.survivors).toBe(0);
    expect(forcedAfterTimeout).toBe(1);
  });

  test("does not write to a lifecycle child whose exit was already observed", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    let exitRequests = 0;
    let forced = 0;
    const result = await driver.terminateLifecycleChild!(
      () => { exitRequests += 1; },
      () => true,
      () => { forced += 1; },
    );
    expect(exitRequests).toBe(0);
    expect(forced).toBe(0);
    expect(result).toEqual({
      explicit_requested: true,
      clean_exit_observed: true,
      clean_exit_wait_ms: 0,
      forced_cleanup_required: false,
      forced_cleanup_attempted: false,
      final_exit_observed: true,
      survivors: 0,
    });
  });

  test("waits for the exit event when ConPTY closes its socket first", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    let observed = false;
    let forced = 0;
    const socketClosed = Object.assign(new Error("Socket is closed"), {
      code: "ERR_SOCKET_CLOSED",
    });
    const result = await driver.terminateLifecycleChild!(
      () => { throw socketClosed; },
      () => observed,
      () => { forced += 1; },
      async () => { observed = true; },
      (() => { let now = 0; return () => (now += 25); })(),
      100,
    );
    expect(forced).toBe(0);
    expect(result.clean_exit_observed).toBe(true);
    expect(result.forced_cleanup_required).toBe(false);
    expect(result.final_exit_observed).toBe(true);
    expect(result.survivors).toBe(0);
  });

  test("classifies only the Windows closed-socket race as benign", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.isBenignConptyClosureError({
      code: "ERR_SOCKET_CLOSED",
    })).toBe(true);
    expect(driver.isBenignConptyClosureError({ code: "EIO" })).toBe(false);
    expect(driver.isBenignConptyClosureError(new Error("Socket is closed")))
      .toBe(false);
  });

  test("binds the Windows node-pty input stream rather than its output emitter", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    let bound: ((error: unknown) => void) | undefined;
    const fakePty = {
      _agent: {
        _inSocket: {
          on: (event: string, listener: (error: unknown) => void) => {
            expect(event).toBe("error");
            bound = listener;
          },
        },
      },
    };
    const observed: unknown[] = [];
    driver.bindConptyInputErrorFence(fakePty as never, (error) => observed.push(error));
    bound?.({ code: "ERR_SOCKET_CLOSED" });
    expect(observed).toEqual([{ code: "ERR_SOCKET_CLOSED" }]);
    expect(() => driver.bindConptyInputErrorFence({} as never, () => {}))
      .toThrow("input socket is unavailable");
  });

  test("refuses forged source, binary, rebuild, or builder bindings", () => {
    for (const mutate of [
      (r: LifecycleReceipt) => { r.source_commit = SHA_D; },
      (r: LifecycleReceipt) => { r.binary.sha256_after = SHA_D; },
      (r: LifecycleReceipt) => { r.reproducible_rebuild.sha256 = SHA_D; },
      (r: LifecycleReceipt) => { r.reproducible_rebuild.builder_sha256_after = SHA_D; },
    ]) {
      const receipt = validReceipt();
      mutate(receipt);
      expect(() => validateLifecycleReceipt(receipt, expected)).toThrow();
    }
  });
});

describe("inspectLifecycleSurface", () => {
  test("reports the live command-registry gap instead of substituting a fixture", async () => {
    const report = inspectLifecycleSurface([
      { name: "train", aliases: [] },
      { name: "watch", aliases: [] },
      { name: "finetune", aliases: ["ft"] },
      { name: "model", aliases: [] },
    ]);
    expect(report.map((row) => row.action)).toEqual([...LIFECYCLE_ACTIONS]);
    expect(report.find((row) => row.action === "continue")).toEqual({
      action: "continue",
      input: "/continue",
      command: "resume",
      status: "MISSING",
    });
    expect(report.filter((row) => row.status === "MISSING")).toHaveLength(1);
  });
});

describe("compiled lifecycle driver host", () => {
  test("loads under Node and reaches its own closed argument boundary", () => {
    const located = spawnSync("node", ["--version"], {
      encoding: "utf8",
      windowsHide: true,
    });
    expect(located.status).toBe(0);
    const driver = join(import.meta.dir, "lifecycle-smoke-driver.ts");
    const result = spawnSync(
      "node",
      ["--experimental-strip-types", driver],
      { cwd: join(import.meta.dir, ".."), encoding: "utf8", windowsHide: true },
    );

    expect(result.status).toBe(1);
    expect(result.stderr).toContain(
      "--binary, --out-dir, and --receipt-path are required",
    );
    expect(result.stderr).not.toContain("Named export 'Terminal' not found");
    expect(result.stderr).not.toContain("ERR_SOCKET_CLOSED");
  }, 15_000);

  test("checkpoint fixture is driven through a repo-relative source path", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.actionInputs).toBeFunction();
    const repoRoot = "D:\\a\\ember\\ember";
    const inputs = driver.actionInputs!("C:\\temp\\ember-smoke", repoRoot);

    expect(inputs.save).not.toContain(repoRoot);
    expect(inputs.save).toMatch(
      /--source tools[\\/]ember-cli[\\/]src[\\/]commands[\\/]__fixtures__[\\/]model-identity/,
    );
  });
});

describe("compiled lifecycle action completion", () => {
  test("does not grant completion while the submitted command remains in the prompt", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.completedPromptFrame).toBeFunction();
    const completedPromptFrame = driver.completedPromptFrame!;
    expect(driver.slashCommandNeedsSecondEnter).toBeFunction();

    const row = (content: string): string => `│${content.padEnd(18)}│`;
    const pending = [
      `╭${"─".repeat(18)}╮`,
      row(" ❯ /train"),
      row(" ○ observe"),
      `╰${"─".repeat(18)}╯`,
    ];
    const cleared = [pending[0]!, row(" ❯ "), row(" ○ observe"), pending[3]!];

    expect(completedPromptFrame(pending, 20, "/train")).toBe(false);
    expect(completedPromptFrame(cleared, 20, "/train")).toBe(true);
    expect(completedPromptFrame([...pending, " ".repeat(20), ...cleared], 20, "/train"))
      .toBe(true);
    const paddedCleared = cleared.map((line) => line.padEnd(30));
    expect(completedPromptFrame(paddedCleared, 30, "/train")).toBe(true);
    expect(driver.slashCommandNeedsSecondEnter!(pending, 20, "/train")).toBe(true);
    expect(driver.slashCommandNeedsSecondEnter!(cleared, 20, "/train")).toBe(false);
  });

  test("types prompt input as ordered keystrokes with bounded inter-key pacing", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.writePromptInput).toBeFunction();
    const writes: string[] = [];
    const waits: number[] = [];

    await driver.writePromptInput!(
      { write: (value: string) => writes.push(value) },
      "/train",
      20,
      async (milliseconds: number) => { waits.push(milliseconds); },
    );

    expect(writes).toEqual(["/", "t", "r", "a", "i", "n"]);
    expect(waits).toEqual([20, 20, 20, 20, 20]);
  });

  test("isolates the current action output from prior full-screen repaint history", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.actionLocalDelta).toBeFunction();

    const continued = driver.actionLocalDelta!(
      "error: failed to load checkpoint\r\n/continue\r\nUnknown command: /continue\r\n",
      "/continue",
    );
    expect(continued).toContain("Unknown command: /continue");
    expect(continued).not.toContain("failed to load checkpoint");

    const saved = driver.actionLocalDelta!(
      `/model checkpoint save C:\\tmp\\saved\r\nmodern governed sparse checkpoint saved: ${"a".repeat(64)}\r\n`,
      "/model checkpoint save C:\\tmp\\saved",
    );
    expect(saved).toContain("modern governed sparse checkpoint saved");
  });

  test("derives an action-local visible delta without unchanged viewport history", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.actionVisibleDelta).toBeFunction();
    expect(driver.actionVisibleDelta!(
      "stale prior error\nunchanged dashboard\n",
      "unchanged dashboard\nnew action result\n",
    )).toBe("new action result");
    expect(driver.actionVisibleDelta!(
      "same row\nsame row\n",
      "same row\nsame row\nnew row\n",
    )).toBe("new row");
  });

  test("classifies the rendered action and retains the exact modern save result", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.classifyActionFrame).toBeFunction();
    expect(driver.actionOutputExcerpt).toBeFunction();

    expect(driver.classifyActionFrame!(
      "continue",
      "Unknown command: /continue",
    )).toBe("MISSING");    expect(driver.classifyActionFrame!(
      "continue",
      "No resumable session selected.",
    )).toBe("REFUSED");
    expect(driver.actionCompletionObserved!(
      "continue",
      "No resumable session selected.",
      "",
    )).toBe(true);
    expect(driver.classifyActionFrame!(
      "continue",
      "cursor repaint without command result",
    )).toBe("NO_EFFECT");
    expect(driver.classifyActionFrame!(
      "train",
      [
        "launch-packet: all preflights GREEN -- EMBER-02 is launch-ready.",
        "This command does NOT launch training.",
      ].join("\n"),
    )).toBe("PREFLIGHT_ONLY");
    expect(driver.classifyActionFrame!(
      "train",
      "launch-packet: all preflights GREEN, but the launch-authority artifacts are not all present",
    )).toBe("REFUSED");
    expect(driver.classifyActionFrame!(
      "terminate",
      "stop run=smoke-run",
    )).toBe("PASS");

    const quote = `modern governed sparse checkpoint saved: ${"a".repeat(64)}`;
    expect(driver.actionOutputExcerpt!("save", "modern governed sparse checkpoint saved", `${quote}${"x".repeat(3000)}`))
      .toBe(quote);
    expect(driver.actionOutputExcerpt!(
      "continue",
      "error: failed to load checkpoint: stale prior viewport row",
      "Unknown command: /continue",
    )).toBe("Unknown command: /continue");
    expect(driver.actionOutputExcerpt!(
      "terminate",
      quote,
      "stop run=smoke-run",
    )).toBe("stop run=smoke-run");
    expect(driver.actionOutputExcerpt!(
      "train",
      "",
      [
        "launch-packet: all preflights GREEN -- EMBER-02 is launch-ready.",
        "This command does NOT launch training.",
      ].join("\n"),
    )).toBe([
      "launch-packet: all preflights GREEN -- EMBER-02 is launch-ready.",
      "This command does NOT launch training.",
    ].join("\n"));

    expect(driver.classifyActionEvidence).toBeFunction();
    expect(driver.classifyActionEvidence!(
      "observe",
      "",
      [
        "error: launch-packet preflight FAILED -- stale prior action",
        "watching state/ember-telemetry.jsonl",
      ].join("\n"),
    )).toEqual({
      status: "PASS",
      excerpt: "watching state/ember-telemetry.jsonl",
    });

    expect(driver.classifyActionEvidence!(
      "train",
      "",
      [
        "launch-packet: all preflights GREEN -- EMBER-02 is launch-ready.",
        "This command does NOT launch training.",
      ].join("\n"),
    ).status).toBe("PREFLIGHT_ONLY");

    expect(driver.saveActionCompletionObserved).toBeFunction();
    expect(driver.saveActionCompletionObserved!(
      "prompt cleared after save submission",
      "cursor repaint without save result",
    )).toBe(false);
    expect(driver.saveActionCompletionObserved!(
      "prompt cleared",
      `modern governed sparse checkpoint saved: ${"a".repeat(64)}`,
    )).toBe(true);
    expect(driver.saveActionCompletionObserved!(
      "prompt cleared",
      "error: failed to save checkpoint: identity refused",
    )).toBe(true);

    expect(driver.actionCompletionObserved).toBeFunction();
    expect(driver.actionCompletionObserved!(
      "observe",
      "unrelated fixed-viewport repaint",
      "cursor repaint without watch result",
    )).toBe(false);
    expect(driver.actionCompletionObserved!(
      "observe",
      "fixed viewport",
      "watching state/ember-telemetry.jsonl",
    )).toBe(true);
    expect(driver.actionCompletionObserved!(
      "pause",
      "fixed viewport",
      "resume run=smoke-run",
    )).toBe(false);
    expect(driver.actionCompletionObserved!(
      "pause",
      "fixed viewport",
      "pause run=smoke-run",
    )).toBe(true);
    expect(driver.actionCompletionObserved!(
      "save",
      "fixed viewport",
      "error: failed to save checkpoint: identity refused",
    )).toBe(true);

    expect(driver.redactPublicText).toBeFunction();
    const backslashProbe = `${String.fromCharCode(66, 58)}\\M\\ember`;
    const slashProbe = `${String.fromCharCode(67, 58)}/tmp/private`;
    const redacted = driver.redactPublicText!(`${backslashProbe} ${slashProbe}`, []);
    expect(redacted).not.toContain(backslashProbe);
    expect(redacted).not.toContain(slashProbe);

    expect(driver.attemptDetail).toBeFunction();
    expect(driver.attemptDetail!("PASS")).toBe(
      "effect-bearing frame delta observed",
    );
    expect(driver.attemptDetail!("PREFLIGHT_ONLY")).toBe(
      "preflight-only product outcome observed",
    );
    expect(driver.attemptDetail!("REFUSED")).toBe("operator surface refused");

    expect(driver.publicFailureFrame).toBeFunction();
    const failedFrame = driver.publicFailureFrame!(
      `failure under ${backslashProbe} and ${slashProbe}`,
      [backslashProbe, slashProbe],
    );
    expect(failedFrame).not.toContain(backslashProbe);
    expect(failedFrame).not.toContain(slashProbe);
    expect(failedFrame).toContain("<HOST_PATH>");
  });

  test("submits a second Enter only while the slash command remains pending", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.submitSecondEnterIfNeeded).toBeFunction();

    const pendingWrites: string[] = [];
    driver.submitSecondEnterIfNeeded!(
      { write: (value: string) => pendingWrites.push(value) },
      "/train",
      [],
      20,
      () => true,
    );
    expect(pendingWrites).toEqual(["\r"]);

    const clearedWrites: string[] = [];
    driver.submitSecondEnterIfNeeded!(
      { write: (value: string) => clearedWrites.push(value) },
      "/train",
      [],
      20,
      () => false,
    );
    expect(clearedWrites).toEqual([]);
  });

  test("routes lifecycle actions through the production operator pipe", () => {
    const source = readFileSync(
      join(import.meta.dir, "lifecycle-smoke-driver.ts"),
      "utf8",
    );
    expect(source).toContain("operatorPipeName");
    expect(source).toContain("writeOperatorLine(child.pid, input)");
  });

  test("interactive cleanup terminates the packaged process after releasing terminal ownership", () => {
    const source = readFileSync(
      join(import.meta.dir, "..", "entrypoints", "process-entry.ts"),
      "utf8",
    );
    const cleanup = source.slice(source.indexOf("await exitPromise;"));
    expect(cleanup).toContain("root.unmount();");
    expect(cleanup).toContain("stopBridge();\n  doExitMain(0);");
  });
});

describe("compiled lifecycle durable state evidence", () => {
  test("binds one exact append-only control row to before, after, and delta bytes", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.deriveControlAppendState).toBeFunction();
    const appended =
      '{"verb":"pause","runId":"smoke-run","ts":"2026-07-25T00:00:00.000Z"}\n';
    expect(driver.deriveControlAppendState!(
      null,
      Buffer.from(appended, "utf8"),
      "pause",
      "receipts/ember-cli-lifecycle-smoke/action-4-pause.state.jsonl",
    )).toEqual({
      artifact: "receipts/ember-cli-lifecycle-smoke/action-4-pause.state.jsonl",
      before_exists: false,
      before_sha256: null,
      after_exists: true,
      after_sha256: "e631817fae79a8dc1775d1cf9e51ec7efe32bfe36f8bd9aba0dd996dfa2cba87",
      delta_sha256: "e631817fae79a8dc1775d1cf9e51ec7efe32bfe36f8bd9aba0dd996dfa2cba87",
      command: "pause",
      run_id: "smoke-run",
    });
  });

  test("refuses changed prefixes, extra rows, or the wrong control command", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    const pause =
      '{"verb":"pause","runId":"smoke-run","ts":"2026-07-25T00:00:00.000Z"}\n';
    const resume =
      '{"verb":"resume","runId":"smoke-run","ts":"2026-07-25T00:00:01.000Z"}\n';
    const artifact =
      "receipts/ember-cli-lifecycle-smoke/action-4-pause.state.jsonl";
    expect(() => driver.deriveControlAppendState!(
      Buffer.from(pause),
      Buffer.from(resume),
      "pause",
      artifact,
    )).toThrow("append-only");
    expect(() => driver.deriveControlAppendState!(
      null,
      Buffer.from(`${pause}${resume}`),
      "pause",
      artifact,
    )).toThrow("exactly one");
    expect(() => driver.deriveControlAppendState!(
      null,
      Buffer.from(resume),
      "pause",
      artifact,
    )).toThrow("control command");
  });

  test("binds publication bytes without inventing a prior state", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.derivePublicationState).toBeFunction();
    expect(driver.derivePublicationState!(
      null,
      Buffer.from("{}\n", "utf8"),
      "receipts/ember-cli-lifecycle-smoke/action-6-save.state.json",
    )).toEqual({
      artifact: "receipts/ember-cli-lifecycle-smoke/action-6-save.state.json",
      before_exists: false,
      before_sha256: null,
      after_exists: true,
      after_sha256: "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356",
      delta_sha256: "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356",
      command: null,
      run_id: null,
    });
  });
});

describe("compiled lifecycle visible frame", () => {
  test("reads the active viewport after terminal output scrolls", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.visibleFrameLines).toBeFunction();
    const { Terminal } = xtermHeadless;
    const terminal = new Terminal({ cols: 12, rows: 3, allowProposedApi: true });
    try {
      await new Promise<void>((done) => {
        terminal.write("one\r\ntwo\r\nthree\r\nfour\r\nfive", done);
      });
      const lines = driver.visibleFrameLines!(terminal);
      expect(lines.some((line) => line.includes("five"))).toBe(true);
      expect(lines.some((line) => line.includes("one"))).toBe(false);
      expect(lines.every((line) => line.length === 12)).toBe(true);
    } finally {
      terminal.dispose();
    }
  });
});

describe("compiled lifecycle workflow authority", () => {
  test("checks out the immutable event head and installs the identity-validator runtime", () => {
    const workflow = readFileSync(
      join(import.meta.dir, "..", "..", "..", "..", ".github", "workflows", "cli-windows-lifecycle-e2e.yml"),
      "utf8",
    );

    expect(workflow).toContain("ref: ${{ github.event.pull_request.head.sha || github.sha }}");
    expect(workflow).toContain("uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97");
    expect(workflow).toContain("python-version: \"3.12\"");
    expect(workflow).toContain("Install pinned validator dependencies");
    expect(workflow).toContain("build-tools/cli-hardening-matrix.ts");
    expect(workflow).toContain("receipts/ember-cli-hardening/receipt.json");
    expect(workflow).toContain(
      'python -m pip install "cryptography==49.0.0" "jsonschema==4.26.0"',
    );
    expect(workflow).toContain(
      "name: ember-cli-lifecycle-smoke-${{ github.sha }}",
    );
  });
});
