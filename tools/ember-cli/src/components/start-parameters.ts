// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// authority: current Ember CLI/Lab governed surface; no parallel runtime authority
// claim_boundary: CPU/source-level START parameter dialog only; no training/result claim
export type ParameterDialogAction = "START" | "PAUSE" | "RESUME" | "RESTART";
export const PARAMETER_NOT_DECLARED = "NOT DECLARED BY RUN-SPEC" as const;
export type AuthorityParameterValue = number | typeof PARAMETER_NOT_DECLARED;

export interface StartParameters {
  seed: number;
  steps: number;
  sequenceLength: AuthorityParameterValue;
  checkpointInterval: AuthorityParameterValue;
  writeBudgetBytes: number;
  runId: string;
}

export type LaunchAuthorityParametersResult =
  | { ok: true; parameters: StartParameters }
  | { ok: false; reason: string };

function positiveInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

function optionalPositiveInteger(value: unknown, name: string): AuthorityParameterValue | { reason: string } {
  if (value === undefined) return PARAMETER_NOT_DECLARED;
  const parsed = positiveInteger(value);
  return parsed === undefined ? { reason: `launch-authority run-spec has invalid ${name}` } : parsed;
}

/** Closed projection: missing authority is a refusal, never guessed steering. */
export function parseLaunchAuthorityParameters(raw: string): LaunchAuthorityParametersResult {
  let row: unknown;
  try {
    row = JSON.parse(raw);
  } catch {
    return { ok: false, reason: "launch-authority run-spec is not valid JSON" };
  }
  if (row === null || typeof row !== "object" || Array.isArray(row)) {
    return { ok: false, reason: "launch-authority run-spec is not an object" };
  }
  const record = row as Record<string, unknown>;
  const scope = record["requested_scope"];
  if (scope === null || typeof scope !== "object" || Array.isArray(scope)) {
    return { ok: false, reason: "launch-authority run-spec is missing requested_scope" };
  }
  const requested = scope as Record<string, unknown>;
  const fields = [
    ["seed", record["seed"], true],
    ["optimizer_steps", requested["optimizer_steps"], false],
    ["write_budget_bytes", requested["write_budget_bytes"], false],
  ] as const;
  const values = new Map<string, number>();
  for (const [name, candidate, allowZero] of fields) {
    const value = allowZero && typeof candidate === "number" && Number.isSafeInteger(candidate) && candidate >= 0
      ? candidate
      : positiveInteger(candidate);
    if (value === undefined) return { ok: false, reason: `launch-authority run-spec is missing ${name}` };
    values.set(name, value);
  }
  const runId = record["run_id"];
  if (typeof runId !== "string" || runId.trim() === "") {
    return { ok: false, reason: "launch-authority run-spec is missing run_id" };
  }
  const sequenceLength = optionalPositiveInteger(requested["sequence_length"], "sequence_length");
  if (typeof sequenceLength === "object") return { ok: false, reason: sequenceLength.reason };
  const checkpointInterval = optionalPositiveInteger(
    record["training_checkpoint_interval"] ?? requested["checkpoint_interval"],
    "checkpoint_interval",
  );
  if (typeof checkpointInterval === "object") return { ok: false, reason: checkpointInterval.reason };
  return {
    ok: true,
    parameters: {
      seed: values.get("seed")!,
      steps: values.get("optimizer_steps")!,
      sequenceLength,
      checkpointInterval,
      writeBudgetBytes: values.get("write_budget_bytes")!,
      runId: runId.trim(),
    },
  };
}

export interface StartParametersDialogProps {
  action: ParameterDialogAction;
  sourcePath: string;
  parameters: StartParameters;
  onConfirm: (parameters: StartParameters) => void;
  onCancel: () => void;
}

/** Review-only by construction: the only actions are CONFIRM and CANCEL. */
export function StartParametersDialog({ action, sourcePath, parameters, onConfirm, onCancel }: StartParametersDialogProps): React.ReactElement {
  return React.createElement(
    Box,
    { borderStyle: "single", flexDirection: "column", flexShrink: 0, paddingX: 1 },
    React.createElement(Text, { bold: true }, `${action} PARAMETERS — REVIEW ONLY`),
    React.createElement(Text, null, `run id: ${parameters.runId}`),
    React.createElement(Text, null, `seed: ${parameters.seed}  steps: ${parameters.steps}`),
    React.createElement(Text, null, `sequence length: ${parameters.sequenceLength}`),
    React.createElement(Text, null, `checkpoint interval: ${parameters.checkpointInterval}`),
    React.createElement(Text, null, `write budget: ${parameters.writeBudgetBytes} bytes`),
    React.createElement(Text, { dimColor: true }, `authority: ${sourcePath}`),
    React.createElement(Button, { onPress: () => onConfirm(parameters) }, `CONFIRM ${action}`),
    React.createElement(Button, { onPress: onCancel }, "CANCEL"),
  );
}
import React from "react";
import { Box, Button, Text } from "../ink/components.ts";
