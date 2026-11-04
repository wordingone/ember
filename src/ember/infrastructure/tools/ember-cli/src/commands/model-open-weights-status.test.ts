// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { describeOpenWeightsSeat } from "./model.ts";

describe("/model status on an open-weights seat", () => {
  const seat = { phase: "RESIDENT", owner: "OPEN_WEIGHTS: q:Q4", endpoint: "http://localhost:1", vramBytes: 0, vramUnmeasured: true };
  it("reports resident when the server answers /health", async () => {
    expect(await describeOpenWeightsSeat(seat, async () => true)).toContain("model: resident");
  });
  it("says NOT RESPONDING when the health check fails", async () => {
    expect(await describeOpenWeightsSeat(seat, async () => false)).toContain("NOT RESPONDING");
  });
  it("reports an absent seat plainly", async () => {
    expect(await describeOpenWeightsSeat({ phase: "ABSENT" })).toContain("no server attached");
  });
});
