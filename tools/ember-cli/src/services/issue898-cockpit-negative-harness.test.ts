// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 J

import { expect, test } from "bun:test";
import { runCockpitNegativeHarness } from "./issue898-cockpit-negative-harness.ts";

test("closed negative harness proves trip/reset/soft/foreign behavior", async () => {
  const result = await runCockpitNegativeHarness({
    source_commit: "b".repeat(40), memory_spec_sha256: "a".repeat(64), observed_at: "2026-08-23T18:00:00.000Z",
    cockpit_pid: 11, cockpit_process_start_token: "638915652000000000", foreign_pid: 99,
    spec: { schema_version: "ember-liveness-watchdog-memory-v1", goal_id: "EMBER-02", workstream_id: "EMBER-02A", next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", classes: { cockpit: { soft_bytes: 2, hard_bytes: 4, consecutive_hard_polls: 3, process_names: ["ember"] }, brain_server: { soft_bytes: 12, hard_bytes: 14, consecutive_hard_polls: 3, process_names: ["ember-lab"] } } },
  });
  expect(result.receipt).toMatchObject({ verdict: "PASS", above_hard_trip: { passed: true }, below_reset: { passed: true }, soft_observe: { passed: true }, foreign_identity_never_controlled: { passed: true, admitted_process_count: 1 } });
  expect(new Set(Object.values(result.negatives).map((row) => row.receipt_sha256)).size).toBe(1);
});
