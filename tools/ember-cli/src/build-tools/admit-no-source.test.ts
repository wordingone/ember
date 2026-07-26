// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { inspectOwnedAdmissionProducerSurface } from "./lifecycle-smoke.ts";

describe("no-source owned-admission producer map", () => {
  it("maps /admit as candidate production without designation, loading, or training", () => {
    expect(inspectOwnedAdmissionProducerSurface([
      { name: "admit" },
    ])).toEqual({
      action: "admit",
      authority_boundary:
        "candidate-production-only; selected=false loaded=false training_started=false",
      command: "admit",
      input:
        "/admit --workspace <path> --descriptor <path> --output-root <path>",
      status: "AVAILABLE",
    });
  });

  it("does not infer production from an absent command", () => {
    expect(inspectOwnedAdmissionProducerSurface([]).status).toBe("MISSING");
  });
});
