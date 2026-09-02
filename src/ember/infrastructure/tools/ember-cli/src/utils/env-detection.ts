// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Environment detection utilities for Ember home directory and runtime configuration.
// L1 leaf: no intra-ember dependencies.

import { homedir } from "os";
import { join } from "path";

// ---------------------------------------------------------------------------
// Memoized config home directory detection
// ---------------------------------------------------------------------------

let cachedConfigHome: string | null = null;

/**
 * Returns the Ember config home directory.
 * Resolved via EMBER_HOME env var, or defaults to ~/.ember
 * Results are memoized for performance.
 */
export function getEmberConfigHomeDir(): string {
  if (cachedConfigHome !== null) {
    return cachedConfigHome;
  }

  const emberHome = process.env["EMBER_HOME"];
  if (emberHome) {
    cachedConfigHome = emberHome;
  } else {
    cachedConfigHome = join(homedir(), ".ember");
  }

  return cachedConfigHome;
}

/**
 * Resets the memoized config home directory.
 * For testing only — allows tests to change EMBER_HOME and have it take effect.
 */
export function _resetConfigHomeMemo(): void {
  cachedConfigHome = null;
}
