// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { expect, test } from "bun:test";
import { updateOperatorControlNotice } from "./operator-control-notice.ts";

test("repeated fail-closed refusals collapse into one live attributed receipt line", () => {
  const first = updateOperatorControlNotice(undefined, {
    action: "PAUSE",
    detail: "no running run",
    receiptPath: "B:/receipts/operator-sessions/session.jsonl",
  });
  const repeated = updateOperatorControlNotice(first, {
    action: "PAUSE",
    detail: "no running run",
    receiptPath: "B:/receipts/operator-sessions/session.jsonl",
  });
  expect(repeated.count).toBe(2);
  expect(repeated.line).toBe(
    "LIVE PAUSE REFUSED (repeated 2x) -- receipt B:/receipts/operator-sessions/session.jsonl: no running run",
  );
});

test("a different refusal replaces the live line instead of relabeling stale scrollback", () => {
  const prior = updateOperatorControlNotice(undefined, {
    action: "PAUSE",
    detail: "no running run",
    receiptPath: "B:/receipts/operator-sessions/a.jsonl",
  });
  const next = updateOperatorControlNotice(prior, {
    action: "RESTART",
    detail: "run identity mismatch",
    receiptPath: "B:/receipts/operator-sessions/b.jsonl",
  });
  expect(next.count).toBe(1);
  expect(next.line).toBe(
    "LIVE RESTART REFUSED -- receipt B:/receipts/operator-sessions/b.jsonl: run identity mismatch",
  );
});
