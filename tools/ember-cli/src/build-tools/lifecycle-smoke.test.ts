// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import xtermHeadless from "@xterm/headless";
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
    schema_version: "ember-cli-lifecycle-smoke/v1",
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
    actions: LIFECYCLE_ACTIONS.map((action, index) => ({
      action,
      ordinal: index + 1,
      input_sha256: String(index + 1).padStart(64, "0"),
      before_frame_sha256: String(index + 11).padStart(64, "0"),
      after_frame_sha256: String(index + 21).padStart(64, "0"),
      effect_evidence_sha256: String(index + 31).padStart(64, "0"),
      effect_kind: "durable-state-transition",
      outcome: "PASS",
      output_excerpt: `${action} effect observed`,
      state_before: index,
      state_after: index + 1,
      frame_artifact: `receipts/ember-cli-lifecycle-smoke/action-${index + 1}.frame.txt`,
      repair_item: null,
    })),
    termination: {
      explicit_requested: true,
      child_exit_observed: true,
      cleanup_attempted: true,
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

  test("accepts truthful product-level red outcomes from a correct instrument", () => {
    const receipt = validReceipt();
    const save = receipt.actions.find((row) => row.action === "save")!;
    save.output_excerpt =
      "legacy checkpoint snapshot saved (not /model checkpoint load compatible)";
    const reload = receipt.actions.find((row) => row.action === "reload")!;
    reload.outcome = "REFUSED";
    reload.effect_kind = "observable-refusal";
    reload.output_excerpt = "error: failed to load checkpoint";
    reload.state_before = null;
    reload.state_after = null;
    reload.repair_item = "EMBER-CLI-SAVE-RELOAD-COMPATIBILITY";
    const continued = receipt.actions.find((row) => row.action === "continue")!;
    continued.outcome = "MISSING";
    continued.effect_kind = "observable-refusal";
    continued.output_excerpt = "Unknown command: /continue";
    continued.state_before = null;
    continued.state_after = null;
    continued.repair_item = "EMBER-CLI-CONTINUE-PRODUCTION-WIRING";

    expect(validateLifecycleReceipt(receipt, expected)).toEqual({
      ok: true,
      action_count: 9,
    });
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
    const located = spawnSync("where.exe", ["node"], {
      encoding: "utf8",
      windowsHide: true,
    });
    expect(located.status).toBe(0);
    const nodeExecutable = located.stdout
      .split(/\r?\n/)
      .find((line) => line.trim().toLowerCase().endsWith("node.exe"))
      ?.trim();
    expect(nodeExecutable).toBeTruthy();
    const driver = join(import.meta.dir, "lifecycle-smoke-driver.ts");
    const result = spawnSync(
      nodeExecutable!,
      ["--experimental-strip-types", driver],
      { cwd: join(import.meta.dir, ".."), encoding: "utf8", windowsHide: true },
    );

    expect(result.status).toBe(1);
    expect(result.stderr).toContain(
      "--binary, --out-dir, and --receipt-path are required",
    );
    expect(result.stderr).not.toContain("Named export 'Terminal' not found");
    expect(result.stderr).not.toContain("ERR_SOCKET_CLOSED");
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
      "/model checkpoint save C:\\tmp\\saved\r\nlegacy checkpoint snapshot saved (not /model checkpoint load compatible)\r\n",
      "/model checkpoint save C:\\tmp\\saved",
    );
    expect(saved).toContain("not /model checkpoint load compatible");
  });

  test("classifies the rendered action and retains the exact save incompatibility", async () => {
    const driver = await import("./lifecycle-smoke-driver.ts");
    expect(driver.classifyActionFrame).toBeFunction();
    expect(driver.actionOutputExcerpt).toBeFunction();

    const continuedFrame = [
      "error: failed to load checkpoint: historical row",
      "Unknown command: /continue",
    ].join("\n");
    expect(driver.classifyActionFrame!(continuedFrame)).toBe("MISSING");

    const quote = "legacy checkpoint snapshot saved (not /model checkpoint load compatible)";
    expect(driver.actionOutputExcerpt!("legacy checkpoint snapshot saved", `${quote}${"x".repeat(3000)}`))
      .toBe(quote);
    expect(driver.actionOutputExcerpt!(continuedFrame, "cursor repaint without contiguous output"))
      .toContain("Unknown command: /continue");
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
