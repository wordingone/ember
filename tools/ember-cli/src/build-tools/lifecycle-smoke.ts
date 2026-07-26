// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// build-tools/lifecycle-smoke.ts — closed receipt contract for the compiled
// Ember operator lifecycle smoke. The live ConPTY driver writes this receipt;
// CI and independent reviewers revalidate it against the immutable source,
// binary, rebuild, and builder bindings.

const SHA256 = /^[0-9a-f]{64}$/;
const GIT_COMMIT = /^[0-9a-f]{40}$/;
const SAFE_ARTIFACT = /^(?!\/)(?![A-Za-z]:)(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._/-]+$/;

export const LIFECYCLE_ACTIONS = [
  "launch",
  "train",
  "observe",
  "pause",
  "resume",
  "save",
  "terminate",
  "reload",
  "continue",
] as const;

export type LifecycleAction = (typeof LIFECYCLE_ACTIONS)[number];

export interface LifecycleSurfaceCommand {
  name: string;
  aliases?: readonly string[];
}

export interface LifecycleSurfaceRow {
  action: LifecycleAction;
  input: string;
  command: string;
  status: "AVAILABLE" | "MISSING";
}

const LIFECYCLE_SURFACE_PLAN: ReadonlyArray<{
  action: LifecycleAction;
  input: string;
  command: string;
}> = [
  { action: "launch", input: "Ember.cmd", command: "compiled-entrypoint" },
  { action: "train", input: "/train", command: "train" },
  { action: "observe", input: "/watch", command: "watch" },
  { action: "pause", input: "/finetune pause smoke-run", command: "finetune" },
  { action: "resume", input: "/finetune resume smoke-run", command: "finetune" },
  {
    action: "save",
    input: "/model checkpoint save <smoke-target>",
    command: "model",
  },
  {
    action: "terminate",
    input: "/finetune stop smoke-run",
    command: "finetune",
  },
  {
    action: "reload",
    input: "/model checkpoint load <smoke-target>",
    command: "model",
  },
  { action: "continue", input: "/continue", command: "resume" },
];

/**
 * Inspect the real registry surface without granting operability credit.
 * AVAILABLE means only that the command/alias is reachable; the ConPTY driver
 * must still execute it and prove an effect-bearing frame delta.
 */
export function inspectLifecycleSurface(
  commands: readonly LifecycleSurfaceCommand[],
): LifecycleSurfaceRow[] {
  const reachable = new Set<string>();
  for (const command of commands) {
    reachable.add(command.name);
    for (const alias of command.aliases ?? []) reachable.add(alias);
  }
  return LIFECYCLE_SURFACE_PLAN.map((row) => ({
    ...row,
    status:
      row.command === "compiled-entrypoint" || reachable.has(row.command)
        ? "AVAILABLE"
        : "MISSING",
  }));
}

export interface LifecycleStateEvidence {
  artifact: string;
  before_exists: boolean;
  before_sha256: string | null;
  after_exists: boolean;
  after_sha256: string | null;
  delta_sha256: string;
  command: string | null;
  run_id: string | null;
}

export interface LifecycleActionEvidence {
  action: LifecycleAction;
  ordinal: number;
  input_sha256: string;
  before_frame_sha256: string;
  after_frame_sha256: string;
  effect_evidence_sha256: string;
  effect_kind:
    | "observable-readiness"
    | "observable-product-effect"
    | "preflight-only"
    | "durable-control-append"
    | "durable-artifact-publication"
    | "observable-refusal";
  outcome: "PASS" | "PREFLIGHT_ONLY" | "MISSING" | "REFUSED" | "NO_EFFECT";
  output_excerpt: string;
  state_evidence: LifecycleStateEvidence | null;
  frame_artifact: string;
  repair_item: string | null;
}

