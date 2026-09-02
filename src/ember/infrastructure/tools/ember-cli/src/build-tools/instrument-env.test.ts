// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// build-tools/instrument-env.test.ts — the completeness half of the headless-capture guard.
//
// The guard itself is tested where the writers live. What could not be tested there is the thing
// that actually failed: the product-side predicate landed correct and NO instrument set it, so
// every real capture run still published the cockpit's liveness and watermark. Unit tests on the
// writers pass either way, because they inject the env themselves.
//
// So this test does not sample launchers. It ENUMERATES every `spawnPty` call site under
// build-tools from the source bytes and requires each one to carry the shared env fragment. A
// launcher added later fails here rather than silently running as the operator's cockpit.

import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  HEADLESS_CAPTURE_ENV,
  headlessCaptureEnv,
  isHeadlessCapture,
} from "../services/headless-capture.ts";

const BUILD_TOOLS_DIR = dirname(fileURLToPath(import.meta.url));
const CALL = "spawnPty(";

/** Source slice of one call expression, from `spawnPty(` to its matching close paren. */
function callExpressions(source: string): string[] {
  const found: string[] = [];
  let from = 0;
  for (;;) {
    const start = source.indexOf(CALL, from);
    if (start === -1) return found;
    let depth = 0;
    let index = start + CALL.length - 1;
    for (; index < source.length; index++) {
      const ch = source[index];
      if (ch === "(") depth++;
      else if (ch === ")") {
        depth--;
        if (depth === 0) break;
      }
    }
    found.push(source.slice(start, index + 1));
    from = index + 1;
  }
}

function launcherSources(): Array<{ file: string; source: string }> {
  return readdirSync(BUILD_TOOLS_DIR)
    .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
    .map((file) => ({ file, source: readFileSync(join(BUILD_TOOLS_DIR, file), "utf8") }))
    .filter(({ source }) => callExpressions(source).length > 0);
}

describe("the shared instrument env fragment", () => {
  test("is exactly the predicate's own signal, and the predicate accepts it", () => {
    expect(headlessCaptureEnv()).toEqual({ [HEADLESS_CAPTURE_ENV]: "1" });
    // The round trip is the point: the fragment is defined in terms of the same constant the
    // guard reads, so a rename cannot leave launchers setting a key nothing consumes.
    expect(isHeadlessCapture({ ...headlessCaptureEnv() })).toBe(true);
  });

  test("forces the value rather than inheriting a stale one", () => {
    const inherited = { [HEADLESS_CAPTURE_ENV]: "0", PATH: "/x" };
    expect(isHeadlessCapture({ ...inherited, ...headlessCaptureEnv() })).toBe(true);
  });
});

describe("every build-tools launcher that spawns the compiled binary", () => {
  const launchers = launcherSources();

  test("is a non-empty set (the enumeration itself must not silently find nothing)", () => {
    // Without this, a broken discovery predicate would make every assertion below vacuous —
    // an enumeration that enumerates zero rows passes for the wrong reason.
    expect(launchers.length).toBeGreaterThanOrEqual(3);
  });

  test("imports the shared fragment", () => {
    const missing = launchers
      .filter(({ source }) => !source.includes("headlessCaptureEnv"))
      .map(({ file }) => file);
    expect(missing).toEqual([]);
  });

  test("spreads it into the env of EVERY spawn call, not just the first", () => {
    const offenders: string[] = [];
    for (const { file, source } of launchers) {
      callExpressions(source).forEach((expression, index) => {
        if (!expression.includes("headlessCaptureEnv()")) offenders.push(`${file}#${index}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
