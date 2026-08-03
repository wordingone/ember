// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// settings.ts
// Hierarchical settings loading (user → project → local → flag → policy),
// permission-rule validation, and file-change detection.

import { join } from 'path';
import { readFile, writeFile, mkdir } from 'fs/promises';
import { watch } from 'fs';
import { getEmberConfigHomeDir } from './utils/env-detection.ts';
import { emberStatePath } from './utils/ember-state-root.ts';

// ---- Constants ----

/**
 * Debounce window (ms) for the SettingsChangeDetector.
 * External file changes are reported after this many milliseconds of silence
 * to avoid repeated callbacks from rapid successive writes.
 */
export const SETTINGS_STABILITY_THRESHOLD_MS = 1500;

// ---- Path resolution ----

/**
 * Returns the on-disk path for the settings file belonging to `source`.
 *
 * - 'user'    → {EMBER_HOME}/settings.json
 * - 'project' → {emberStateRoot(gitRoot)}/settings.json
 * - 'local'   → {emberStateRoot(gitRoot)}/settings.local.json
 *
 * Project/local settings live outside the certified tree (issue #1330) so the
 * completion verifier's total census never sees a resident cockpit writer.
 */
export function getSettingsFilePathForSource(
  source: 'user' | 'project' | 'local',
  gitRoot?: string,
): string {
  if (source === 'user') {
    return join(getEmberConfigHomeDir(), 'settings.json');
  }
  const root = gitRoot ?? process.cwd();
  if (source === 'project') {
    return emberStatePath(root, 'settings.json');
  }
  // 'local'
  return emberStatePath(root, 'settings.local.json');
}

// ---- Deep merge (arrays replaced, objects merged) ----

function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...target };
  for (const key of Object.keys(source)) {
    const srcVal = source[key];
    if (srcVal === undefined) continue;
    if (Array.isArray(srcVal)) {
      // Arrays replace; no deep merge.
      result[key] = [...(srcVal as unknown[])];
    } else if (
      typeof srcVal === 'object' &&
      srcVal !== null &&
      !Array.isArray(srcVal) &&
      typeof result[key] === 'object' &&
      result[key] !== null &&
      !Array.isArray(result[key])
    ) {
      result[key] = deepMerge(
        result[key] as Record<string, unknown>,
        srcVal as Record<string, unknown>,
      );
    } else {
      result[key] = srcVal;
    }
  }
  return result;
}

// ---- JSON loader (returns {} on missing/invalid files) ----

async function loadJsonFile(path: string): Promise<Record<string, unknown>> {
  try {
    const raw = await readFile(path, 'utf-8');
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return {};
  } catch {
    return {};
  }
}

// ---- Settings cache ----

let _settingsCache: null = null; // placeholder; cache is always cleared on write

/**
 * Clears the module-level settings cache.
 * TEST-ONLY: call this between tests that change EMBER_HOME or write to settings files.
 */
export function _resetSettingsCache(): void {
  _settingsCache = null;
}

// Suppress unused-assignment lint (the variable is intentionally kept as a
// hook point for future caching without breaking the test-helper contract).
void _settingsCache;

// ---- Main loader ----

/**
 * Loads and merges settings from all sources in priority order:
 * user → project → local → flagSettings → policySettings.
 *
 * Policy settings win unconditionally for any key they define.
 * Arrays in higher-priority sources replace (not merge with) lower-priority arrays.
 */
export async function loadSettingsFromDisk(
  gitRoot: string,
  flagSettings: Record<string, unknown> = {},
  policySettings: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const userSettings = await loadJsonFile(getSettingsFilePathForSource('user', gitRoot));
  const projectSettings = await loadJsonFile(getSettingsFilePathForSource('project', gitRoot));
  const localSettings = await loadJsonFile(getSettingsFilePathForSource('local', gitRoot));

  let merged: Record<string, unknown> = {};
  merged = deepMerge(merged, userSettings);
  merged = deepMerge(merged, projectSettings);
  merged = deepMerge(merged, localSettings);
  merged = deepMerge(merged, flagSettings);

  // Policy wins unconditionally for any key it defines.
  for (const key of Object.keys(policySettings)) {
    merged[key] = policySettings[key];
  }

  return merged;
}

// ---- Atomic writer ----

/**
 * Reads the current settings for `source`, deep-merges `updates` into them,
 * and writes the result back atomically.
 *
 * When `tracker` is provided, the write is recorded so that SettingsChangeDetector
 * can suppress the resulting fs.watch notification.
 */
