// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { Database } from "bun:sqlite";
import { afterEach, describe, expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  observeTrainFrame,
  observeTrainSample,
  parsePreflightJobMembershipSamples,
  parseRuntimeJobEnforcementProbe,
} from "./job-memory-probe-driver-state.ts";
import { readPacketBinding } from "./job-memory-probe-packet.ts";
import * as productionDriver from "./drive-job-memory-probe.ts";
import * as driverState from "./job-memory-probe-driver-state.ts";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true });
});

function fixture(signedDeltaBytes = -67_108_864): {
  authorityRoot: string;
  custodyRoot: string;
  repoRoot: string;
} {
  const root = mkdtempSync(join(tmpdir(), "ember-probe-driver-test-"));
  roots.push(root);
  const repoRoot = join(root, "repo");
  const authorityRoot = join(root, "authority");
  const custodyRoot = join(root, "custody");
  mkdirSync(repoRoot);
  mkdirSync(authorityRoot);
  mkdirSync(custodyRoot);
  writeFileSync(join(authorityRoot, "certificate.json"), "{}\n");
  writeFileSync(join(authorityRoot, "declaration-ledger.jsonl"), "{}\n");
  writeFileSync(join(authorityRoot, "launch-authority-custody.json"), "{}\n");
  writeFileSync(
    join(authorityRoot, "run-spec.json"),
    `${JSON.stringify({
      schema_version: "ember-certified-train-run-v1",
      run_id: "issue898-probe-negative",
      requested_scope: {
        mode: "governed-vertical",
        custody_root: custodyRoot,
      },
      job_memory_ceiling_probe: {
        maximum_job_memory_bytes: 1_073_741_824,
        signed_delta_bytes: signedDeltaBytes,
      },
    })}\n`,
  );
  return { authorityRoot, custodyRoot, repoRoot };
}

