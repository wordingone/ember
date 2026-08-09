import { describe, expect, test } from "bun:test";
import { createStartDialogState, reduceStartDialog, formatStartTrainCommand, StartParametersDialog } from "./start-parameters.ts";

describe("START parameter dialog contract", () => {
  test("bounds edits and emits exact governed command on confirm", () => {
    let state = createStartDialogState();
    state = reduceStartDialog(state, { type: "open" }).state;
    state = reduceStartDialog(state, { type: "edit", field: "steps", value: 999999 }).state;
    state = reduceStartDialog(state, { type: "edit", field: "dataSize", value: 0 }).state;
    state = reduceStartDialog(state, { type: "edit", field: "timeBudgetMinutes", value: 999999 }).state;
    const result = reduceStartDialog(state, { type: "confirm" });
    expect(result.submitted).toEqual({ dataSize: 1, steps: 100000, timeBudgetMinutes: 1440 });
    expect(formatStartTrainCommand(result.submitted!)).toBe("/train --data-size 1 --steps 100000 --time-budget-minutes 1440");
  });

  test("cancel closes without submission", () => {
    const result = reduceStartDialog({ open: true, parameters: { dataSize: 2, steps: 3, timeBudgetMinutes: 4 } }, { type: "cancel" });
    expect(result.submitted).toBeUndefined();
    expect(result.state.open).toBe(false);
  });

  test("rendered dialog exposes governed confirm and cancel actions", () => {
    const confirmed: unknown[] = [];
    let cancelled = 0;
    const tree = StartParametersDialog({
      initial: { dataSize: 0, steps: 100_001, timeBudgetMinutes: 0 },
      onConfirm: (parameters) => confirmed.push(parameters),
      onCancel: () => { cancelled += 1; },
    }) as unknown as { props?: { children?: unknown[] }; children?: unknown[] };
    const children = (tree.props?.children ?? tree.children ?? []) as Array<{ props?: { onPress?: () => void } }>;
    const buttons = children.filter((child) => typeof child?.props?.onPress === "function");
    expect(buttons).toHaveLength(2);
    buttons[0]!.props!.onPress!();
    buttons[1]!.props!.onPress!();
    expect(confirmed).toEqual([{ dataSize: 1, steps: 100000, timeBudgetMinutes: 1 }]);
    expect(cancelled).toBe(1);
  });
});
