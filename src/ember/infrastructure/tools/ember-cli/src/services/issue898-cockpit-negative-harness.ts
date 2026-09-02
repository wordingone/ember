// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 J

import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { censusWindowsProcessMemoryBatch } from "./process-memory-census.ts";
import { createMemoryFootprintGovernor, type MemoryFootprintSpec } from "./memory-footprint-governor.ts";
import type { InstalledCockpitSoakNegatives } from "./issue898-installed-cockpit-soak.ts";

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const row = value as Record<string, unknown>;
  return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${canonical(row[key])}`).join(",")}}`;
}

function hash(value: unknown): string {
  return createHash("sha256").update(typeof value === "string" ? value : canonical(value)).digest("hex");
}

export interface CockpitNegativeHarnessInput {
  source_commit: string;
  memory_spec_sha256: string;
  observed_at: string;
  cockpit_pid: number;
  cockpit_process_start_token: string;
  foreign_pid: number;
  spec: MemoryFootprintSpec;
  output_path?: string;
}

export async function runCockpitNegativeHarness(input: CockpitNegativeHarnessInput): Promise<{
  receipt: Record<string, unknown> & { receipt_sha256: string };
  negatives: InstalledCockpitSoakNegatives;
}> {
  if (!/^[0-9a-f]{40}$/.test(input.source_commit) || !/^[0-9a-f]{64}$/.test(input.memory_spec_sha256)) throw new Error("ISSUE898_NEGATIVE_SOURCE_INVALID");
  const events: string[] = [];
  const governor = createMemoryFootprintGovernor({
    spec: input.spec,
    now: () => Date.parse(input.observed_at),
    writeReceipt: () => events.push("receipt"),
    correctiveAction: () => events.push("action"),
  });
  const cockpit = { process_class: "cockpit" as const, pid: input.cockpit_pid };
  const row = input.spec.classes.cockpit;
  const hard = row.hard_bytes + 1;
  let aboveState = "";
  for (let index = 0; index < row.consecutive_hard_polls; index += 1) aboveState = governor.observe({ ...cockpit, commit_bytes: hard }).state;
  const aboveHardTrip = aboveState === "tripped" && events.join(",") === "receipt,action";

  const resetPid = input.cockpit_pid + 1;
  const resetGovernor = createMemoryFootprintGovernor({ spec: input.spec, writeReceipt: () => { throw new Error("ISSUE898_NEGATIVE_UNEXPECTED_RECEIPT"); } });
  for (let index = 0; index < row.consecutive_hard_polls - 1; index += 1) resetGovernor.observe({ process_class: "cockpit", pid: resetPid, commit_bytes: hard });
  const resetState = resetGovernor.observe({ process_class: "cockpit", pid: resetPid, commit_bytes: row.hard_bytes - 1 });
  const resetNext = resetGovernor.observe({ process_class: "cockpit", pid: resetPid, commit_bytes: hard });
  const belowReset = resetState.consecutive_hard_polls === 0 && resetNext.consecutive_hard_polls === 1;

  let softActions = 0;
  const softGovernor = createMemoryFootprintGovernor({ spec: input.spec, writeReceipt: () => { softActions += 1; }, correctiveAction: () => { softActions += 1; } });
  const softState = softGovernor.observe({ ...cockpit, commit_bytes: row.soft_bytes });
  const softObserve = softState.state === "soft" && softActions === 0;

  const brainName = input.spec.classes.brain_server.process_names[0];
  const census = await censusWindowsProcessMemoryBatch(input.spec, {
    cockpitPid: input.cockpit_pid,
    observedAt: () => input.observed_at,
    runPowerShell: async () => JSON.stringify([
      { Id: input.cockpit_pid, ParentProcessId: 1, ProcessName: input.spec.classes.cockpit.process_names[0], PagedMemorySize64: row.soft_bytes, ProcessStartToken: input.cockpit_process_start_token },
      { Id: input.foreign_pid, ParentProcessId: 1, ProcessName: brainName, PagedMemorySize64: input.spec.classes.brain_server.hard_bytes + 1, ProcessStartToken: "638915652999999999" },
    ]),
  });
  const foreignNeverControlled = census.candidate_process_count === 2 && census.admitted_process_count === 1
    && !census.samples.some((sample) => sample.pid === input.foreign_pid);
  if (!aboveHardTrip || !belowReset || !softObserve || !foreignNeverControlled) throw new Error("ISSUE898_NEGATIVE_HARNESS_FAILED");
  const base = {
    schema_version: "ember-issue898-cockpit-negative-harness-v1",
    verdict: "PASS",
    source_commit: input.source_commit,
    memory_spec_sha256: input.memory_spec_sha256,
    observed_at: input.observed_at,
    above_hard_trip: { passed: true, receipt_before_action: events.join(",") === "receipt,action", terminal_state: aboveState },
    below_reset: { passed: true, reset_state: resetState.state, next_hard_count: resetNext.consecutive_hard_polls },
    soft_observe: { passed: true, state: softState.state, corrective_action_count: softActions },
    foreign_identity_never_controlled: { passed: true, foreign_pid: input.foreign_pid, candidate_process_count: census.candidate_process_count, admitted_process_count: census.admitted_process_count },
  };
  const receipt = { ...base, receipt_sha256: hash(base) };
  if (input.output_path) writeFileSync(input.output_path, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  const evidence = { passed: true as const, receipt_sha256: receipt.receipt_sha256 };
  return { receipt, negatives: { above_hard_trip: evidence, below_reset: evidence, soft_observe: evidence, foreign_identity_never_controlled: evidence } };
}