export interface LifecycleReceipt {
  schema_version: "ember-cli-lifecycle-smoke/v2";
  evidence_class: "LIVE_COMPILED_BINARY_CONPTY";
  source_commit: string;
  binary: {
    artifact: string;
    sha256_before: string;
    sha256_after: string;
  };
  reproducible_rebuild: {
    sha256: string;
    builder_basename: string;
    builder_sha256_before: string;
    builder_sha256_after: string;
    builder_version: string;
  };
  readiness: {
    marker: "EMBER_READY;v1";
    observed: boolean;
    elapsed_ms: number;
    frame_sha256: string;
  };
  actions: LifecycleActionEvidence[];
  termination: {
    explicit_requested: boolean;
    child_exit_observed: boolean;
    cleanup_attempted: boolean;
    survivors: number;
  };
  artifacts: {
    receipt: string;
    diagnostics: string;
  };
  operator_contract_mapping: string;
  accepted_instrument_run: true;
  claim_boundary: {
    model_capability: false;
    training_quality: false;
    checkpoint_sufficiency: false;
    benchmark: false;
  };
}

export interface LifecycleExpectedBindings {
  sourceCommit: string;
  binarySha256: string;
  builderSha256: string;
}

function requireSha(value: string, label: string): void {
  if (!SHA256.test(value)) throw new Error(`${label} must be lowercase SHA-256`);
}

function requireGitCommit(value: string, label: string): void {
  if (!GIT_COMMIT.test(value)) throw new Error(`${label} must be a lowercase 40-hex Git commit`);
}

function requireArtifact(value: string, label: string): void {
  if (!SAFE_ARTIFACT.test(value) || value.includes("\\")) {
    throw new Error(`${label} must be a path-free repository artifact`);
  }
}

function requireClosedKeys(
  value: object,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
    throw new Error(`${label} has missing or unknown fields`);
  }
}

