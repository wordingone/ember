// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export const REFERENCE_SEAT_FLAG = "--reference-seat";

/** Operator-selected open-weights harness mode: run any non-Ember model the
 * operator chose (e.g. one fetched by `ember pull`) as the working model.  It
 * is labelled OPEN_WEIGHTS everywhere and, like REFERENCE_ONLY, never carries
 * an owned identity, a modelConfigSha256, or owned capability. */
export const OPEN_WEIGHTS_FLAG = "--open-weights";

export type ModelSeat = "OWNED_ADMITTED" | "OWNED_DEVELOPMENT" | "REFERENCE_ONLY" | "OPEN_WEIGHTS" | "OFFLINE";

/** The operator-visible seat lifecycle.  This is a projection of the existing
 * model-seat authority, not a second launcher or ownership registry. */
export type ModelSeatPhase = "ABSENT" | "LOADING" | "RESIDENT";

export type ModelSeatState =
  | { phase: "ABSENT"; owner?: string; endpoint?: never; vramBytes?: never; note?: string }
  | { phase: "LOADING"; owner?: string; endpoint?: never; vramBytes?: never; note?: string }
  | { phase: "RESIDENT"; owner: string; endpoint: string; vramBytes: number; vramUnmeasured?: boolean; note?: string };

/** Runtime fail-closed guard for stale or untyped cockpit state.  Internal
 * callers get the discriminated-union guarantee above; this guard prevents a
 * malformed external value from ever being displayed as resident. */
export function normalizeModelSeatState(state: ModelSeatState): ModelSeatState {
  if (state.phase !== "RESIDENT") return state;
  if (
    typeof state.owner === "string" && state.owner.trim() !== "" &&
    typeof state.endpoint === "string" && state.endpoint.trim() !== "" &&
    typeof state.vramBytes === "number" &&
    Number.isSafeInteger(state.vramBytes) && state.vramBytes >= 0
  ) {
    return state;
  }
  return state.note ? { phase: "ABSENT", note: state.note } : { phase: "ABSENT" };
}

interface OwnedServerLaunchBase {
  pythonExecutable: string;
  serverPath: string;
  checkpointDir: string;
  tokenizerPath: string;
  mode: "INTERACTIVE";
}

export type OwnedServerLaunch =
  | (OwnedServerLaunchBase & {
      authorityKind: "ADMISSION";
      modelConfigPath: string;
      runManifestPath: string;
      trustedVerifierRegistryPath: string;
      trustedVerifierRegistrySha256: string;
      trustedVerifierRegistryApprovalPath: string;
      trustedVerifierRegistryApprovalSha256: string;
    })
  | (OwnedServerLaunchBase & {
      authorityKind: "DEVELOPMENT";
      cleanupRuntimeSnapshot: () => void;
      developmentManifestSha256: string;
      developmentManifestPath: string;
      modelConfigPath: string;
      runtimeIndexPath: string;
      runtimeIndexSha256: string;
    });

/**
 * A structured-outputs capability declaration bound to an EXACT
 * `modelConfigSha256`. `selectedModelContract` grants the capability only
 * when this hash equals the served identity's own `modelConfigSha256` —
 * a mismatched or missing hash never grants the capability, regardless of
 * the `structuredOutputs` flag's value.
 */
export interface ModelConfigCapabilities {
  modelConfigSha256: string;
  structuredOutputs: boolean;
}

export interface OwnedModelIdentity {
  seat?: "OWNED_ADMITTED" | "OWNED_DEVELOPMENT";
  claimStatus?: "NON_ADMISSIBLE";
  tokensSeen?: number;
  allocatedParameters?: number;
  activeParameters?: number;
  checkpointSha256: string;
  endpointUrl: string;
  identityUrl: string;
  modelConfigSha256: string;
  modelName: string;
  modelFormat?: string;
  serverSourceSha256: string;
  tokenizerSha256: string;
  launch?: OwnedServerLaunch;
  /**
   * Capability declaration bound to this identity's exact `modelConfigSha256`.
   * Absent by default — an owned identity carries no capability unless it is
   * explicitly declared here AND its own `modelConfigSha256` equals the
   * served identity's `modelConfigSha256` above (see `selectedModelContract`).
   */
  modelConfigCapabilities?: ModelConfigCapabilities;
}

export interface OwnedResidentIdentity extends OwnedModelIdentity {
  vramBytes: number;
}

const MODEL_FREE_FAST_FLAGS = new Set([
  "--help",
  "-h",
  "--version",
  "-v",
  "-V",
  "--diag-crash",
  "--diag-startup",
  "--diagnostics",
  "--dump-system-prompt",
  "--watch",
  "goal-session-smoke",
  "pull",
]);

export function isModelFreeFastPath(argv: string[]): boolean {
  const args = argv
    .slice(2)
    .filter((argument) => argument !== REFERENCE_SEAT_FLAG && argument !== OPEN_WEIGHTS_FLAG);
  const first = args[0] ?? "";
  return (
    MODEL_FREE_FAST_FLAGS.has(first) ||
    (first === "gh" && args[1] === "doctor")
  );
}

