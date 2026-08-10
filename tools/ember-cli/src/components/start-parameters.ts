// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// authority: current Ember CLI/Lab governed surface; no parallel runtime authority
// claim_boundary: CPU/source-level START parameter dialog only; no training/result claim
export interface StartParameters {
  dataSize: number;
  steps: number;
  timeBudgetMinutes: number;
}

export const DEFAULT_START_PARAMETERS: Readonly<StartParameters> = {
  dataSize: 1,
  steps: 100,
  timeBudgetMinutes: 30,
};

export const START_PARAMETER_BOUNDS = {
  dataSize: { min: 1, max: 128 },
  steps: { min: 1, max: 100_000 },
  timeBudgetMinutes: { min: 1, max: 1_440 },
} as const;

export function clampStartParameters(parameters: StartParameters): StartParameters {
  return {
    dataSize: Math.max(1, Math.min(128, Math.trunc(parameters.dataSize))),
    steps: Math.max(1, Math.min(100_000, Math.trunc(parameters.steps))),
    timeBudgetMinutes: Math.max(1, Math.min(1_440, Math.trunc(parameters.timeBudgetMinutes))),
  };
}

export function formatStartTrainCommand(parameters: StartParameters): string {
  const bounded = clampStartParameters(parameters);
  return `/train --data-size ${bounded.dataSize} --steps ${bounded.steps} --time-budget-minutes ${bounded.timeBudgetMinutes}`;
}

export type StartDialogAction =
  | { type: "open" }
  | { type: "edit"; field: keyof StartParameters; value: number }
  | { type: "confirm" }
  | { type: "cancel" };

export interface StartDialogState {
  open: boolean;
  parameters: StartParameters;
}

export function createStartDialogState(parameters: StartParameters = DEFAULT_START_PARAMETERS): StartDialogState {
  return { open: false, parameters: clampStartParameters({ ...parameters }) };
}

export function reduceStartDialog(state: StartDialogState, action: StartDialogAction): { state: StartDialogState; submitted?: StartParameters } {
  if (action.type === "open") return { state: { ...state, open: true } };
  if (action.type === "edit") return { state: { ...state, parameters: clampStartParameters({ ...state.parameters, [action.field]: action.value }) } };
  if (action.type === "confirm") {
    const parameters = clampStartParameters(state.parameters);
    return { state: { open: false, parameters }, submitted: parameters };
  }
  return { state: { ...state, open: false } };
}

export interface StartParametersDialogProps {
  initial?: StartParameters;
  onConfirm: (parameters: StartParameters) => void;
  onCancel: () => void;
  onEdit?: (field: keyof StartParameters, value: number) => void;
}

export function StartParametersDialog({ initial = DEFAULT_START_PARAMETERS, onConfirm, onCancel, onEdit }: StartParametersDialogProps): React.ReactElement {
  const parameters = clampStartParameters(initial);
  const edit = (field: keyof StartParameters, delta: number) => onEdit?.(field, parameters[field] + delta);
  return React.createElement(
    Box,
    { borderStyle: "single", flexDirection: "column", flexShrink: 0, paddingX: 1 },
    React.createElement(Text, null, "START PARAMETERS"),
    React.createElement(Text, null, `data=${parameters.dataSize} steps=${parameters.steps} budget=${parameters.timeBudgetMinutes}`),
    React.createElement(Button, { onPress: () => edit("dataSize", 1) }, "DATA+"),
    React.createElement(Button, { onPress: () => edit("steps", 1) }, "STEPS+"),
    React.createElement(Button, { onPress: () => edit("timeBudgetMinutes", 1) }, "BUDGET+"),
    React.createElement(Button, { onPress: () => onConfirm(parameters) }, "CONFIRM"),
    React.createElement(Button, { onPress: onCancel }, "CANCEL"),
  );
}
import React from "react";
import { Box, Button, Text } from "../ink/components.ts";