describe("readPacketBinding", () => {
  test("binds one external nonzero signed probe packet", () => {
    const paths = fixture();
    const binding = readPacketBinding(paths.repoRoot, paths.authorityRoot);
    expect(binding.runId).toBe("issue898-probe-negative");
    expect(binding.maximumJobMemoryBytes).toBe(1_073_741_824);
    expect(binding.signedDeltaBytes).toBe(-67_108_864);
    expect(binding.operationalReceipt).toBe(
      join(
        paths.custodyRoot,
        "issue898-probe-negative",
        "ember-lab-certified-launch-operational.json",
      ),
    );
    expect(Object.keys(binding.hashes).sort()).toEqual([
      "certificate.json",
      "declaration-ledger.jsonl",
      "launch-authority-custody.json",
      "run-spec.json",
    ]);
    for (const digest of Object.values(binding.hashes)) {
      expect(digest).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  test("refuses an authority packet inside the repository", () => {
    const paths = fixture();
    expect(() => readPacketBinding(paths.repoRoot, paths.repoRoot)).toThrow(
      "authority root must be outside the repository",
    );
  });

  test("refuses zero delta", () => {
    const paths = fixture(0);
    expect(() => readPacketBinding(paths.repoRoot, paths.authorityRoot)).toThrow(
      "probe quantities are not positive-maximum/nonzero-delta",
    );
  });

  test("refuses overwrite of an existing operational receipt", () => {
    const paths = fixture();
    const receiptRoot = join(paths.custodyRoot, "issue898-probe-negative");
    mkdirSync(receiptRoot);
    writeFileSync(join(receiptRoot, "ember-lab-certified-launch-operational.json"), "{}\n");
    expect(() => readPacketBinding(paths.repoRoot, paths.authorityRoot)).toThrow(
      "no-overwrite operational receipt already exists",
    );
  });
});

describe("observeTrainFrame", () => {
  test("classifies a synchronous refusal only before governed evidence", () => {
    const observation = observeTrainFrame(
      "error: certified train consumer refused or failed.\n",
      undefined,
      false,
    );
    expect(observation.synchronousRefusal).toBe(true);
    expect(observation.governedEvidenceSeen).toBe(false);
  });

  test("complete governed start evidence outranks refusal text in the same frame", () => {
    const observation = observeTrainFrame(
      [
        "error: certified train consumer refused or failed.",
        "governed child pid: 4242",
        "job id: issue898-probe-negative-launch-1",
      ].join("\n"),
      undefined,
      false,
      {
        governedPid: 4242,
        jobId: "issue898-probe-negative-launch-1",
      },
    );
    expect(observation.synchronousRefusal).toBe(false);
    expect(observation.start).toEqual({
      governedPid: 4242,
      jobId: "issue898-probe-negative-launch-1",
    });
  });

  test("partial governed evidence permanently suppresses pre-receipt cleanup", () => {
    const partial = observeTrainFrame("governed child pid: 4242\n", undefined, false);
    const later = observeTrainFrame(
      "error: certified train consumer refused or failed.\n",
      partial.start,
      partial.governedEvidenceSeen,
    );
    expect(partial.governedEvidenceSeen).toBe(true);
    expect(later.synchronousRefusal).toBe(false);
  });

  test("preserves a complete start after it scrolls out of the frame", () => {
    const first = observeTrainFrame(
      "governed child pid: 4242\njob id: issue898-probe-negative-launch-1\n",
      undefined,
      false,
      {
        governedPid: 4242,
        jobId: "issue898-probe-negative-launch-1",
      },
    );
    const later = observeTrainFrame("waiting for terminal receipt\n", first.start, true);
    expect(later.start).toEqual(first.start);
    expect(later.governedEvidenceSeen).toBe(true);
  });

  test("stream evidence suppresses cleanup after it scrolls beyond the sampled viewport", () => {
    const governedStart = [
      "governed child pid: 4242",
      "job id: issue898-probe-negative-launch-1",
    ].join("\n");
    const scrolledOutput = Array.from(
      { length: 41 },
      (_, index) => `post-start output row ${index}`,
    ).join("\n");
    const refusalViewport = "error: certified train consumer refused or failed.\n";
    const observation = observeTrainSample(
      refusalViewport,
      `${governedStart}\n${scrolledOutput}\n${refusalViewport}`,
      undefined,
      false,
      {
        governedPid: 4242,
        jobId: "issue898-probe-negative-launch-1",
      },
    );

    expect(observation.governedEvidenceSeen).toBe(true);
    expect(observation.start).toEqual({
      governedPid: 4242,
      jobId: "issue898-probe-negative-launch-1",
    });
    expect(observation.synchronousRefusal).toBe(false);
  });

  test("uses authored identity with the real lossy governed-start frame", () => {
    const captured = [
      "● certified train consumer started in background.                     │",
      "  governed child pid: 17972                                           │",
      "  job id:                                                             │",
      "  issue898-premerge-train-confirm-cage-negative-20260826t1357z-launch-│",
      "  87758320679                                                         │",
      "  preflight receipt:                                                  │",
    ].join("\n");
    const authoredStart = {
      governedPid: 17972,
      jobId:
        "issue898-premerge-train-confirm-cage-negative-20260826t1357z-launch-1787758320679",
    };
    const withoutAuthoredIdentity = observeTrainSample(
      captured,
      captured,
      undefined,
      false,
    );
    const observation = observeTrainSample(
      captured,
      captured,
      undefined,
      false,
      authoredStart,
    );

    expect(withoutAuthoredIdentity.start).toBeUndefined();
    expect(observation.start).toEqual(authoredStart);
    expect(observation.governedEvidenceSeen).toBe(true);
    expect(observation.synchronousRefusal).toBe(false);
  });
});

describe("parseDaemonJobMemoryEnforcementWitness", () => {
  const jobId = "issue898-probe-negative-launch-1787761213938";
  const governedPid = 45588;
  const maximumJobMemoryBytes = 1_073_741_824;
  const witness = {
    schema_version: "ember-lab-job-memory-enforcement-witness-v1",
    witness_kind: "daemon_assignment_time_kernel_query",
    witness_stage: "post_create_pre_resume",
    observed_at_ms: 1_787_761_216_300,
    job_object_name: "Local\\ember-lab-42336-exact",
    governed_pid: governedPid,
    daemon_control_pid: 42336,
    assignment_method: "proc_thread_attribute_job_list",
    governed_membership_query_succeeded: true,
    governed_is_member: true,
    daemon_membership_query_succeeded: true,
    daemon_is_member: false,
    extended_limit_query_succeeded: true,
    limit_flags: 0x2200,
    job_memory_limit_flag_set: true,
    expected_maximum_job_memory_bytes: maximumJobMemoryBytes,
    observed_job_memory_limit_bytes: maximumJobMemoryBytes,
  };
  const receipt = (events: unknown[]) => ({
    schema: "ember-lab-operational-receipt-v1",
    state: "exited",
    job_id: jobId,
    pid: governedPid,
    events,
  });
  const prepared = (value: Record<string, unknown> = witness) => ({
    seq: 7,
    ts_ms: witness.observed_at_ms + 1,
    kind: "job_prepared",
    payload: {
      pid: governedPid,
      job_object_name: witness.job_object_name,
      job_memory_enforcement_witness: value,
    },
  });
  function parser(): (
    receipt: unknown,
    expected: { jobId: string; governedPid: number; maximumJobMemoryBytes: number },
  ) => unknown {
    const value = (driverState as Record<string, unknown>)[
      "parseDaemonJobMemoryEnforcementWitness"
    ];
    expect(typeof value).toBe("function");
    return value as (
      receipt: unknown,
      expected: { jobId: string; governedPid: number; maximumJobMemoryBytes: number },
    ) => unknown;
  }

  test("accepts one exact daemon-authored pre-execution witness", () => {
    expect(parser()(receipt([prepared()]), {
      jobId,
      governedPid,
      maximumJobMemoryBytes,
    })).toEqual({
      schemaVersion: "ember-lab-job-memory-enforcement-witness-v1",
      witnessKind: "daemon_assignment_time_kernel_query",
      witnessStage: "post_create_pre_resume",
      observedAtMs: witness.observed_at_ms,
      jobId,
      jobObjectName: witness.job_object_name,
      governedPid,
      daemonControlPid: 42336,
      assignmentMethod: "proc_thread_attribute_job_list",
      limitFlags: 0x2200,
      jobMemoryLimitBytes: maximumJobMemoryBytes,
      result: "VERIFIED_PRE_EXECUTION_KERNEL_ENFORCEMENT",
    });
  });

  test("refuses a missing prepared witness event", () => {
    expect(() => parser()(receipt([]), {
      jobId,
      governedPid,
      maximumJobMemoryBytes,
    })).toThrow("exactly one job_prepared witness event");
  });

  test("refuses duplicate prepared witness events", () => {
    expect(() => parser()(receipt([prepared(), prepared()]), {
      jobId,
      governedPid,
      maximumJobMemoryBytes,
    })).toThrow("exactly one job_prepared witness event");
  });

  test("refuses deceptive, non-closed, or numerically mismatched witnesses", () => {
    const cases = [
      { ...witness, governed_membership_query_succeeded: false },
      { ...witness, daemon_is_member: true },
      { ...witness, observed_job_memory_limit_bytes: maximumJobMemoryBytes - 1 },
      { ...witness, caller_claim: true },
    ];
    const parse = parser();
    for (const candidate of cases) {
      expect(() => parse(receipt([prepared(candidate)]), {
        jobId,
        governedPid,
        maximumJobMemoryBytes,
      })).toThrow();
    }
  });
});

describe("parsePreflightJobMembershipSamples", () => {
  test("preserves the sample denominator and both raw membership values", () => {
    const evidence = parsePreflightJobMembershipSamples([
      JSON.stringify({
        schema_version: "ember-issue898-preflight-job-membership-sample-v1",
        sample_index: 1,
        observed_at_ms: 100,
        descendant_count: 1,
        matches: [],
      }),
      JSON.stringify({
        schema_version: "ember-issue898-preflight-job-membership-sample-v1",
        sample_index: 2,
        observed_at_ms: 200,
        descendant_count: 2,
        matches: [
          {
            pid: 42,
            parent_pid: 7,
            command_line: 'python.exe "C:\\repo\\tools\\launch_packet.py" --config a',
            command_line_sha256: "a".repeat(64),
            is_process_in_job: false,
          },
          {
            pid: 43,
            parent_pid: 7,
            command_line: 'python.exe "C:\\repo\\tools\\launch_packet.py" --config b',
            command_line_sha256: "b".repeat(64),
            is_process_in_job: true,
          },
        ],
      }),
    ].join("\n"));
    expect(evidence.sampleCount).toBe(2);
    expect(evidence.maximumDescendantCount).toBe(2);
    expect(evidence.observations).toHaveLength(2);
    expect(evidence.result).toBe("OBSERVED_MIXED_JOB_MEMBERSHIP");
    expect(evidence.sampleTimestampsMs).toEqual([100, 200]);
  });

  test("does not mislabel membership in an unknown job as daemon-caged", () => {
    const evidence = parsePreflightJobMembershipSamples(JSON.stringify({
      schema_version: "ember-issue898-preflight-job-membership-sample-v1",
      sample_index: 1,
      observed_at_ms: 100,
      descendant_count: 1,
      matches: [{
        pid: 42,
        parent_pid: 7,
        command_line: 'python.exe "C:\\repo\\tools\\launch_packet.py" --config a',
        command_line_sha256: "a".repeat(64),
        is_process_in_job: true,
      }],
    }));
    expect(evidence.result).toBe("OBSERVED_IN_SOME_JOB_LIMIT_UNVERIFIED");
    expect(evidence.result).not.toContain("CAGED");
  });

  test("records a vacuous stream as explicit measurement failure", () => {
    const evidence = parsePreflightJobMembershipSamples(JSON.stringify({
      schema_version: "ember-issue898-preflight-job-membership-sample-v1",
      sample_index: 1,
      observed_at_ms: 100,
      descendant_count: 0,
      matches: [],
    }));
    expect(evidence.result).toBe("NEVER_OBSERVED_MEASUREMENT_FAILED");
    expect(evidence.sampleCount).toBe(1);
    expect(evidence.observations).toEqual([]);
  });

  test("refuses malformed or non-monotonic census rows", () => {
    expect(() => parsePreflightJobMembershipSamples("not-json\n")).toThrow(
      "sample JSON is invalid",
    );
    const row = JSON.stringify({
      schema_version: "ember-issue898-preflight-job-membership-sample-v1",
      sample_index: 1,
      observed_at_ms: 100,
      descendant_count: 0,
      matches: [],
    });
    expect(() => parsePreflightJobMembershipSamples(`${row}\n${row}\n`)).toThrow(
      "sample_index is not strictly increasing",
    );
  });
});

describe("parseRuntimeJobEnforcementProbe", () => {
  const expected = {
    jobId: "issue898-probe-negative-launch-1",
    governedPid: 4242,
    outsideControlPid: 77,
    maximumJobMemoryBytes: 1_073_741_824,
  };

  function row(overrides: Record<string, unknown> = {}): string {
    return JSON.stringify({
      schema_version: "ember-issue898-runtime-job-enforcement-v1",
      job_id: expected.jobId,
      job_object_name: "Local\\\\ember-lab-issue898-probe-negative-launch-1",
      governed_pid: expected.governedPid,
      outside_control_pid: expected.outsideControlPid,
      governed_membership_query_succeeded: true,
      governed_is_member: true,
      outside_membership_query_succeeded: true,
      outside_is_member: false,
      extended_limit_query_succeeded: true,
      limit_flags: 0x200,
      job_memory_limit_bytes: expected.maximumJobMemoryBytes,
      ...overrides,
    });
  }

  test("binds exact governed membership, limit, and outside-path control", () => {
    expect(parseRuntimeJobEnforcementProbe(row(), expected)).toEqual({
      schemaVersion: "ember-issue898-runtime-job-enforcement-v1",
      jobId: expected.jobId,
      jobObjectName: "Local\\\\ember-lab-issue898-probe-negative-launch-1",
      governedPid: expected.governedPid,
      outsideControlPid: expected.outsideControlPid,
      governedIsMember: true,
      outsideIsMember: false,
      limitFlags: 0x200,
      jobMemoryLimitBytes: expected.maximumJobMemoryBytes,
      result: "VERIFIED_GOVERNED_WITH_OUTSIDE_CONTROL",
    });
  });

  test("refuses a governed process outside the named target job", () => {
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ governed_is_member: false }),
      expected,
    )).toThrow("governed process is not a member of the named target job");
  });

  test("requires the outside-path control to fail against the same target job", () => {
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ outside_is_member: true }),
      expected,
    )).toThrow("outside control unexpectedly belongs to the named target job");
  });

  test("requires the kernel job-memory flag and exact authenticated limit", () => {
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ limit_flags: 0 }),
      expected,
    )).toThrow("JOB_OBJECT_LIMIT_JOB_MEMORY is absent");
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ job_memory_limit_bytes: expected.maximumJobMemoryBytes - 1 }),
      expected,
    )).toThrow("job-memory limit does not equal the authenticated maximum");
  });

  test("refuses unavailable kernel queries instead of treating false as evidence", () => {
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ governed_membership_query_succeeded: false }),
      expected,
    )).toThrow("governed membership query failed");
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ outside_membership_query_succeeded: false }),
      expected,
    )).toThrow("outside membership query failed");
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ extended_limit_query_succeeded: false }),
      expected,
    )).toThrow("extended job limit query failed");
  });

  test("refuses identity drift in the runtime sample", () => {
    expect(() => parseRuntimeJobEnforcementProbe(
      row({ governed_pid: expected.governedPid + 1 }),
      expected,
    )).toThrow("runtime job enforcement identity does not match governed start");
  });
});
describe("production driver live-query helpers", () => {
  test("loads the changed driver and reads the exact daemon job-object row", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-probe-driver-db-test-"));
    roots.push(root);
    const databasePath = join(root, "ember-lab.sqlite3");
    const database = new Database(databasePath);
    database.exec(
      "CREATE TABLE jobs(job_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, job_object_name TEXT NOT NULL)",
    );
    database
      .query("INSERT INTO jobs(job_id, pid, job_object_name) VALUES (?1, ?2, ?3)")
      .run("run-launch-1", 77, "Local\\ember-lab-run-launch-1");
    database.close();

    const readJobObjectName = (
      productionDriver as Record<string, unknown>
    )["readJobObjectName"];
    expect(typeof readJobObjectName).toBe("function");
    const lookup = (
      readJobObjectName as (path: string, jobId: string) => Promise<string>
    )(
      databasePath,
      "run-launch-1",
    );
    expect(lookup).toBeInstanceOf(Promise);
    expect(await lookup).toBe("Local\\ember-lab-run-launch-1");
    await expect(
      (
        readJobObjectName as (path: string, jobId: string) => Promise<string>
      )(
        databasePath,
        "missing",
      ),
    ).rejects.toThrow("daemon database lacks the exact governed job-object name");
  });

  test("takes exact governed identity from preflight receipt and daemon database", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-probe-authored-start-test-"));
    roots.push(root);
    const databasePath = join(root, "ember-lab.sqlite3");
    const preflightPath = join(root, "launch.preflight.json");
    const runId = "issue898-probe-negative";
    const jobId = `${runId}-launch-1787758320679`;
    const maximumJobMemoryBytes = 1_073_741_824;
    const database = new Database(databasePath);
    database.exec(
      "CREATE TABLE jobs(job_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, job_object_name TEXT NOT NULL, state TEXT NOT NULL)",
    );
    database
      .query(
        "INSERT INTO jobs(job_id, pid, job_object_name, state) VALUES (?1, ?2, ?3, 'running')",
      )
      .run(jobId, 17972, "Local\\ember-lab-exact");
    database.close();
    const writePreflight = (nextJobId: string, maximum: number): void =>
      writeFileSync(
        preflightPath,
        `${JSON.stringify({
          schema_version: "ember-lab-dispatch-preflight-v1",
          result: "PREFLIGHT_PASSED",
          job_id: nextJobId,
          maximum_job_memory_bytes: maximum,
        })}\n`,
      );
    writePreflight(jobId, maximumJobMemoryBytes);

    const readGovernedStartFromArtifacts = (
      productionDriver as Record<string, unknown>
    )["readGovernedStartFromArtifacts"];
    expect(typeof readGovernedStartFromArtifacts).toBe("function");
    const readStart = readGovernedStartFromArtifacts as (
      preflightReceiptPath: string,
      databasePath: string,
      expectedRunId: string,
      expectedMaximumJobMemoryBytes: number,
      timeoutMs?: number,
    ) => Promise<{ governedPid: number; jobId: string }>;
    expect(
      await readStart(preflightPath, databasePath, runId, maximumJobMemoryBytes),
    ).toEqual({ governedPid: 17972, jobId });

    writePreflight(jobId, maximumJobMemoryBytes - 1);
    await expect(
      readStart(preflightPath, databasePath, runId, maximumJobMemoryBytes),
    ).rejects.toThrow("preflight receipt maximum does not match authenticated maximum");

    writePreflight(`foreign-run-launch-1787758320679`, maximumJobMemoryBytes);
    await expect(
      readStart(preflightPath, databasePath, runId, maximumJobMemoryBytes),
    ).rejects.toThrow("preflight receipt job id is not bound to packet run id");

    writePreflight(jobId, maximumJobMemoryBytes);
    const zeroPidDatabase = new Database(databasePath);
    zeroPidDatabase.query("UPDATE jobs SET pid = 0 WHERE job_id = ?1").run(jobId);
    zeroPidDatabase.close();
    await expect(
      readStart(preflightPath, databasePath, runId, maximumJobMemoryBytes, 0),
    ).rejects.toThrow("daemon database lacks positive governed identity for preflight job id");

    // Do not insert an await before Promise.allSettled: attaching both handlers
    // synchronously is what keeps either owned promise from escaping the test.
    const lookup = readStart(
      preflightPath,
      databasePath,
      runId,
      maximumJobMemoryBytes,
      500,
    );
    const update = new Promise<void>((resolveUpdate, rejectUpdate) =>
      setTimeout(() => {
        try {
          const populatedDatabase = new Database(databasePath);
          populatedDatabase.query("UPDATE jobs SET pid = ?1 WHERE job_id = ?2").run(17972, jobId);
          populatedDatabase.close();
          resolveUpdate();
        } catch (error) {
          rejectUpdate(error);
        }
      }, 50),
    );
    expect(await Promise.allSettled([lookup, update])).toEqual([
      { status: "fulfilled", value: { governedPid: 17972, jobId } },
      { status: "fulfilled", value: undefined },
    ]);
  });

  test("executes the hidden kernel probe and emits the closed fail-closed row", async () => {
    if (process.platform !== "win32") return;
    const queryRuntimeJobEnforcement = (
      productionDriver as Record<string, unknown>
    )["queryRuntimeJobEnforcement"];
    expect(typeof queryRuntimeJobEnforcement).toBe("function");
    const jobId = "issue898-query-source-gate";
    const jobObjectName = `Local\\ember-absent-${randomUUID()}`;
    const probe = await (
      queryRuntimeJobEnforcement as (
        jobId: string,
        jobObjectName: string,
        governedPid: number,
        outsidePid: number,
      ) => Promise<{ exitCode: number | null; stderr: string; stdout: string }>
    )(jobId, jobObjectName, process.pid, process.pid);
    expect(probe.exitCode).toBe(0);
    expect(probe.stderr).toBe("");
    expect(JSON.parse(probe.stdout)).toEqual({
      schema_version: "ember-issue898-runtime-job-enforcement-v1",
      job_id: jobId,
      job_object_name: jobObjectName,
      governed_pid: process.pid,
      outside_control_pid: process.pid,
      governed_membership_query_succeeded: false,
      governed_is_member: false,
      outside_membership_query_succeeded: false,
      outside_is_member: false,
      extended_limit_query_succeeded: false,
      limit_flags: 0,
      job_memory_limit_bytes: 0,
    });
  }, 60_000);

  test("kills a timed-out hidden kernel probe and settles exactly once", async () => {
    if (process.platform !== "win32") return;
    const queryRuntimeJobEnforcement = (
      productionDriver as Record<string, unknown>
    )["queryRuntimeJobEnforcement"] as (
      jobId: string,
      jobObjectName: string,
      governedPid: number,
      outsidePid: number,
      timeoutMs?: number,
    ) => Promise<{ exitCode: number | null; stderr: string; stdout: string }>;
    let settlements = 0;
    let timeoutError: (Error & { childPid?: number }) | undefined;
    try {
      await queryRuntimeJobEnforcement(
        "issue898-query-timeout-gate",
        `Local\\ember-absent-${randomUUID()}`,
        process.pid,
        process.pid,
        1,
      ).then(
        (value) => {
          settlements += 1;
          return value;
        },
        (error: Error & { childPid?: number }) => {
          settlements += 1;
          throw error;
        },
      );
    } catch (error) {
      timeoutError = error as Error & { childPid?: number };
    }
    expect(timeoutError?.message).toBe("runtime job enforcement probe timed out after 1 ms");
    expect(timeoutError?.childPid).toBeGreaterThan(0);
    const childPid = timeoutError?.childPid ?? 0;
    let childAlive = true;
    try {
      process.kill(childPid, 0);
    } catch {
      childAlive = false;
    }
    expect(childAlive).toBe(false);
    await Bun.sleep(25);
    expect(settlements).toBe(1);
  }, 60_000);
});
describe("production driver failure observability", () => {
  function driverFunction(name: string): (...args: any[]) => any {
    const value = (productionDriver as Record<string, unknown>)[name];
    expect(typeof value).toBe("function");
    return value as (...args: any[]) => any;
  }

  function fakeTransport(callbackError?: Error): {
    child: unknown;
    written: string[];
  } {
    const listeners = new Set<(error: Error) => void>();
    const written: string[] = [];
    const socket = {
      destroyed: false,
      writable: true,
      once(event: string, listener: (error: Error) => void) {
        if (event === "error") listeners.add(listener);
        return socket;
      },
      off(event: string, listener: (error: Error) => void) {
        if (event === "error") listeners.delete(listener);
        return socket;
      },
      write(data: string, callback: (error?: Error) => void) {
        written.push(data);
        queueMicrotask(() => {
          if (callbackError !== undefined) {
            for (const listener of [...listeners]) listener(callbackError);
          }
          callback(callbackError);
        });
        return callbackError === undefined;
      },
    };
    return { child: { _agent: { inSocket: socket } }, written };
  }

  test("awaits successful ConPTY input delivery", async () => {
    const writePtyData = driverFunction("writePtyData");
    const transport = fakeTransport();
    await writePtyData(transport.child, "/train");
    expect(transport.written).toEqual(["/train"]);
  });

  test("refuses a closed ConPTY input socket at the write boundary", async () => {
    const writePtyData = driverFunction("writePtyData");
    const closed = Object.assign(new Error("Socket is closed"), {
      code: "ERR_SOCKET_CLOSED",
    });
    const transport = fakeTransport(closed);
    await expect(writePtyData(transport.child, "/train")).rejects.toThrow(
      "ConPTY input write failed: Socket is closed",
    );
    expect(transport.written).toEqual(["/train"]);
  });

  test("persists preflight streams exactly and refuses overwrite", () => {
    const persistPreflightProbeStreams = driverFunction(
      "persistPreflightProbeStreams",
    );
    const root = mkdtempSync(join(tmpdir(), "ember-probe-failure-artifacts-"));
    roots.push(root);
    persistPreflightProbeStreams(root, "{\"sample_index\":1}\n", "diagnostic\n");
    expect(readFileSync(join(root, "preflight-probe.stdout.jsonl"), "utf8")).toBe(
      "{\"sample_index\":1}\n",
    );
    expect(readFileSync(join(root, "preflight-probe.stderr.txt"), "utf8")).toBe(
      "diagnostic\n",
    );
    expect(() =>
      persistPreflightProbeStreams(root, "replacement\n", ""),
    ).toThrow();
  });

  test("persists unfiltered cockpit stream and rendered frame with no overwrite", () => {
    const persistCockpitEvidence = driverFunction("persistCockpitEvidence");
    const root = mkdtempSync(join(tmpdir(), "ember-probe-cockpit-artifacts-"));
    roots.push(root);
    const raw = "\u001b[31mOFFER train-exact\u001b[0m\r\n";
    const frame = "OFFER train-exact action=train-launch\n";

    persistCockpitEvidence(root, raw, frame);

    expect(readFileSync(join(root, "cockpit.raw.txt"), "utf8")).toBe(raw);
    expect(readFileSync(join(root, "cockpit.frame.txt"), "utf8")).toBe(frame);
    expect(() =>
      persistCockpitEvidence(root, "replacement\n", "replacement frame\n"),
    ).toThrow();
  });
});