export interface ModelSeatResolutionInput {
  argv: string[];
  explicitModelUrl: string | undefined;
  gpuFreeRequested: boolean;
  referenceSeatEnv: string | undefined;
  ownedIdentity?: OwnedModelIdentity;
  /**
   * The exact identity of the borrowed/reference model (e.g. "Qwen2.5-72B-
   * Instruct") when an explicit REFERENCE_ONLY seat is requested. Carried
   * through to `ModelSeatDecision.referenceModelName` so `selectedModelContract`
   * never has to fall back to `ownedIdentity` (which a REFERENCE_ONLY decision
   * never carries) and never silently collapses to "unidentified-model" when
   * the caller actually knows the identity.
   */
  referenceModelName?: string;
  /** "1" when EMBER_OPEN_WEIGHTS requests the open-weights harness mode. */
  openWeightsEnv?: string;
  /** True when the operator's models.json declares `"seat": "open-weights"`. */
  openWeightsConfig?: boolean;
}

export interface ModelSeatDecision {
  allowed: boolean;
  seat: ModelSeat | null;
  source: "flag" | "env" | "config" | "gpu-free" | "owned-manifest" | "owned-development-manifest" | "none";
  argv: string[];
  ownedIdentity?: OwnedModelIdentity;
  /** Set only when `seat` is REFERENCE_ONLY or OPEN_WEIGHTS; see `ModelSeatResolutionInput.referenceModelName`. */
  referenceModelName?: string;
  error?: string;
}

/**
 * The truthful, currently-selected model identity + capability contract for
 * an explicit REFERENCE_ONLY seat (Qwen or any other borrowed model). Its
 * `modelName` is always derived through `referenceSeatModelName` and it never
 * carries `modelConfigSha256` or `structuredOutputs` capability — a borrowed
 * model is never presented as owned.
 */
export interface ReferenceModelContract {
  seat: "REFERENCE_ONLY";
  modelName: string;
  modelConfigSha256: null;
  structuredOutputs: false;
}

/**
 * The truthful, currently-selected model identity + capability contract for
 * an owned Ember model (admitted or development). `structuredOutputs` is
 * true only when bound to the exact served `modelConfigSha256` — see
 * `selectedModelContract`.
 */
export interface OwnedModelContract {
  seat: "OWNED_ADMITTED" | "OWNED_DEVELOPMENT";
  modelName: string;
  modelConfigSha256: string | null;
  structuredOutputs: boolean;
}

/**
 * The truthful, currently-selected model identity + capability contract.
 * See `selectedModelContract` for derivation rules. OFFLINE and refused
 * seats never produce a contract at all (`selectedModelContract` returns
 * `undefined`) — there is intentionally no `OfflineModelContract` variant
 * reachable from `selectedModelContract`, so a consumer can never be handed
 * a callable-looking model identity for a seat with no model.
 */
/** Contract for the operator-selected open-weights harness mode.  Same
 * invariants as REFERENCE_ONLY: never owned, no config hash, no capability. */
export interface OpenWeightsModelContract {
  seat: "OPEN_WEIGHTS";
  modelName: string;
  modelConfigSha256: null;
  structuredOutputs: false;
}

export type SelectedModelContract = ReferenceModelContract | OpenWeightsModelContract | OwnedModelContract;

