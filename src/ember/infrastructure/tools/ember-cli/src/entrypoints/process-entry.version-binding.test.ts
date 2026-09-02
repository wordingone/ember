// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, test } from "bun:test";
import {
  EMBER_CLI_VERSION,
  buildCliVersionRecord,
  formatCliVersionOutput,
} from "../../../../../../../tools/ember-cli/src/entrypoints/process-entry.ts";

type BuildGlobal = typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown };

const prior = (globalThis as BuildGlobal).__EMBER_BUILD_COMMIT__;

afterEach(() => {
  if (prior === undefined) delete (globalThis as BuildGlobal).__EMBER_BUILD_COMMIT__;
  else (globalThis as BuildGlobal).__EMBER_BUILD_COMMIT__ = prior;
});

describe("#159 compiled source-version binding", () => {
  test("shows the exact embedded source commit in text and JSON output", () => {
    const commit = "a".repeat(40);
    (globalThis as BuildGlobal).__EMBER_BUILD_COMMIT__ = commit;

    expect(buildCliVersionRecord()).toEqual({
      version: EMBER_CLI_VERSION,
      source_commit: commit,
      source_binding: "BOUND",
    });
    expect(formatCliVersionOutput(false)).toBe(
      `ember-cli ${EMBER_CLI_VERSION} source ${commit}\n`,
    );
    expect(JSON.parse(formatCliVersionOutput(true))).toEqual({
      version: EMBER_CLI_VERSION,
      source_commit: commit,
      source_binding: "BOUND",
    });
  });

  test("reports SOURCE_UNBOUND rather than inventing a commit in source mode", () => {
    delete (globalThis as BuildGlobal).__EMBER_BUILD_COMMIT__;

    expect(buildCliVersionRecord()).toEqual({
      version: EMBER_CLI_VERSION,
      source_commit: null,
      source_binding: "UNBOUND",
    });
    expect(formatCliVersionOutput(false)).toContain("source SOURCE_UNBOUND");
  });

  test("rejects malformed embedded commit values instead of displaying them", () => {
    (globalThis as BuildGlobal).__EMBER_BUILD_COMMIT__ = "master";
    expect(() => buildCliVersionRecord()).toThrow(
      "embedded Ember source commit is malformed",
    );
  });
});
