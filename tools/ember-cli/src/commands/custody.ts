// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/custody.ts — /custody status (alias /seat): read-only exposure of the
// current model seat classification (OWNED_ADMITTED | OWNED_DEVELOPMENT |
// REFERENCE_ONLY | OFFLINE). Pure exposure of the existing classification
// logic in entrypoints/model-seat.ts (resolveModelSeat / selectedModelContract)
// -- no new backend logic, no mutation, no seat/server side effects. Prior to
// this command, only entrypoints/process-entry.ts (boot-time) and
// commands/ultraplan.ts (via an injected `getModelContract` dependency) ever
// read a seat decision; there was no operator-visible way to ask "what seat is
// this session actually in right now".

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  referenceSeatModelName,
  resolveModelSeat,
  selectedModelContract,
  type ModelSeatDecision,
  type ModelSeatResolutionInput,
  type SelectedModelContract,
} from "../entrypoints/model-seat.ts";
import {
  loadOwnedDevelopmentIdentity,
  loadOwnedModelIdentity,
} from "../entrypoints/owned-seat-loader.ts";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import {
  resolveEmberRepoRootOrCwd,
  resolveEmberSourceRootOrCwd,
} from "../utils/repo-root.ts";
import {
  MalformedBindingArgError,
  parseBindingArg,
  readRootBindingsStore,
  rootBindingsStorePath,
  writeRootBinding,
  type CustodyBindingsDeps,
  type RootBindingsStore,
} from "../services/custody-bindings.ts";

// ---------------------------------------------------------------------------
// Deps (injectable for testing)
// ---------------------------------------------------------------------------

interface CustodyCommandDeps {
  /**
   * Returns the CURRENT seat classification for this session. Tests inject a
   * canned `ModelSeatDecision` directly (matching the `getModelContract`
   * seam `commands/ultraplan.ts` already uses); production defaults to
   * `_defaultGetModelSeatDecision`, which re-derives the decision the exact
   * way `entrypoints/process-entry.ts::main()` does at boot -- same
   * functions, same env-var inputs, same owned-identity fallback -- but with
   * zero side effects (never spawns/binds a server, never mutates env).
   */
  getModelSeatDecision?: () => ModelSeatDecision;
  /** Injectable for tests; defaults to the real `selectedModelContract`. */
  selectedModelContractFn?: (decision: ModelSeatDecision) => SelectedModelContract | undefined;
  /** Injectable for tests; defaults to the real repo-root resolver. */
  resolveRepoRoot?: () => string;
  /** Injectable fs seam for the root-bindings store (`services/custody-bindings.ts`). */
  bindingsFs?: CustodyBindingsDeps;
}

// ---------------------------------------------------------------------------
// Production default: re-derive the current seat decision, read-only
// ---------------------------------------------------------------------------

/**
 * Mirrors the seat-resolution half of `process-entry.ts::main()` (never the
 * server-binding half): builds the same `ModelSeatResolutionInput` from the
 * current process env/argv, calls the same `resolveModelSeat`, and -- only
 * when that comes back refused -- attempts the same owned-identity fallback
 * (`loadOwnedModelIdentity` / `loadOwnedDevelopmentIdentity`) so an
 * OWNED_ADMITTED / OWNED_DEVELOPMENT session is classified correctly instead
 * of always reporting "no admitted owned Ember identity". Any failure in the
 * fallback (missing manifest, rejected admission, resolver subprocess error)
 * is swallowed here -- the original refused decision is returned as-is, and
 * `renderCustodyStatus` turns that into an explicit UNRESOLVED line. This
 * function never writes to `process.env`, never spawns/binds a model server,
 * and never calls `process.exit`.
 *
 * Exported (T2.1, B5.5 spine panel) so components/spine-panel.ts's element 2
 * (checkpoint + seat identity) reads the SAME production seat-decision
 * derivation `/custody status` itself uses -- never a second, drifting
 * reimplementation of the owned-identity fallback.
 */
