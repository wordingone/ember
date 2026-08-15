// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import {
  createPollFailureStatusTracker,
  formatFailureMessageChangedLine,
  formatFailureRecoveredLine,
  formatFailureStartedLine,
  type PollFailureStatusEntry,
} from "./poll-failure-status.ts";

describe("createPollFailureStatusTracker", () => {
  it("publishes exactly one 'started' transition on first occurrence", () => {
    const published: string[] = [];
    const tracker = createPollFailureStatusTracker({
      now: () => 0,
      recoveryAfterMs: 1000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("memory-footprint:ownership", "identity unavailable");
    expect(published).toEqual(["identity unavailable"]);
  });

  it("#1701 core repro: many repeated same-message reports across long silence-free spans publish zero additional transitions", () => {
    const published: string[] = [];
    let clock = 0;
    const tracker = createPollFailureStatusTracker({
      now: () => clock,
      recoveryAfterMs: 20_000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("memory-footprint:ownership", "identity unavailable");
    // 60 ticks at 1s cadence -- spans what would have been 4 old 15s dedup windows -- all the
    // same message.
    for (let i = 0; i < 60; i += 1) {
      clock += 1000;
      tracker.report("memory-footprint:ownership", "identity unavailable");
    }
    expect(published).toEqual(["identity unavailable"]);
    const [entry] = tracker.getActiveStatuses();
    expect(entry?.count).toBe(61);
    expect(entry?.since).toBe(0);
    expect(entry?.lastSeenAt).toBe(60_000);
  });

  it("publishes a 'message changed' transition exactly once when the message differs, then stays quiet on repeats of the new message", () => {
    const published: string[] = [];
    let clock = 0;
    const tracker = createPollFailureStatusTracker({
      now: () => clock,
      recoveryAfterMs: 20_000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("serving-topology:poll", "poll failed: ECONNREFUSED");
    clock += 1000;
    tracker.report("serving-topology:poll", "poll failed: ECONNREFUSED");
    clock += 1000;
    tracker.report("serving-topology:poll", "poll failed: ETIMEDOUT");
    clock += 1000;
    tracker.report("serving-topology:poll", "poll failed: ETIMEDOUT");
    expect(published).toEqual([
      "poll failed: ECONNREFUSED",
      formatFailureMessageChangedLine("serving-topology:poll", "poll failed: ETIMEDOUT"),
    ]);
  });

  it("sweep() publishes exactly one 'recovered' transition once a class has been silent for recoveryAfterMs and clears it from active status", () => {
    const published: string[] = [];
    let clock = 0;
    const tracker = createPollFailureStatusTracker({
      now: () => clock,
      recoveryAfterMs: 5000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("memory-footprint:ownership", "identity unavailable");
    clock = 1000;
    tracker.report("memory-footprint:ownership", "identity unavailable");
    clock = 6500; // 5500ms silent since lastSeenAt=1000 -- past the 5000ms threshold
    tracker.sweep();
    expect(published).toEqual([
      "identity unavailable",
      formatFailureRecoveredLine(
        { classKey: "memory-footprint:ownership", message: "identity unavailable", count: 2, since: 0, lastSeenAt: 1000 },
        6500,
      ),
    ]);
    expect(tracker.getActiveStatuses()).toEqual([]);
  });

  it("sweep() does nothing while a class is still within its silence threshold", () => {
    const published: string[] = [];
    let clock = 0;
    const tracker = createPollFailureStatusTracker({
      now: () => clock,
      recoveryAfterMs: 5000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("memory-footprint:ownership", "identity unavailable");
    clock = 3000;
    tracker.sweep();
    expect(published).toEqual(["identity unavailable"]);
    expect(tracker.getActiveStatuses().length).toBe(1);
  });

  it("a class that recovers and then reports again starts a fresh streak (new 'started' transition, count reset)", () => {
    const published: string[] = [];
    let clock = 0;
    const tracker = createPollFailureStatusTracker({
      now: () => clock,
      recoveryAfterMs: 5000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("memory-footprint:ownership", "identity unavailable");
    clock = 6000;
    tracker.sweep(); // recovers
    clock = 7000;
    tracker.report("memory-footprint:ownership", "identity unavailable"); // fresh streak
    expect(published.length).toBe(3); // started, recovered, started again
    expect(published[2]).toBe("identity unavailable");
    const [entry] = tracker.getActiveStatuses();
    expect(entry?.count).toBe(1);
    expect(entry?.since).toBe(7000);
  });

  it("keeps independent status per classKey", () => {
    const published: string[] = [];
    const tracker = createPollFailureStatusTracker({
      now: () => 0,
      recoveryAfterMs: 1000,
      publishTransition: (text) => published.push(text),
    });
    tracker.report("memory-footprint:ownership", "A");
    tracker.report("serving-topology:poll", "B");
    tracker.report("memory-footprint:ownership", "A");
    expect(published).toEqual(["A", "B"]);
    expect(tracker.getActiveStatuses().map((e) => e.classKey).sort()).toEqual([
      "memory-footprint:ownership",
      "serving-topology:poll",
    ]);
  });

  it("getActiveStatuses returns entries oldest-first", () => {
    let clock = 0;
    const tracker = createPollFailureStatusTracker({
      now: () => clock,
      recoveryAfterMs: 100_000,
      publishTransition: () => {},
    });
    tracker.report("b", "B");
    clock = 10;
    tracker.report("a", "A");
    expect(tracker.getActiveStatuses().map((e) => e.classKey)).toEqual(["b", "a"]);
  });
});

describe("formatFailureRecoveredLine", () => {
  it("includes classKey, total count, and a compact duration", () => {
    const entry: PollFailureStatusEntry = {
      classKey: "serving-topology:poll",
      message: "poll failed: X",
      count: 12,
      since: 0,
      lastSeenAt: 44_000,
    };
    const text = formatFailureRecoveredLine(entry, 46_000);
    expect(text).toContain("serving-topology:poll");
    expect(text).toContain("12 occurrences");
    expect(text).toContain("46s");
  });

  it("singularizes a one-occurrence recovery", () => {
    const entry: PollFailureStatusEntry = {
      classKey: "x",
      message: "m",
      count: 1,
      since: 0,
      lastSeenAt: 0,
    };
    expect(formatFailureRecoveredLine(entry, 1000)).toContain("1 occurrence");
    expect(formatFailureRecoveredLine(entry, 1000)).not.toContain("1 occurrences");
  });
});
