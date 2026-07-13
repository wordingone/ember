// goal_id: EMBER-01
// workstream_id: EMBER-01A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export const REFERENCE_SEAT_FLAG = "--reference-seat";

export type ModelSeat = "REFERENCE_ONLY" | "OFFLINE";

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
}

export interface ModelSeatDecision {
  allowed: boolean;
  seat: ModelSeat | null;
  source: "flag" | "env" | "gpu-free" | "none";
  argv: string[];
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
