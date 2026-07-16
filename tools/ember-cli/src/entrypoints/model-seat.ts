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