export function resolveModelSeat(
  input: ModelSeatResolutionInput,
): ModelSeatDecision {
  const flagRequested = input.argv
    .slice(2)
    .some((argument) => argument === REFERENCE_SEAT_FLAG);
  const openWeightsFlag = input.argv
    .slice(2)
    .some((argument) => argument === OPEN_WEIGHTS_FLAG);
  const sanitizedArgv = input.argv.filter(
    (argument, index) =>
      index < 2 || (argument !== REFERENCE_SEAT_FLAG && argument !== OPEN_WEIGHTS_FLAG),
  );
  const envRequested = input.referenceSeatEnv === "1";

  // Open-weights harness mode: an explicit operator choice (flag, env, or a
  // models.json "seat") to work with a non-Ember model.  It never overrides
  // an explicit --reference-seat request, which keeps its parity semantics.
  if (!flagRequested && !envRequested &&
      (openWeightsFlag || input.openWeightsEnv === "1" || input.openWeightsConfig === true)) {
    return {
      allowed: true,
      seat: "OPEN_WEIGHTS",
      source: openWeightsFlag ? "flag" : input.openWeightsEnv === "1" ? "env" : "config",
      argv: sanitizedArgv,
      referenceModelName: input.referenceModelName,
    };
  }

  if (flagRequested || envRequested) {
    return {
      allowed: true,
      seat: "REFERENCE_ONLY",
      source: flagRequested ? "flag" : "env",
      argv: sanitizedArgv,
      referenceModelName: input.referenceModelName,
    };
  }

  if (input.gpuFreeRequested && input.explicitModelUrl === undefined) {
    return {
      allowed: true,
      seat: "OFFLINE",
      source: "gpu-free",
      argv: sanitizedArgv,
    };
  }

  if (input.ownedIdentity) {
    const ownedSeat = input.ownedIdentity.seat ?? "OWNED_ADMITTED";
    if (
      ownedSeat === "OWNED_DEVELOPMENT" &&
      (input.ownedIdentity.claimStatus !== "NON_ADMISSIBLE" ||
        !Number.isSafeInteger(input.ownedIdentity.tokensSeen) ||
        (input.ownedIdentity.tokensSeen ?? -1) < 0 ||
        input.ownedIdentity.modelName !==
          "ember-owned-development:" + input.ownedIdentity.checkpointSha256.slice(0, 12))
    ) {
      return {
        allowed: false,
        seat: null,
        source: "none",
        argv: sanitizedArgv,
        error: "owned development identity is not exact and NON_ADMISSIBLE",
      };
    }
    const admittedEndpoint = input.ownedIdentity.endpointUrl.replace(/\/$/, "");
    const explicitEndpoint = input.explicitModelUrl?.replace(/\/$/, "");
    if (explicitEndpoint !== undefined && explicitEndpoint !== admittedEndpoint) {
      return {
        allowed: false,
        seat: null,
        source: "none",
        argv: sanitizedArgv,
        error:
          "EMBER_MODEL_URL does not match the admitted owned endpoint; " +
          "ordinary launch will not redirect an OWNED_ADMITTED identity. " +
          "Use --reference-seat for explicit comparison models.",
      };
    }
    return {
      allowed: true,
      seat: ownedSeat,
      source: ownedSeat === "OWNED_ADMITTED"
        ? "owned-manifest"
        : "owned-development-manifest",
      argv: sanitizedArgv,
      ownedIdentity: input.ownedIdentity,
    };
  }

  return {
    allowed: false,
    seat: null,
    source: "none",
    argv: sanitizedArgv,
    error:
      "no admitted owned Ember identity is available; ordinary launch refuses " +
      "persisted endpoints, managed models, and explicit model URLs. Use " +
      "--reference-seat for explicit REFERENCE_ONLY parity testing or " +
      "EMBER_GPU_FREE=1 for offline observation.",
  };
}

export function openWeightsModelName(modelName: string | undefined): string {
  const subject = modelName?.trim() || "unidentified-model";
  return subject.startsWith("OPEN_WEIGHTS: ")
    ? subject
    : "OPEN_WEIGHTS: " + subject;
}

export function referenceSeatModelName(modelName: string | undefined): string {
  const subject = modelName?.trim() || "unidentified-model";
  return subject.startsWith("REFERENCE_ONLY: ")
    ? subject
    : "REFERENCE_ONLY: " + subject;
}

/**
 * The truthful, currently-selected model identity + capability contract,
 * derived from a `ModelSeatDecision`. Never a hardcoded model-name literal.
 *
 * - A refused decision (no seat) selects no contract: returns `undefined`.
 * - REFERENCE_ONLY (Qwen or any borrowed model) is reachable only through
 *   this explicit seat. Its identity is carried via
 *   `decision.referenceModelName` (never read from `ownedIdentity`, which a
 *   REFERENCE_ONLY decision never carries) and always labeled through
 *   `referenceSeatModelName` — it never carries structured-outputs
 *   capability.
 * - OFFLINE carries no model identity and no capability: returns
 *   `undefined`, never a callable-looking contract.
 * - An owned identity (OWNED_ADMITTED / OWNED_DEVELOPMENT) reports
 *   `structuredOutputs` true ONLY when `modelConfigCapabilities` is declared
 *   AND its `modelConfigSha256` equals EXACTLY the served identity's own
 *   `modelConfigSha256`. A missing declaration, a missing served hash, or a
 *   mismatched hash all default to false.
 */
export function selectedModelContract(
  decision: ModelSeatDecision,
): SelectedModelContract | undefined {
  if (!decision.allowed || decision.seat === null) return undefined;

  if (decision.seat === "REFERENCE_ONLY") {
    return {
      seat: "REFERENCE_ONLY",
      modelName: referenceSeatModelName(decision.referenceModelName),
      modelConfigSha256: null,
      structuredOutputs: false,
    };
  }

  if (decision.seat === "OPEN_WEIGHTS") {
    return {
      seat: "OPEN_WEIGHTS",
      modelName: openWeightsModelName(decision.referenceModelName),
      modelConfigSha256: null,
      structuredOutputs: false,
    };
  }

  if (decision.seat === "OFFLINE") {
    // OFFLINE observes with no model at all -- never hand a consumer a
    // callable-looking contract for a seat that has no model.
    return undefined;
  }

  const identity = decision.ownedIdentity;
  if (!identity) return undefined;

  const modelConfigSha256 =
    typeof identity.modelConfigSha256 === "string" &&
    identity.modelConfigSha256.trim() !== ""
      ? identity.modelConfigSha256
      : null;

  const capabilitiesBoundToServedHash =
    modelConfigSha256 !== null &&
    identity.modelConfigCapabilities?.modelConfigSha256 === modelConfigSha256;

  return {
    seat: decision.seat,
    modelName: identity.modelName,
    modelConfigSha256,
    structuredOutputs:
      capabilitiesBoundToServedHash &&
      identity.modelConfigCapabilities?.structuredOutputs === true,
  };
}
