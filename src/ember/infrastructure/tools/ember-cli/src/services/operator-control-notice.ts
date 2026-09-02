// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import type { OperatorControlAction } from "./operator-controls.ts";

export interface OperatorControlRefusal {
  action: OperatorControlAction;
  detail: string;
  receiptPath: string;
}

export interface OperatorControlNotice extends OperatorControlRefusal {
  count: number;
  line: string;
}

export function updateOperatorControlNotice(
  current: OperatorControlNotice | undefined,
  refusal: OperatorControlRefusal,
): OperatorControlNotice {
  const repeated = current !== undefined && current.action === refusal.action &&
    current.detail === refusal.detail && current.receiptPath === refusal.receiptPath;
  const count = repeated ? current.count + 1 : 1;
  const suffix = count > 1 ? ` (repeated ${count}x)` : "";
  return {
    ...refusal,
    count,
    // Attribution leads the detail so the bounded live pane never truncates the receipt path.
    line: `LIVE ${refusal.action} REFUSED${suffix} -- receipt ${refusal.receiptPath}: ${refusal.detail}`,
  };
}
