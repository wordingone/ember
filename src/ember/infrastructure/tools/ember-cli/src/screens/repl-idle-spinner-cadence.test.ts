// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ANIMATION_LOOP_MS } from "../components/spinner.ts";
import { spinnerCadenceForBusy } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";

describe("issue #898 idle spinner cadence", () => {
  test("does not schedule the spinner clock while idle", () => {
    expect(spinnerCadenceForBusy(false)).toBeNull();
  });

  test("retains the production animation cadence while busy", () => {
    expect(spinnerCadenceForBusy(true)).toBe(ANIMATION_LOOP_MS);
  });

  test("the real REPL interval is bound to the busy-aware cadence", () => {
    const source = readFileSync(join(import.meta.dir, "repl.ts"), "utf8");
    expect(source).toContain("}, spinnerCadenceForBusy(busy));");
  });
});
