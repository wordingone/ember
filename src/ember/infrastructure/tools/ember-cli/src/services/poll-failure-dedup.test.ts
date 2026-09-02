// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { createPollFailureDeduper } from "./poll-failure-dedup.ts";

describe("createPollFailureDeduper", () => {
  it("publishes the first occurrence of a class immediately", () => {
    const published: string[] = [];
    const deduper = createPollFailureDeduper({
      intervalMs: 1000,
      now: () => 0,
      publish: (text) => published.push(text),
    });
    deduper.report("memory-footprint:ownership", "identity unavailable");
    expect(published).toEqual(["identity unavailable"]);
  });

  it("suppresses repeats of the same class within the window, never publishing per-tick", () => {
    const published: string[] = [];
    let clock = 0;
    const deduper = createPollFailureDeduper({
      intervalMs: 1000,
      now: () => clock,
      publish: (text) => published.push(text),
    });
    deduper.report("memory-footprint:ownership", "identity unavailable");
    for (let i = 0; i < 49; i += 1) {
      clock += 20;
      deduper.report("memory-footprint:ownership", "identity unavailable");
    }
    expect(clock).toBeLessThan(1000);
    expect(published).toEqual(["identity unavailable"]);
  });

  it("publishes again once the window elapses, carrying the suppressed count forward", () => {
    const published: string[] = [];
    let clock = 0;
    const deduper = createPollFailureDeduper({
      intervalMs: 1000,
      now: () => clock,
      publish: (text) => published.push(text),
    });
    deduper.report("serving-topology:poll", "poll failed: X");
    for (let i = 0; i < 9; i += 1) {
      clock += 100;
      deduper.report("serving-topology:poll", "poll failed: X");
    }
    clock = 1000;
    deduper.report("serving-topology:poll", "poll failed: X");
    expect(published).toEqual([
      "poll failed: X",
      "poll failed: X (+9 more suppressed in the last 1000ms)",
    ]);
  });

  it("keeps independent windows per classKey", () => {
    const published: string[] = [];
    const deduper = createPollFailureDeduper({
      intervalMs: 1000,
      now: () => 0,
      publish: (text) => published.push(text),
    });
    deduper.report("memory-footprint:ownership", "A");
    deduper.report("serving-topology:poll", "B");
    deduper.report("memory-footprint:ownership", "A again");
    expect(published).toEqual(["A", "B"]);
  });
});
