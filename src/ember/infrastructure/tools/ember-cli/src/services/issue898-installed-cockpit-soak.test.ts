// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 J

import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  appendInstalledCockpitSoakPoll,
  createInstalledCockpitSoakLedger,
  runInstalledCockpitSoak,
  sealInstalledCockpitSoak,
  verifyInstalledCockpitSoakReceipt,
  verifyInstalledCockpitSoakCustody,
} from "./issue898-installed-cockpit-soak.ts";

const sha = "a".repeat(64);
const source = "b".repeat(40);

function fixtureRows(ledgerPath: string, foreign = false): void {
  const started = Date.parse("2026-08-23T18:00:00.000Z");
  for (let index = 0; index <= 120; index += 1) {
    const ts = new Date(started + index * 60_000).toISOString();
    appendInstalledCockpitSoakPoll(ledgerPath, {
      schema_version: "ember-issue898-installed-cockpit-soak-poll-v1",
      sequence: index,
      census: {
        schema_version: "ember-process-memory-census-poll-v1",
        observed_at: ts,
        provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks",
        candidate_process_count: foreign ? 2 : 1,
        admitted_process_count: 1,
        class_cardinality: { cockpit: 1, brain_server: 0 },
        ownership_overlap: { count: 0, pids: [] },
        samples: [{ process_class: "cockpit", pid: 11, parent_pid: 1, process_name: "ember", process_start_token: "638915652000000000", provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks", commit_bytes: 1_000_000 + index * 10, ownership_basis: ["cockpit_pid"] }],
      },
      walls: {
        schema_version: "ember-lab-wall-observation-snapshot-v1",
        captured_at_ms: started + index * 60_000,
        after_vram_seq: index,
        after_disk_seq: index,
        next_vram_seq: index + 1,
        next_disk_seq: index + 1,
        daemon_identity: { schema_version: "ember-lab-runtime-identity-v1", pid: 44, binary_sha256: sha, source_sha256: sha },
        vram_observations: [{ seq: index + 1, job_id: "sidecar", observed_at_ms: started + index * 60_000, outcome: index === 3 ? "provider_unavailable" : "within_limit", payload: index === 3 ? { debounce_disposition: "retained_previous_sample" } : {} }],
        disk_observations: [{ seq: index + 1, job_id: "sidecar", write_root: "B:\\durable", observed_at_ms: started + index * 60_000, outcome: "within_limit", payload: { measurement_duration_ms: 12 } }],
      },
    });
  }
}

function seal(root: string) {
  const ledger = createInstalledCockpitSoakLedger(path.join(root, "durable"));
  fixtureRows(ledger, true);
  const receiptPath = path.join(root, "durable", "receipt.json");
  const receipt = sealInstalledCockpitSoak({
    raw_ledger_path: ledger,
    receipt_path: receiptPath,
    identity: { source_commit: source, cockpit_binary_sha256: sha, ember_lab_binary_sha256: sha, ember_lab_source_sha256: sha, cockpit_pid: 11, cockpit_process_start_token: "638915652000000000", sidecar_job_id: "sidecar", sidecar_manifest_sha256: sha },
    negatives: {
      above_hard_trip: { passed: true, receipt_sha256: sha },
      below_reset: { passed: true, receipt_sha256: sha },
      soft_observe: { passed: true, receipt_sha256: sha },
      foreign_identity_never_controlled: { passed: true, receipt_sha256: sha },
    },
    poll_interval_seconds: 60,
    receipt_written_at: "2026-08-23T20:00:01.000Z",
    restart_event_count_before_receipt: 0,
  });
  return { ledger, receiptPath, receipt };
}

describe("installed cockpit soak custody", () => {
  test("real adapter advances exact wall cursors for a full governed duration", async () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "issue898-run-"));
    let current = Date.parse("2026-08-23T18:00:00.000Z");
    const ledger = await runInstalledCockpitSoak({
      outputRoot: path.join(root, "durable"), pipeName: "\\\\.\\pipe\\ember-lab-test",
      memorySpec: { schema_version: "ember-liveness-watchdog-memory-v1", goal_id: "EMBER-02", workstream_id: "EMBER-02A", next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", classes: { cockpit: { soft_bytes: 2, hard_bytes: 4, consecutive_hard_polls: 3, process_names: ["ember"] }, brain_server: { soft_bytes: 12, hard_bytes: 14, consecutive_hard_polls: 3, process_names: ["ember-lab"] } } },
      cockpitPid: 11, ownedBrainPids: [44], durationSeconds: 7_200, pollIntervalSeconds: 60,
    }, {
      now: () => current,
      sleep: async (milliseconds) => { current += milliseconds; },
      census: async () => ({ schema_version: "ember-process-memory-census-poll-v1", observed_at: new Date(current).toISOString(), provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks", candidate_process_count: 1, admitted_process_count: 1, class_cardinality: { cockpit: 1, brain_server: 0 }, ownership_overlap: { count: 0, pids: [] }, samples: [{ process_class: "cockpit", pid: 11, parent_pid: 1, process_name: "ember", process_start_token: "638915652000000000", provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks", commit_bytes: 1_000_000, ownership_basis: ["cockpit_pid"] }] }),
      readWalls: async ({ afterVramSeq, afterDiskSeq }) => ({ schema_version: "ember-lab-wall-observation-snapshot-v1", captured_at_ms: current, after_vram_seq: afterVramSeq, after_disk_seq: afterDiskSeq, next_vram_seq: afterVramSeq + 1, next_disk_seq: afterDiskSeq + 1, daemon_identity: { schema_version: "ember-lab-runtime-identity-v1", pid: 44, binary_sha256: sha, source_sha256: sha }, vram_observations: [], disk_observations: [] }),
    });
    const rows = readFileSync(ledger, "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows).toHaveLength(121);
    expect(rows.at(-1).walls.after_vram_seq).toBe(120);
    expect(rows.at(-1).walls.after_disk_seq).toBe(120);
  });

  test("seals 2h raw polls, OLS bands, walls, negatives, and receipt-before-restart", () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "issue898-soak-"));
    const { receiptPath, receipt } = seal(root);
    expect(receipt.verdict).toBe("MEASURED_NEEDS_INDEPENDENT_ADJUDICATION");
    expect((receipt.final_hour as { band: { window_count: number } }).band.window_count).toBe(12);
    expect((receipt.wall_summary as { provider_unavailable_count: number }).provider_unavailable_count).toBe(1);
    expect((receipt.wall_summary as { disk_measurement_duration_cap_met: boolean }).disk_measurement_duration_cap_met).toBe(true);
    expect(verifyInstalledCockpitSoakReceipt(readFileSync(receiptPath, "utf8"))).toEqual(receipt);
    expect(verifyInstalledCockpitSoakCustody(readFileSync(receiptPath, "utf8"), readFileSync(path.join(root, "durable", "polls.jsonl")))).toEqual(receipt);
  });

  test("refuses overwrite custody and receipt tampering", () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "issue898-soak-"));
    const { receiptPath } = seal(root);
    expect(() => createInstalledCockpitSoakLedger(path.join(root, "durable"))).toThrow("OUTPUT_ROOT_EXISTS");
    expect(() => verifyInstalledCockpitSoakReceipt(readFileSync(receiptPath, "utf8").replace('"sample_count": 121', '"sample_count": 122')))
      .toThrow("RECEIPT_SHA256_INVALID");
  });
});
