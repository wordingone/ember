// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export interface GovernedStart {
  governedPid: number;
  jobId: string;
}

export interface TrainFrameObservation {
  governedEvidenceSeen: boolean;
  start: GovernedStart | undefined;
  synchronousRefusal: boolean;
}

export interface PreflightJobMembershipObservation {
  commandLine: string;
  commandLineSha256: string;
  isProcessInJob: boolean;
  observedAtMs: number;
  parentPid: number;
  pid: number;
  sampleIndex: number;
}

export interface PreflightJobMembershipEvidence {
  maximumDescendantCount: number;
  observations: PreflightJobMembershipObservation[];
  result:
    | "OBSERVED_IN_SOME_JOB_LIMIT_UNVERIFIED"
    | "OBSERVED_NOT_IN_ANY_JOB"
    | "OBSERVED_MIXED_JOB_MEMBERSHIP"
    | "NEVER_OBSERVED_MEASUREMENT_FAILED";
  sampleCount: number;
  sampleTimestampsMs: number[];
}

export interface RuntimeJobEnforcementExpected {
  jobId: string;
  governedPid: number;
  outsideControlPid: number;
  maximumJobMemoryBytes: number;
}

export interface RuntimeJobEnforcementEvidence {
  schemaVersion: "ember-issue898-runtime-job-enforcement-v1";
  jobId: string;
  jobObjectName: string;
  governedPid: number;
  outsideControlPid: number;
  governedIsMember: true;
  outsideIsMember: false;
  limitFlags: number;
  jobMemoryLimitBytes: number;
  result: "VERIFIED_GOVERNED_WITH_OUTSIDE_CONTROL";
}

export interface DaemonJobMemoryEnforcementExpected {
  jobId: string;
  governedPid: number;
  maximumJobMemoryBytes: number;
}

export interface DaemonJobMemoryEnforcementEvidence {
  schemaVersion: "ember-lab-job-memory-enforcement-witness-v1";
  witnessKind: "daemon_assignment_time_kernel_query";
  witnessStage: "post_create_pre_resume";
  observedAtMs: number;
  jobId: string;
  jobObjectName: string;
  governedPid: number;
  daemonControlPid: number;
  assignmentMethod: "proc_thread_attribute_job_list";
  limitFlags: number;
  jobMemoryLimitBytes: number;
  result: "VERIFIED_PRE_EXECUTION_KERNEL_ENFORCEMENT";
}

const SYNCHRONOUS_REFUSALS = [
  "error: certified train consumer refused or failed.",
  "error: certified train consumer exited 0 without exactly one valid completion record.",
  "error: certified train consumer response omitted execution_receipt or artifact_root.",
  "no outstanding train-launch offer",
] as const;

