// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { freshInteractiveReplConfig } from "./process-entry.ts";

describe("#1215 process-entry sandbox default", () => {
  test("the production interactive REPL is constructed in sandbox mode", () => {
    expect(freshInteractiveReplConfig("ember")).toEqual({
      model: "ember",
      permissionMode: "regular",
      baseSystemPrompt: "",
    });
  });
});
