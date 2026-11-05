// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { buildOpenWeightsSystemPrompt } from "./open-weights-system-prompt.ts";

describe("buildOpenWeightsSystemPrompt", () => {
  it("states the working directory, shell and date", () => {
    const p = buildOpenWeightsSystemPrompt({ cwd: "A:\work", platform: "win32", date: new Date("2026-11-03T08:00:00Z") });
    expect(p).toContain("Working directory: A:\work.");
    expect(p).toContain("cmd.exe");
    expect(p).toContain("2026-11-03");
    expect(p.length).toBeLessThan(800);
  });
});
