// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// utils/harness-warn.ts -- governance-path warnings in the OPEN_WEIGHTS harness mode.
//
// In OPEN_WEIGHTS mode ember-cli runs in any project directory, where Ember
// repo-root resolution is expected to fail. Printing that to stderr on every
// receipt write scribbles over the Ink screen, so in that mode each distinct
// warning is written once to EMBER_HOME/ember-warnings.log instead. Every
// other seat keeps the loud console warning unchanged.

import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { getEmberConfigHomeDir } from "./env-detection.ts";

const seen = new Set<string>();

export function harnessWarn(message: string, level: "warn" | "error" = "warn"): void {
  if (process.env["EMBER_OPEN_WEIGHTS_ACTIVE"] !== "1") {
    if (level === "error") console.error(message);
    else console.warn(message);
    return;
  }
  if (seen.has(message)) return;
  seen.add(message);
  try {
    const dir = getEmberConfigHomeDir();
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, "ember-warnings.log"), `${new Date().toISOString()} ${message}\n`);
  } catch {
    // a warning that cannot be logged is dropped, never thrown
  }
}
