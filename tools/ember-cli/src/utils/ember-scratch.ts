// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// NO-TEMP policy (per operator direction): none of ember's stack, current, past, or future,
// may live in system temp. This helper is the ONE canonical ember-owned scratch root for
// TypeScript call sites. It replaces every `os.tmpdir()` / `mkdtempSync(join(tmpdir(), ...))`
// use in ember-cli. See: tools/no_temp_allowlist and src/ember/infrastructure/tools/check_no_temp.py for the
// enforcement gate covering the rest of the stack.

import { mkdirSync, realpathSync } from "fs";
import { homedir } from "os";
import { join } from "path";

/**
 * Returns the ember-owned scratch directory for `purpose`, creating it if
 * necessary. Never touches system temp (`os.tmpdir()` / `%TEMP%` / `/tmp`).
 *
 * Path shape: `<EMBER_HOME>/.runtime/<purpose>/<pid>`
 * - `EMBER_HOME` = `process.env.EMBER_HOME` if set, else `~/.ember`.
 * - The directory is created recursively before returning.
 * - The returned path is canonicalized via `realpathSync.native()` so
 *   downstream path comparisons (e.g. `!==` against another resolved path)
 *   are case-correct on case-insensitive filesystems (Windows/macOS).
 */
export function emberScratchDir(purpose: string): string {
  const emberHome = process.env.EMBER_HOME || join(homedir(), ".ember");
  const scratchPath = join(emberHome, ".runtime", purpose, String(process.pid));
  mkdirSync(scratchPath, { recursive: true });
  return realpathSync.native(scratchPath);
}