function closedObject(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} is not an object`);
  }
  return value as Record<string, unknown>;
}

function positiveInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    throw new Error(`${label} is not a positive safe integer`);
  }
  return value as number;
}

/** Verify a raw kernel-query row against identities fixed before the query.
 * The outside control is tested against the same named target-job handle as
 * the governed process; membership in some unspecified job is not evidence. */
export function parseRuntimeJobEnforcementProbe(
  stream: string,
  expected: RuntimeJobEnforcementExpected,
): RuntimeJobEnforcementEvidence {
  let decoded: unknown;
  try {
    decoded = JSON.parse(stream);
  } catch {
    throw new Error("runtime job enforcement probe JSON is invalid");
  }
  const row = closedObject(decoded, "runtime job enforcement probe");
  const requiredKeys = new Set([
    "schema_version",
    "job_id",
    "job_object_name",
    "governed_pid",
    "outside_control_pid",
    "governed_membership_query_succeeded",
    "governed_is_member",
    "outside_membership_query_succeeded",
    "outside_is_member",
    "extended_limit_query_succeeded",
    "limit_flags",
    "job_memory_limit_bytes",
  ]);
  const actualKeys = Object.keys(row);
  if (
    actualKeys.length !== requiredKeys.size ||
    actualKeys.some((key) => !requiredKeys.has(key))
  ) {
    throw new Error("runtime job enforcement probe keys are not the closed schema");
  }
  if (row["schema_version"] !== "ember-issue898-runtime-job-enforcement-v1") {
    throw new Error("runtime job enforcement probe schema is invalid");
  }
  if (typeof expected.jobId !== "string" || expected.jobId.length === 0) {
    throw new Error("expected governed job id is invalid");
  }
  const expectedGovernedPid = positiveInteger(expected.governedPid, "expected governed pid");
  const expectedOutsidePid = positiveInteger(
    expected.outsideControlPid,
    "expected outside-control pid",
  );
  const expectedMaximum = positiveInteger(
    expected.maximumJobMemoryBytes,
    "expected maximum job memory bytes",
  );
  const governedPid = positiveInteger(row["governed_pid"], "governed_pid");
  const outsideControlPid = positiveInteger(
    row["outside_control_pid"],
    "outside_control_pid",
  );
  if (
    row["job_id"] !== expected.jobId ||
    governedPid !== expectedGovernedPid ||
    outsideControlPid !== expectedOutsidePid
  ) {
    throw new Error("runtime job enforcement identity does not match governed start");
  }
  const jobObjectName = row["job_object_name"];
  if (typeof jobObjectName !== "string" || jobObjectName.length === 0) {
    throw new Error("runtime target job object name is invalid");
  }
  if (row["governed_membership_query_succeeded"] !== true) {
    throw new Error("governed membership query failed");
  }
  if (row["governed_is_member"] !== true) {
    throw new Error("governed process is not a member of the named target job");
  }
  if (row["outside_membership_query_succeeded"] !== true) {
    throw new Error("outside membership query failed");
  }
  if (row["outside_is_member"] !== false) {
    throw new Error("outside control unexpectedly belongs to the named target job");
  }
  if (row["extended_limit_query_succeeded"] !== true) {
    throw new Error("extended job limit query failed");
  }
  const limitFlags = row["limit_flags"];
  if (
    !Number.isSafeInteger(limitFlags) ||
    (limitFlags as number) < 0 ||
    (limitFlags as number) > 0xffff_ffff
  ) {
    throw new Error("runtime job limit flags are invalid");
  }
  if (((limitFlags as number) & 0x200) === 0) {
    throw new Error("JOB_OBJECT_LIMIT_JOB_MEMORY is absent");
  }
  const jobMemoryLimitBytes = positiveInteger(
    row["job_memory_limit_bytes"],
    "job_memory_limit_bytes",
  );
  if (jobMemoryLimitBytes !== expectedMaximum) {
    throw new Error("job-memory limit does not equal the authenticated maximum");
  }
  return {
    schemaVersion: "ember-issue898-runtime-job-enforcement-v1",
    jobId: expected.jobId,
    jobObjectName,
    governedPid,
    outsideControlPid,
    governedIsMember: true,
    outsideIsMember: false,
    limitFlags: limitFlags as number,
    jobMemoryLimitBytes,
    result: "VERIFIED_GOVERNED_WITH_OUTSIDE_CONTROL",
  };
}

/** Select exactly one daemon event and verify its closed, success-only
 * pre-execution witness. The true query booleans are schema gates, not
 * measurements: existence plus the exact flags/bytes is the evidence. */
export function parseDaemonJobMemoryEnforcementWitness(
  receiptValue: unknown,
  expected: DaemonJobMemoryEnforcementExpected,
): DaemonJobMemoryEnforcementEvidence {
  const receipt = closedObject(receiptValue, "terminal operational receipt");
  if (receipt["schema"] !== "ember-lab-operational-receipt-v1") {
    throw new Error("terminal operational receipt schema is invalid");
  }
  if (!new Set(["stopped", "exited", "failed"]).has(String(receipt["state"]))) {
    throw new Error("operational receipt is not terminal");
  }
  if (typeof expected.jobId !== "string" || expected.jobId.length === 0) {
    throw new Error("expected governed job id is invalid");
  }
  const expectedGovernedPid = positiveInteger(expected.governedPid, "expected governed pid");
  const expectedMaximum = positiveInteger(
    expected.maximumJobMemoryBytes,
    "expected maximum job memory bytes",
  );
  if (
    receipt["job_id"] !== expected.jobId ||
    positiveInteger(receipt["pid"], "operational receipt pid") !== expectedGovernedPid
  ) {
    throw new Error("operational receipt does not bind the governed start identity");
  }
  if (!Array.isArray(receipt["events"])) {
    throw new Error("operational receipt events are not an array");
  }
  const preparedEvents = receipt["events"].filter((rawEvent) => {
    const event = closedObject(rawEvent, "operational receipt event");
    return event["kind"] === "job_prepared";
  });
  if (preparedEvents.length !== 1) {
    throw new Error("operational receipt must carry exactly one job_prepared witness event");
  }
  const event = closedObject(preparedEvents[0], "job_prepared event");
  const eventTimestampMs = positiveInteger(event["ts_ms"], "job_prepared ts_ms");
  const payload = closedObject(event["payload"], "job_prepared payload");
  const witness = closedObject(
    payload["job_memory_enforcement_witness"],
    "job-memory enforcement witness",
  );
  const requiredKeys = new Set([
    "schema_version",
    "witness_kind",
    "witness_stage",
    "observed_at_ms",
    "job_object_name",
    "governed_pid",
    "daemon_control_pid",
    "assignment_method",
    "governed_membership_query_succeeded",
    "governed_is_member",
    "daemon_membership_query_succeeded",
    "daemon_is_member",
    "extended_limit_query_succeeded",
    "limit_flags",
    "job_memory_limit_flag_set",
    "expected_maximum_job_memory_bytes",
    "observed_job_memory_limit_bytes",
  ]);
  const actualKeys = Object.keys(witness);
  if (
    actualKeys.length !== requiredKeys.size ||
    actualKeys.some((key) => !requiredKeys.has(key))
  ) {
    throw new Error("job-memory enforcement witness keys are not the closed schema");
  }
  if (
    witness["schema_version"] !== "ember-lab-job-memory-enforcement-witness-v1" ||
    witness["witness_kind"] !== "daemon_assignment_time_kernel_query" ||
    witness["witness_stage"] !== "post_create_pre_resume" ||
    witness["assignment_method"] !== "proc_thread_attribute_job_list"
  ) {
    throw new Error("job-memory enforcement witness literals are invalid");
  }
  if (
    witness["governed_membership_query_succeeded"] !== true ||
    witness["governed_is_member"] !== true ||
    witness["daemon_membership_query_succeeded"] !== true ||
    witness["daemon_is_member"] !== false ||
    witness["extended_limit_query_succeeded"] !== true ||
    witness["job_memory_limit_flag_set"] !== true
  ) {
    throw new Error("job-memory enforcement witness contains a refusal-valued kernel result");
  }
  const observedAtMs = positiveInteger(witness["observed_at_ms"], "witness observed_at_ms");
  if (observedAtMs > eventTimestampMs) {
    throw new Error("job-memory enforcement witness postdates its daemon event");
  }
  const governedPid = positiveInteger(witness["governed_pid"], "witness governed_pid");
  const daemonControlPid = positiveInteger(
    witness["daemon_control_pid"],
    "witness daemon_control_pid",
  );
  if (governedPid !== expectedGovernedPid || payload["pid"] !== governedPid) {
    throw new Error("job-memory enforcement witness does not bind the governed pid");
  }
  const jobObjectName = witness["job_object_name"];
  if (
    typeof jobObjectName !== "string" ||
    jobObjectName.length === 0 ||
    payload["job_object_name"] !== jobObjectName
  ) {
    throw new Error("job-memory enforcement witness does not bind the job object name");
  }
  const limitFlags = witness["limit_flags"];
  if (
    !Number.isSafeInteger(limitFlags) ||
    (limitFlags as number) < 0 ||
    (limitFlags as number) > 0xffff_ffff ||
    ((limitFlags as number) & 0x200) === 0
  ) {
    throw new Error("JOB_OBJECT_LIMIT_JOB_MEMORY is absent from the witnessed flags");
  }
  const declaredMaximum = positiveInteger(
    witness["expected_maximum_job_memory_bytes"],
    "witness expected maximum job memory bytes",
  );
  const observedMaximum = positiveInteger(
    witness["observed_job_memory_limit_bytes"],
    "witness observed job memory limit bytes",
  );
  if (declaredMaximum !== expectedMaximum || observedMaximum !== expectedMaximum) {
    throw new Error("witnessed job-memory limit does not equal the authenticated maximum");
  }
  return {
    schemaVersion: "ember-lab-job-memory-enforcement-witness-v1",
    witnessKind: "daemon_assignment_time_kernel_query",
    witnessStage: "post_create_pre_resume",
    observedAtMs,
    jobId: expected.jobId,
    jobObjectName,
    governedPid,
    daemonControlPid,
    assignmentMethod: "proc_thread_attribute_job_list",
    limitFlags: limitFlags as number,
    jobMemoryLimitBytes: observedMaximum,
    result: "VERIFIED_PRE_EXECUTION_KERNEL_ENFORCEMENT",
  };
}

/** Parse the append-only output of the live Windows descendant sampler. A
 * census with zero positive launch_packet.py observations is recorded as an
 * explicit measurement failure; the production driver persists it, then
 * refuses before confirmation. */
export function parsePreflightJobMembershipSamples(
  stream: string,
): PreflightJobMembershipEvidence {
  const lines = stream.split(/\r?\n/).filter((line) => line.length > 0);
  if (lines.length === 0) throw new Error("preflight job-membership census is empty");
  let previousSampleIndex = 0;
  let maximumDescendantCount = 0;
  const observations: PreflightJobMembershipObservation[] = [];
  const sampleTimestampsMs: number[] = [];
  for (const line of lines) {
    let decoded: unknown;
    try {
      decoded = JSON.parse(line);
    } catch {
      throw new Error("preflight job-membership sample JSON is invalid");
    }
    const row = closedObject(decoded, "preflight job-membership sample");
    if (row["schema_version"] !== "ember-issue898-preflight-job-membership-sample-v1") {
      throw new Error("preflight job-membership sample schema is invalid");
    }
    const sampleIndex = positiveInteger(row["sample_index"], "sample_index");
    if (sampleIndex <= previousSampleIndex) {
      throw new Error("preflight job-membership sample_index is not strictly increasing");
    }
    previousSampleIndex = sampleIndex;
    const observedAtMs = positiveInteger(row["observed_at_ms"], "observed_at_ms");
    sampleTimestampsMs.push(observedAtMs);
    const descendantCount = row["descendant_count"];
    if (!Number.isSafeInteger(descendantCount) || (descendantCount as number) < 0) {
      throw new Error("preflight job-membership descendant_count is invalid");
    }
    maximumDescendantCount = Math.max(maximumDescendantCount, descendantCount as number);
    if (!Array.isArray(row["matches"])) {
      throw new Error("preflight job-membership matches is not an array");
    }
    for (const rawMatch of row["matches"]) {
      const match = closedObject(rawMatch, "preflight job-membership match");
      const digest = match["command_line_sha256"];
      if (typeof digest !== "string" || !/^[0-9a-f]{64}$/.test(digest)) {
        throw new Error("preflight command_line_sha256 is invalid");
      }
      if (typeof match["is_process_in_job"] !== "boolean") {
        throw new Error("preflight is_process_in_job measurement is unavailable");
      }
      const commandLine = match["command_line"];
      if (
        typeof commandLine !== "string" ||
        !/(^|[\\/])launch_packet\.py"?(\s|$)/i.test(commandLine)
      ) {
        throw new Error("preflight matched command line is not launch_packet.py");
      }
      observations.push({
        commandLine,
        commandLineSha256: digest,
        isProcessInJob: match["is_process_in_job"],
        observedAtMs,
        parentPid: positiveInteger(match["parent_pid"], "parent_pid"),
        pid: positiveInteger(match["pid"], "pid"),
        sampleIndex,
      });
    }
  }
  if (observations.length === 0) {
    return {
      maximumDescendantCount,
      observations,
      result: "NEVER_OBSERVED_MEASUREMENT_FAILED",
      sampleCount: lines.length,
      sampleTimestampsMs,
    };
  }
  const memberships = new Set(observations.map((row) => row.isProcessInJob));
  const result = memberships.size > 1
    ? "OBSERVED_MIXED_JOB_MEMBERSHIP"
    : memberships.has(true)
      ? "OBSERVED_IN_SOME_JOB_LIMIT_UNVERIFIED"
      : "OBSERVED_NOT_IN_ANY_JOB";
  return {
    maximumDescendantCount,
    observations,
    result,
    sampleCount: lines.length,
    sampleTimestampsMs,
  };
}

/** Preserve any governed-start evidence across rendered frames. A refusal can
 * authorize pre-receipt cockpit cleanup only when no pid/job evidence has ever
 * appeared; partial rendering must fail toward waiting for the daemon receipt. */
export function observeTrainFrame(
  frame: string,
  previousStart: GovernedStart | undefined,
  previousGovernedEvidenceSeen: boolean,
  authoredStart?: GovernedStart,
): TrainFrameObservation {
  return observeTrainSample(frame, frame, previousStart, previousGovernedEvidenceSeen, authoredStart);
}

/** Classify one sampled viewport while deriving governed-start evidence from the
 * complete append-only ConPTY stream. Evidence may scroll out between samples;
 * cleanup authority must therefore never depend on viewport retention. */
export function observeTrainSample(
  viewport: string,
  completeStream: string,
  previousStart: GovernedStart | undefined,
  previousGovernedEvidenceSeen: boolean,
  authoredStart?: GovernedStart,
): TrainFrameObservation {
  const projectionMarkerSeen = completeStream.includes("governed child pid:");
  const governedEvidenceSeen =
    previousGovernedEvidenceSeen || projectionMarkerSeen || authoredStart !== undefined;
  const start = authoredStart ?? previousStart;
  return {
    governedEvidenceSeen,
    start,
    synchronousRefusal:
      !governedEvidenceSeen && SYNCHRONOUS_REFUSALS.some((marker) => viewport.includes(marker)),
  };
}
