// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export const REFERENCE_SEAT_FLAG = "--reference-seat";

export type ModelSeat = "OWNED_ADMITTED" | "OWNED_DEVELOPMENT" | "REFERENCE_ONLY" | "OFFLINE";

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
   * explicitly declared here (see `selectedModelContract`).
   */
  capabilities?: {
    structuredOutputs: boolean;
  };
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
]);

export function isModelFreeFastPath(argv: string[]): boolean {
  const args = argv
    .slice(2)
    .filter((argument) => argument !== REFERENCE_SEAT_FLAG);
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
}

export interface ModelSeatDecision {
  allowed: boolean;
  seat: ModelSeat | null;
  source: "flag" | "env" | "gpu-free" | "owned-manifest" | "owned-development-manifest" | "none";
  argv: string[];
  ownedIdentity?: OwnedModelIdentity;
  error?: string;
}

/**
 * The truthful, currently-selected model identity + capability contract.
 * See `selectedModelContract` for derivation rules.
 */
export interface SelectedModelContract {
  seat: ModelSeat;
  modelName: string;
  modelConfigSha256: string | null;
  structuredOutputs: boolean;
}

export function resolveModelSeat(
  input: ModelSeatResolutionInput,
): ModelSeatDecision {
  const flagRequested = input.argv
    .slice(2)
    .some((argument) => argument === REFERENCE_SEAT_FLAG);
  const sanitizedArgv = input.argv.filter(
    (argument, index) => index < 2 || argument !== REFERENCE_SEAT_FLAG,
  );
  const envRequested = input.referenceSeatEnv === "1";

  if (flagRequested || envRequested) {
    return {
      allowed: true,
      seat: "REFERENCE_ONLY",
      source: flagRequested ? "flag" : "env",
      argv: sanitizedArgv,
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
 * - A refused decision (no seat) selects no contract.
 * - REFERENCE_ONLY (Qwen or any borrowed model) is reachable only through
 *   this explicit seat, and its identity is always labeled via
 *   `referenceSeatModelName` — it never carries structured-outputs
 *   capability.
 * - OFFLINE carries no model identity and no capability.
 * - An owned identity (OWNED_ADMITTED / OWNED_DEVELOPMENT) reports
 *   `structuredOutputs` true ONLY when the identity declares it AND an
 *   exact `modelConfigSha256` is present to bind that declaration to.
 *   An owned identity without a declaration defaults to false.
 */
export function selectedModelContract(
  decision: ModelSeatDecision,
): SelectedModelContract | null {
  if (!decision.allowed || decision.seat === null) return null;

  if (decision.seat === "REFERENCE_ONLY") {
    return {
      seat: "REFERENCE_ONLY",
      modelName: referenceSeatModelName(decision.ownedIdentity?.modelName),
      modelConfigSha256: null,
      structuredOutputs: false,
    };
  }

  if (decision.seat === "OFFLINE") {
    return {
      seat: "OFFLINE",
      modelName: "OFFLINE",
      modelConfigSha256: null,
      structuredOutputs: false,
    };
  }

  const identity = decision.ownedIdentity;
  if (!identity) return null;

  const modelConfigSha256 =
    typeof identity.modelConfigSha256 === "string" &&
    identity.modelConfigSha256.trim() !== ""
      ? identity.modelConfigSha256
      : null;

  return {
    seat: decision.seat,
    modelName: identity.modelName,
    modelConfigSha256,
    structuredOutputs:
      modelConfigSha256 !== null &&
      identity.capabilities?.structuredOutputs === true,
  };
}