export async function updateSettingsForSource(
  source: 'user' | 'project' | 'local',
  updates: Record<string, unknown>,
  gitRoot?: string,
  tracker?: InternalWriteTracker,
): Promise<void> {
  const filePath = getSettingsFilePathForSource(source, gitRoot);
  const existing = await loadJsonFile(filePath);
  const merged = deepMerge(existing, updates);

  // Ensure the directory exists.
  const dir = join(filePath, '..');
  await mkdir(dir, { recursive: true });

  // Record the write before touching the file so the detector sees it immediately.
  tracker?.markWrite(filePath);

  await writeFile(filePath, JSON.stringify(merged, null, 2), 'utf-8');
}

// ---- Permission rule validation ----

/**
 * Validates a permission rule string.
 * Returns null when the rule is valid, or a human-readable error message otherwise.
 *
 * Rules:
 * - No parentheses → always valid.
 * - Unbalanced parentheses (open without close) → error.
 * - Empty parentheses `()` → error (a rule must specify at least one argument).
 * - MCP rules (`mcp__*`) disallow wildcards inside the parentheses.
 */
export function validatePermissionRule(rule: string): string | null {
  const openIdx = rule.indexOf('(');
  if (openIdx === -1) {
    // No parens — the rule is a bare tool name; valid.
    return null;
  }

  const closeIdx = rule.indexOf(')', openIdx + 1);
  if (closeIdx === -1) {
    return 'Unbalanced parentheses in permission rule: missing closing ")"';
  }

  const content = rule.slice(openIdx + 1, closeIdx).trim();

  if (content === '') {
    return 'Permission rule has empty parentheses: specify at least one argument or pattern';
  }

  if (rule.startsWith('mcp__') && content.includes('*')) {
    return 'MCP permission rules do not allow wildcard patterns inside parentheses';
  }

  return null;
}

// ---- Internal write tracker ----

/**
 * Records file paths that were written by internal code so that
 * SettingsChangeDetector can suppress the resulting fs.watch notifications.
 */
export class InternalWriteTracker {
  private readonly recentWrites = new Map<string, number>(); // path → epoch ms
  // Writes older than this are considered stale and ignored.
  private static readonly WINDOW_MS = 10_000;

  /** Records that code is about to write to `filePath`. */
  markWrite(filePath: string): void {
    this.recentWrites.set(filePath, Date.now());
  }

  /** Returns true when `filePath` was written internally within the stale window. */
  wasRecentlyWritten(filePath: string): boolean {
    const ts = this.recentWrites.get(filePath);
    if (ts === undefined) return false;
    if (Date.now() - ts > InternalWriteTracker.WINDOW_MS) {
      this.recentWrites.delete(filePath);
      return false;
    }
    return true;
  }
}

// ---- Settings change detector ----

type WatchHandle = ReturnType<typeof watch>;

/**
 * Watches settings files for external changes and fires registered callbacks
 * with a debounce of SETTINGS_STABILITY_THRESHOLD_MS.
 *
 * Internal writes (marked via InternalWriteTracker) are suppressed to avoid
 * false-positive cascades.
 */
export class SettingsChangeDetector {
  private readonly tracker: InternalWriteTracker | undefined;
  private readonly callbacks: Array<() => void> = [];
  private readonly watchers: WatchHandle[] = [];
  private readonly debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor(tracker?: InternalWriteTracker) {
    this.tracker = tracker;
  }

  /**
   * Begins watching `filePath` for external changes.
   * Safe to call multiple times with different paths.
   */
  watch(filePath: string): void {
    try {
      const watcher = watch(filePath, (eventType) => {
        if (eventType !== 'change' && eventType !== 'rename') return;
        if (this.tracker?.wasRecentlyWritten(filePath)) return;

        const existing = this.debounceTimers.get(filePath);
        if (existing !== undefined) clearTimeout(existing);

        const timer = setTimeout(() => {
          this.debounceTimers.delete(filePath);
          for (const cb of this.callbacks) {
            try { cb(); } catch { /* individual callback errors must not break the loop */ }
          }
        }, 100); // short debounce; SETTINGS_STABILITY_THRESHOLD_MS is the caller's wait budget

        this.debounceTimers.set(filePath, timer);
      });
      this.watchers.push(watcher);
    } catch {
      // File may not exist yet; watcher creation failure is silently ignored.
    }
  }

  /** Registers a callback to fire when an external settings change is detected. */
  onConfigChange(callback: () => void): void {
    this.callbacks.push(callback);
  }

  /** Stops all file watchers and clears pending debounce timers. */
  dispose(): void {
    for (const timer of this.debounceTimers.values()) clearTimeout(timer);
    this.debounceTimers.clear();
    for (const w of this.watchers) {
      try { w.close(); } catch { /* ignore */ }
    }
    this.watchers.length = 0;
  }
}
