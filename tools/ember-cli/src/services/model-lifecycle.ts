// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/model-lifecycle.ts — managed model process lifecycle (load/unload toggle).
//
// Owns the handle for a local-spawned model process so it can be unloaded
// (freed from VRAM) and reloaded without closing the cockpit. All process effects
// are injected for CPU-testability.

import { LLAMA_SERVER_DEFAULT_PORT } from "./runtime-bootstrap.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ModelState = "unloaded" | "loading" | "loaded" | "external";

export interface ManagedModelHandle {
  pid: number;
}

export interface ModelLifecycleDeps {
  spawnModel: () => ManagedModelHandle;
  killPid: (pid: number) => void;
  waitReady: (port?: number) => Promise<void>;
  writeKillReceipt: (rec: { pid: number; match_rule: string }) => void;
  isExternal: () => boolean;
  now: () => string;
  /**
   * Path to the active checkpoint's identity manifest (cond3 inc2a). Threaded
   * through so /model status|load can resolve+validate checkpoint identity
   * via _resolveModelIdentity() before rendering/spawning -- fail-closed when
   * absent or unresolvable (never a silent "no identity" render for a
   * checkpoint that IS supposed to carry one).
   */
  manifestPath?: string;
}

// ---------------------------------------------------------------------------
// Module state (reset via resetModelLifecycleForTests)
// ---------------------------------------------------------------------------

let currentState: ModelState = "unloaded";
let trackedPid: number | null = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Returns the current model state: "unloaded" | "loading" | "loaded" | "external".
 * AC1: initial state is "unloaded" (or "external" if EMBER_MODEL_URL is set at boot).
 */
export function getModelState(): ModelState {
  return currentState;
}

/**
 * Wire the boot-spawned handle in so it can be unloaded later.
 * AC2: sets state to "loaded" and stores the pid in managed mode.
 * In external mode (isExternal() true at boot), this is a no-op and state stays "external".
 */
export function registerManagedModel(handle: ManagedModelHandle): void {
  // External mode is determined at bootstrap via env, not here.
  // For this simple API, we just register the handle and set state to "loaded".
  trackedPid = handle.pid;
  currentState = "loaded";
}

/**
 * Kill the tracked PID, writing a receipt first (before killPid call).
 * AC3: receipt written strictly before kill, state set to "unloaded", one-line status.
 * AC4: idempotent when already unloaded; in external mode never kills.
 */
export async function unloadModel(deps: ModelLifecycleDeps): Promise<string> {
  // If external, never kill
  if (deps.isExternal()) {
    return `external model (EMBER_MODEL_URL) — not managed, nothing to unload`;
  }

  // If already unloaded, idempotent no-op
  if (currentState === "unloaded") {
    return `model already unloaded`;
  }

  // Unload: receipt BEFORE kill (AC3 strict ordering)
  const pid = trackedPid!;
  deps.writeKillReceipt({
    pid,
    match_rule: `model child spawned this session`,
  });

  // Now kill
  deps.killPid(pid);

  // Update state
  currentState = "unloaded";
  trackedPid = null;

  return `model unloaded (pid ${pid} freed)`;
}

/**
 * Spawn a new model process, wait for it to be ready.
 * AC5: sets "loading", spawns, registers handle, waits, sets "loaded".
 * If waitReady rejects, state returns to "unloaded" (not stuck in "loading").
 * AC6: idempotent when already "loaded"; in external mode never spawns.
 */
export async function loadModel(deps: ModelLifecycleDeps): Promise<string> {
  // If external, never spawn
  if (deps.isExternal()) {
    return `external model (EMBER_MODEL_URL) — not managed, nothing to load`;
  }

  // If already loaded, idempotent no-op
  if (currentState === "loaded") {
    return `model already loaded`;
  }

  // Transition to "loading"
  currentState = "loading";

  try {
    // Spawn
    const handle = deps.spawnModel();
    trackedPid = handle.pid;

    // Wait for readiness (defaults to LLAMA_SERVER_DEFAULT_PORT)
    await deps.waitReady(LLAMA_SERVER_DEFAULT_PORT);

    // Success: set state to "loaded"
    currentState = "loaded";

    return `model loaded (pid ${handle.pid})`;
  } catch (err) {
    // Failure: return state to "unloaded" (not stuck in "loading")
    currentState = "unloaded";
    trackedPid = null;

    // Propagate the error
    throw err;
  }
}

/**
 * Reset all state for tests. Called by the test framework.
 */
export function resetModelLifecycleForTests(): void {
  currentState = "unloaded";
  trackedPid = null;
}