export function _defaultGetModelSeatDecision(): ModelSeatDecision {
  const seatInput: ModelSeatResolutionInput = {
    argv: process.argv,
    explicitModelUrl: process.env["EMBER_MODEL_URL"],
    gpuFreeRequested: Boolean(process.env["EMBER_GPU_FREE"]),
    referenceSeatEnv: process.env["EMBER_REFERENCE_SEAT"],
    referenceModelName: process.env["EMBER_MODEL_NAME"],
  };

  const decision = resolveModelSeat(seatInput);
  if (decision.allowed) return decision;

  try {
    const repoRoot = resolveEmberSourceRootOrCwd({}, "[ember] /custody identity");
    const configHome = getEmberConfigHomeDir();
    const admittedIdentity = loadOwnedModelIdentity({
      repoRoot,
      configHome,
      manifestPath: process.env["EMBER_OWNED_RUNG_MANIFEST"],
      verifierRegistryPath: process.env["EMBER_TRUSTED_VERIFIER_REGISTRY"],
      pythonExecutable: process.env["EMBER_PYTHON"],
    });
    const ownedIdentity =
      admittedIdentity ??
      loadOwnedDevelopmentIdentity({
        repoRoot,
        configHome,
        manifestPath: process.env["EMBER_OWNED_DEVELOPMENT_MANIFEST"],
        pythonExecutable: process.env["EMBER_PYTHON"],
      });
    if (ownedIdentity) {
      return resolveModelSeat({ ...seatInput, ownedIdentity });
    }
  } catch {
    // Fail closed to the original refused decision -- rendered as UNRESOLVED
    // below. A read-only status query is never broken by a missing manifest,
    // an unavailable python executable, or a rejected admission.
  }

  return decision;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * Renders the operator-facing `/custody status` text for a given seat
 * decision. Exported for direct unit testing of the render shape without
 * going through the command's `execute()` plumbing.
 *
 * Never throws: an unresolved/refused decision (`seat === null`) renders an
 * explicit UNRESOLVED line carrying `decision.error`, rather than a crash or
 * a silently blank status.
 */
export function renderCustodyStatus(
  decision: ModelSeatDecision,
  contractFn: (decision: ModelSeatDecision) => SelectedModelContract | undefined = selectedModelContract,
): string {
  if (!decision.allowed || decision.seat === null) {
    return `custody: UNRESOLVED (${decision.error ?? "no seat could be resolved"})`;
  }

  const contract = contractFn(decision);
  const lines = [`custody: ${decision.seat}`, `source: ${decision.source}`];

  if (decision.seat === "OFFLINE") {
    lines.push("model: none (GPU-free observation; no model identity)");
    lines.push("offline reason: EMBER_GPU_FREE requested with no explicit EMBER_MODEL_URL");
    return lines.join("\n");
  }

  if (decision.seat === "REFERENCE_ONLY") {
    const modelName = contract?.modelName ?? referenceSeatModelName(decision.referenceModelName);
    lines.push(`model: ${modelName}`);
    lines.push("structuredOutputs: false (borrowed model; never owned capability)");
    return lines.join("\n");
  }

  // OWNED_ADMITTED | OWNED_DEVELOPMENT
  const identity = decision.ownedIdentity;
  lines.push(`model: ${contract?.modelName ?? identity?.modelName ?? "UNVERIFIED"}`);
  lines.push(`checkpoint: ${identity?.checkpointSha256 ?? "UNVERIFIED"}`);
  lines.push(
    `checkpointDir: ${identity?.launch?.checkpointDir ?? "unavailable (no launch descriptor)"}`,
  );
  lines.push(`structuredOutputs: ${contract?.structuredOutputs === true}`);
  if (decision.seat === "OWNED_DEVELOPMENT") {
    lines.push(`claimStatus: ${identity?.claimStatus ?? "unknown"}`);
    lines.push(`tokensSeen: ${identity?.tokensSeen ?? "unknown"}`);
  }
  return lines.join("\n");
}

/**
 * Renders any persisted machine-local root bindings for `/custody status`.
 * Read-only, fail-open: when the store is absent/empty this returns `""` so
 * callers can splice it in without changing today's status shape when no
 * binding has ever been set (`readRootBindingsStore` already fails open on a
 * missing/malformed file; this only decides how to *render* an empty result).
 */
export function renderRootBindings(store: RootBindingsStore): string {
  const entries = Object.values(store.roots);
  if (entries.length === 0) return "";
  const lines = ["", "bindings:"];
  for (const b of entries.sort((a, c) => a.root_id.localeCompare(c.root_id))) {
    lines.push(`  ${b.root_id} -> ${b.machine_path} (${b.binding_env})`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/** Creates the read-only `/custody status` (alias `/seat`) command. */
export function createCustodyCommand(deps: CustodyCommandDeps = {}): RegistryCommand {
  const doGetModelSeatDecision = deps.getModelSeatDecision ?? _defaultGetModelSeatDecision;
  const doSelectedModelContract = deps.selectedModelContractFn ?? selectedModelContract;
  const doResolveRepoRoot =
    deps.resolveRepoRoot ?? (() => resolveEmberRepoRootOrCwd({}, "[ember] /custody"));
  const bindingsFs = deps.bindingsFs ?? {};

  return {
    name: "custody",
    description:
      "Show the current model seat classification (read-only): custody status -- also reports the bound owned model's identity (sha256, on-disk directory) when an owned seat is active; persist a machine-local root path: custody set <root_id>=<path>",
    aliases: ["seat"],
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      const trimmed = args.trim();
      const firstSpace = trimmed.search(/\s/);
      const subcommand = firstSpace === -1 ? trimmed : trimmed.slice(0, firstSpace);
      const rest = firstSpace === -1 ? "" : trimmed.slice(firstSpace + 1).trim();

      if (subcommand === "set") {
        if (!rest) {
          return {
            type: "message" as const,
            message: "usage: /custody set <root_id>=<path> (or --binding <root_id>=<path>)",
            exitCode: 1,
          };
        }
        // Accept both `set root_id=path` and `set --binding root_id=path`.
        const bindingArg = rest.startsWith("--binding")
          ? rest.slice("--binding".length).trim()
          : rest;

        let parsed: { rootId: string; machinePath: string };
        try {
          parsed = parseBindingArg(bindingArg);
        } catch (err) {
          if (err instanceof MalformedBindingArgError) {
            return {
              type: "message" as const,
              message: `custody set: ${err.message}`,
              exitCode: 1,
            };
          }
          throw err;
        }

        let repoRoot: string;
        try {
          repoRoot = doResolveRepoRoot();
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          return {
            type: "message" as const,
            message: `custody set: could not resolve the ember repo root (${msg})`,
            exitCode: 1,
          };
        }

        const binding = writeRootBinding(repoRoot, parsed.rootId, parsed.machinePath, bindingsFs);
        return {
          type: "message" as const,
          message: `custody set: wrote ${binding.root_id} -> ${binding.machine_path} (${binding.binding_env}) to ${rootBindingsStorePath(repoRoot)}`,
        };
      }

      if (subcommand !== "status" && subcommand !== "") {
        return {
          type: "message" as const,
          message: "usage: /custody status (alias: /seat) | /custody set <root_id>=<path>",
        };
      }

      let decision: ModelSeatDecision;
      try {
        decision = doGetModelSeatDecision();
      } catch (err) {
        // Fail gracefully: seat resolution throwing (subprocess crash, I/O
        // error, malformed manifest) never crashes the command itself.
        const msg = err instanceof Error ? err.message : String(err);
        return {
          type: "message" as const,
          message: `custody: UNRESOLVED (seat resolution failed: ${msg})`,
        };
      }

      let bindingsSuffix = "";
      try {
        const repoRoot = doResolveRepoRoot();
        bindingsSuffix = renderRootBindings(readRootBindingsStore(repoRoot, bindingsFs));
      } catch {
        // Fail open to today's behavior (no bindings section) -- a status
        // query is never broken by a repo-root resolution failure.
        bindingsSuffix = "";
      }

      return {
        type: "message" as const,
        message: renderCustodyStatus(decision, doSelectedModelContract) + bindingsSuffix,
      };
    },
  };
}