export function validateLifecycleReceipt(
  receipt: LifecycleReceipt,
  expected: LifecycleExpectedBindings,
): { ok: true; action_count: 9 } {
  requireClosedKeys(receipt, [
    "schema_version", "evidence_class", "source_commit", "binary",
    "reproducible_rebuild", "readiness", "actions", "termination",
    "artifacts", "operator_contract_mapping", "accepted_instrument_run",
    "claim_boundary",
  ], "receipt");
  if (receipt.schema_version !== "ember-cli-lifecycle-smoke/v2") {
    throw new Error("unsupported lifecycle receipt schema");
  }
  if (receipt.evidence_class !== "LIVE_COMPILED_BINARY_CONPTY") {
    throw new Error("wrong evidence class");
  }
  requireGitCommit(receipt.source_commit, "source commit");
  requireGitCommit(expected.sourceCommit, "expected source commit");
  requireSha(expected.binarySha256, "expected binary");
  requireSha(expected.builderSha256, "expected builder");
  if (receipt.source_commit !== expected.sourceCommit) {
    throw new Error("forged source binding");
  }

  requireClosedKeys(
    receipt.binary,
    ["artifact", "sha256_before", "sha256_after"],
    "binary",
  );
  requireArtifact(receipt.binary.artifact, "binary artifact");
  requireSha(receipt.binary.sha256_before, "binary before");
  requireSha(receipt.binary.sha256_after, "binary after");
  if (
    receipt.binary.sha256_before !== expected.binarySha256 ||
    receipt.binary.sha256_after !== expected.binarySha256
  ) {
    throw new Error("forged or changing binary binding");
  }

  requireClosedKeys(receipt.reproducible_rebuild, [
    "sha256", "builder_basename", "builder_sha256_before",
    "builder_sha256_after", "builder_version",
  ], "reproducible rebuild");
  requireSha(receipt.reproducible_rebuild.sha256, "rebuild");
  requireSha(receipt.reproducible_rebuild.builder_sha256_before, "builder before");
  requireSha(receipt.reproducible_rebuild.builder_sha256_after, "builder after");
  if (
    receipt.reproducible_rebuild.sha256 !== expected.binarySha256 ||
    receipt.reproducible_rebuild.builder_sha256_before !== expected.builderSha256 ||
    receipt.reproducible_rebuild.builder_sha256_after !== expected.builderSha256 ||
    receipt.reproducible_rebuild.builder_basename.trim() === "" ||
    receipt.reproducible_rebuild.builder_basename.includes("/") ||
    receipt.reproducible_rebuild.builder_basename.includes("\\") ||
    receipt.reproducible_rebuild.builder_version.trim() === ""
  ) {
    throw new Error("forged reproducible rebuild binding");
  }

  requireClosedKeys(
    receipt.readiness,
    ["marker", "observed", "elapsed_ms", "frame_sha256"],
    "readiness",
  );
  requireSha(receipt.readiness.frame_sha256, "readiness frame");
  if (
    receipt.readiness.marker !== "EMBER_READY;v1" ||
    receipt.readiness.observed !== true ||
    !Number.isSafeInteger(receipt.readiness.elapsed_ms) ||
    receipt.readiness.elapsed_ms < 0
  ) {
    throw new Error("readiness must be marker-observed, never sleep-only");
  }

  if (
    !Array.isArray(receipt.actions) ||
    receipt.actions.length !== LIFECYCLE_ACTIONS.length ||
    receipt.actions.some((row, index) => row.action !== LIFECYCLE_ACTIONS[index])
  ) {
    throw new Error("ordered actions must contain the exact nine lifecycle verbs");
  }
  receipt.actions.forEach((row, index) => {
    requireClosedKeys(row, [
      "action", "ordinal", "input_sha256", "before_frame_sha256",
      "after_frame_sha256", "effect_evidence_sha256", "effect_kind",
      "outcome", "output_excerpt", "state_evidence", "frame_artifact",
      "repair_item",
    ], `action ${index + 1}`);
    requireSha(row.input_sha256, `${row.action} input`);
    requireSha(row.before_frame_sha256, `${row.action} before frame`);
    requireSha(row.after_frame_sha256, `${row.action} after frame`);
    requireSha(row.effect_evidence_sha256, `${row.action} effect evidence`);
    requireArtifact(row.frame_artifact, `${row.action} frame artifact`);
    if (row.ordinal !== index + 1) throw new Error("ordered actions have a wrong ordinal");
    if (row.output_excerpt.trim() === "") {
      throw new Error(`${row.action} output excerpt is absent`);
    }
    if (row.outcome === "NO_EFFECT") {
      throw new Error(`${row.action} NO_EFFECT is an instrument failure`);
    }

    const isDurable =
      row.effect_kind === "durable-control-append" ||
      row.effect_kind === "durable-artifact-publication";
    if (isDurable) {
      if (row.outcome !== "PASS" || row.state_evidence === null) {
        throw new Error(`${row.action} durable state evidence is absent`);
      }
      const state = row.state_evidence;
      requireClosedKeys(state, [
        "artifact", "before_exists", "before_sha256", "after_exists",
        "after_sha256", "delta_sha256", "command", "run_id",
      ], `${row.action} state evidence`);
      requireArtifact(state.artifact, `${row.action} state artifact`);
      requireSha(state.delta_sha256, `${row.action} state delta`);
      if (state.before_exists) {
        if (state.before_sha256 === null) {
          throw new Error(`${row.action} durable state before hash is absent`);
        }
        requireSha(state.before_sha256, `${row.action} state before`);
      } else if (state.before_sha256 !== null) {
        throw new Error(`${row.action} nonexistent prior state has a hash`);
      }
      if (!state.after_exists || state.after_sha256 === null) {
        throw new Error(`${row.action} durable state after bytes are absent`);
      }
      requireSha(state.after_sha256, `${row.action} state after`);
      if (
        (state.before_exists && state.before_sha256 === state.after_sha256) ||
        state.delta_sha256 !== row.effect_evidence_sha256
      ) {
        throw new Error(`${row.action} durable state is unchanged or unbound`);
      }
      const expectedControl: Partial<Record<LifecycleAction, string>> = {
        pause: "pause",
        resume: "resume",
        terminate: "stop",
      };
      if (row.effect_kind === "durable-control-append") {
        if (
          state.command !== expectedControl[row.action] ||
          state.run_id !== "smoke-run"
        ) {
          throw new Error(`${row.action} control command is not state-bound`);
        }
      } else if (
        row.action !== "save" ||
        state.command !== null ||
        state.run_id !== null
      ) {
        throw new Error(`${row.action} publication state is malformed`);
      }
    } else if (row.state_evidence !== null) {
      throw new Error(`${row.action} nondurable outcome carries fake state`);
    }

    if (row.outcome === "PASS") {
      if (row.before_frame_sha256 === row.after_frame_sha256) {
        throw new Error(`${row.action} is missing an effect-bearing frame delta`);
      }
      const expectedEffect: Partial<Record<LifecycleAction, string>> = {
        launch: "observable-readiness",
        observe: "observable-product-effect",
        pause: "durable-control-append",
        resume: "durable-control-append",
        save: "durable-artifact-publication",
        terminate: "durable-control-append",
      };
      if (row.effect_kind !== expectedEffect[row.action] || row.repair_item !== null) {
        throw new Error(`${row.action} PASS effect is lexical-only or mismapped`);
      }
    } else if (row.outcome === "PREFLIGHT_ONLY") {
      if (
        row.action !== "train" ||
        row.effect_kind !== "preflight-only" ||
        typeof row.repair_item !== "string" ||
        row.repair_item.trim() === ""
      ) {
        throw new Error("train preflight-only outcome is not truthfully bound");
      }
    } else if (
      !["MISSING", "REFUSED"].includes(row.outcome) ||
      row.effect_kind !== "observable-refusal" ||
      typeof row.repair_item !== "string" ||
      row.repair_item.trim() === ""
    ) {
      throw new Error(`${row.action} red outcome is not truthfully repair-bound`);
    }
  });

  const save = receipt.actions.find((row) => row.action === "save")!;
  const reload = receipt.actions.find((row) => row.action === "reload")!;
  if (
    reload.outcome !== "PASS" &&
    !save.output_excerpt.includes("not /model checkpoint load compatible")
  ) {
    throw new Error("save/reload incompatibility quote is missing");
  }
  const continued = receipt.actions.find((row) => row.action === "continue")!;
  if (
    continued.outcome === "MISSING" &&
    !/unknown command|not registered/i.test(continued.output_excerpt)
  ) {
    throw new Error("missing continue surface lacks exact observable evidence");
  }

  requireClosedKeys(receipt.termination, [
    "explicit_requested", "child_exit_observed", "cleanup_attempted", "survivors",
  ], "termination");
  if (
    receipt.termination.explicit_requested !== true ||
    receipt.termination.child_exit_observed !== true ||
    receipt.termination.cleanup_attempted !== true ||
    receipt.termination.survivors !== 0
  ) {
    throw new Error("termination did not prove an exited, cleaned, leak-free child");
  }

  requireClosedKeys(receipt.artifacts, ["receipt", "diagnostics"], "artifacts");
  requireArtifact(receipt.artifacts.receipt, "receipt artifact");
  requireArtifact(receipt.artifacts.diagnostics, "diagnostics artifact");

  if (
    receipt.accepted_instrument_run !== true ||
    !receipt.operator_contract_mapping.includes("/train") ||
    !receipt.operator_contract_mapping.includes("/watch") ||
    !receipt.operator_contract_mapping.includes("/finetune") ||
    !receipt.operator_contract_mapping.includes("/model") ||
    !receipt.operator_contract_mapping.includes("resume")
  ) {
    throw new Error("heterogeneous operator contract mapping is not preserved");
  }

  requireClosedKeys(receipt.claim_boundary, [
    "model_capability", "training_quality", "checkpoint_sufficiency", "benchmark",
  ], "claim boundary");
  if (Object.values(receipt.claim_boundary).some((value) => value !== false)) {
    throw new Error("lifecycle smoke cannot claim model or benchmark capability");
  }

  return { ok: true, action_count: 9 };
}
