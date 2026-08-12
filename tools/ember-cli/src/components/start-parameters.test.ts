// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import {
  PARAMETER_NOT_DECLARED,
  StartParametersDialog,
  parseLaunchAuthorityParameters,
} from "./start-parameters.ts";

describe("operator parameter review contract", () => {
  test("parses the six closed launch-authority fields without inventing defaults", () => {
    expect(parseLaunchAuthorityParameters(JSON.stringify({
      schema_version: "ember-certified-train-run-v1",
      run_id: "run-1314",
      seed: 830001,
      requested_scope: {
        optimizer_steps: 200,
        sequence_length: 4096,
        checkpoint_interval: 50,
        write_budget_bytes: 36507222016,
      },
    }))).toEqual({
      ok: true,
      parameters: {
        seed: 830001,
        steps: 200,
        sequenceLength: 4096,
        checkpointInterval: 50,
        writeBudgetBytes: 36507222016,
        runId: "run-1314",
      },
    });
  });

  test("fails closed when a required authority value is absent or malformed", () => {
    expect(parseLaunchAuthorityParameters(JSON.stringify({
      schema_version: "ember-certified-train-run-v1",
      run_id: "run-1314",
      seed: 830001,
      requested_scope: { sequence_length: 4096, checkpoint_interval: 50, write_budget_bytes: 1 },
    }))).toEqual({ ok: false, reason: "launch-authority run-spec is missing optimizer_steps" });
    expect(parseLaunchAuthorityParameters("{not-json")).toEqual({
      ok: false,
      reason: "launch-authority run-spec is not valid JSON",
    });
  });

  test("the public governed-vertical shape reports undeclared display fields without guessing", () => {
    expect(parseLaunchAuthorityParameters(JSON.stringify({
      schema_version: "ember-certified-train-run-v1",
      run_id: "r-public",
      seed: 830001,
      requested_scope: { optimizer_steps: 100, write_budget_bytes: 36507222016 },
    }))).toEqual({
      ok: true,
      parameters: {
        seed: 830001,
        steps: 100,
        sequenceLength: PARAMETER_NOT_DECLARED,
        checkpointInterval: PARAMETER_NOT_DECLARED,
        writeBudgetBytes: 36507222016,
        runId: "r-public",
      },
    });
  });

  test("seed zero is preserved as declared authority, not mistaken for missing", () => {
    const parsed = parseLaunchAuthorityParameters(JSON.stringify({
      run_id: "seed-zero",
      seed: 0,
      requested_scope: { optimizer_steps: 1, write_budget_bytes: 1 },
    }));
    expect(parsed.ok && parsed.parameters.seed).toBe(0);
  });

  test("rendered dialog is review-only and exposes one explicit confirm plus cancel", () => {
    const confirmed: unknown[] = [];
    let cancelled = 0;
    const tree = StartParametersDialog({
      action: "RESTART",
      sourcePath: "B:/authority/run-spec.json",
      parameters: {
        seed: 83,
        steps: 200,
        sequenceLength: 4096,
        checkpointInterval: 50,
        writeBudgetBytes: 4096,
        runId: "run-1314",
      },
      onConfirm: (parameters) => confirmed.push(parameters),
      onCancel: () => { cancelled += 1; },
    }) as unknown as { props?: { children?: unknown[] }; children?: unknown[] };
    const children = (tree.props?.children ?? tree.children ?? []) as Array<{ props?: { onPress?: () => void } }>;
    const buttons = children.filter((child) => typeof child?.props?.onPress === "function");
    expect(buttons).toHaveLength(2);
    buttons[0]!.props!.onPress!();
    buttons[1]!.props!.onPress!();
    expect(confirmed).toEqual([{
      seed: 83,
      steps: 200,
      sequenceLength: 4096,
      checkpointInterval: 50,
      writeBudgetBytes: 4096,
      runId: "run-1314",
    }]);
    expect(cancelled).toBe(1);
  });
});
