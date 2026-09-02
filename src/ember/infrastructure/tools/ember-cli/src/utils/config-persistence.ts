// utils/config-persistence.ts
// Provides a module-level config-directory cache and the test-helper reset function.
// The cost-tracking functions live in utils/cost-telemetry.ts and import from here.

import { getEmberConfigHomeDir } from './env-detection.ts';
import { join } from 'path';

// ---- Module-level cache ----

let _cachedCostsDir: string | null = null;

/**
 * Returns (and caches) the directory used to persist per-session cost records.
 * Located at {EMBER_HOME}/.costs/
 */
export function getCostStorageDir(): string {
  if (_cachedCostsDir !== null) return _cachedCostsDir;
  _cachedCostsDir = join(getEmberConfigHomeDir(), '.costs');
  return _cachedCostsDir;
}

/**
 * Clears the cached config/cost-directory path.
 * TEST-ONLY: call this whenever EMBER_HOME changes between tests.
 */
export function _resetGlobalConfigCache(): void {
  _cachedCostsDir = null;
}
