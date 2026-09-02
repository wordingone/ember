// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// state/loop-phase.test.ts — tests for setLoopPhase/getCognitiveMode/getModeHistory (AC9-AC10)
// Spec: specs/surface6-fireball-observatory.md

import { describe, it, expect, beforeEach } from "bun:test";
import {
  setLoopPhase,
  getCognitiveMode,
  getModeHistory,
  resetLoopPhaseForTests,
} from "./app-state.ts";

// Reset module-level state before each test to prevent cross-test contamination.
beforeEach(() => {
  resetLoopPhaseForTests();
});

// ---------------------------------------------------------------------------
// AC9: setLoopPhase publishes phase; getCognitiveMode returns derived mode
// ---------------------------------------------------------------------------

describe("AC9: setLoopPhase → getCognitiveMode", () => {
  it("initial state maps to 'observe' (idle phase default)", () => {
    expect(getCognitiveMode()).toBe("observe");
  });

  it("setLoopPhase('streaming_text') → getCognitiveMode() returns 'orient'", () => {
    setLoopPhase("streaming_text");
    expect(getCognitiveMode()).toBe("orient");
  });

  it("setLoopPhase('tool_call') → getCognitiveMode() returns 'act'", () => {
    setLoopPhase("tool_call");
    expect(getCognitiveMode()).toBe("act");
  });

  it("setLoopPhase('tool_result') → getCognitiveMode() returns 'verify'", () => {
    setLoopPhase("tool_result");
    expect(getCognitiveMode()).toBe("verify");
  });

  it("setLoopPhase('compacting') → getCognitiveMode() returns 'consolidate'", () => {
    setLoopPhase("compacting");
    expect(getCognitiveMode()).toBe("consolidate");
  });

  it("setLoopPhase('awaiting_input') → getCognitiveMode() returns 'ask'", () => {
    setLoopPhase("awaiting_input");
    expect(getCognitiveMode()).toBe("ask");
  });

  it("setLoopPhase('final_response') → getCognitiveMode() returns 'report'", () => {
    setLoopPhase("final_response");
    expect(getCognitiveMode()).toBe("report");
  });

  it("setLoopPhase('error') → getCognitiveMode() returns 'rollback'", () => {
    setLoopPhase("error");
    expect(getCognitiveMode()).toBe("rollback");
  });

  it("most recent setLoopPhase wins", () => {
    setLoopPhase("streaming_text");
    setLoopPhase("tool_call");
    setLoopPhase("idle");
    expect(getCognitiveMode()).toBe("observe");
  });
});

// ---------------------------------------------------------------------------
// AC10: bounded ring — getModeHistory keeps newest ≤100 entries
// ---------------------------------------------------------------------------

describe("AC10: bounded ring — getModeHistory", () => {
  it("returns empty array initially", () => {
    expect(getModeHistory()).toEqual([]);
  });

  it("records each phase transition as a derived CognitiveMode entry", () => {
    setLoopPhase("streaming_text");
    setLoopPhase("tool_call");
    expect(getModeHistory()).toEqual(["orient", "act"]);
  });

  it("returns a copy (mutation of the returned array does not affect state)", () => {
    setLoopPhase("streaming_text");
    const hist = getModeHistory();
    hist.push("act");
    expect(getModeHistory()).toEqual(["orient"]);
  });

  it("keeps newest when exactly 100 transitions occur (no eviction needed)", () => {
    for (let i = 0; i < 100; i++) {
      setLoopPhase("streaming_text");
    }
    expect(getModeHistory().length).toBe(100);
  });

  it("caps at 100 entries when >100 transitions occur", () => {
    for (let i = 0; i < 110; i++) {
      setLoopPhase(i % 2 === 0 ? "streaming_text" : "tool_call");
    }
    expect(getModeHistory().length).toBe(100);
  });

  it("eviction keeps newest 100 (last pushed entries survive)", () => {
    // Push 100 'orient' entries, then 5 'rollback' entries — total 105
    for (let i = 0; i < 100; i++) {
      setLoopPhase("streaming_text"); // → orient
    }
    for (let i = 0; i < 5; i++) {
      setLoopPhase("error"); // → rollback
    }
    const hist = getModeHistory();
    expect(hist.length).toBe(100);
    // Newest 5 should be 'rollback'
    expect(hist.slice(-5)).toEqual(["rollback", "rollback", "rollback", "rollback", "rollback"]);
    // First 95 should be 'orient'
    expect(hist.slice(0, 5)).toEqual(["orient", "orient", "orient", "orient", "orient"]);
  });

  it("last entry in history matches current getCognitiveMode()", () => {
    setLoopPhase("error");
    setLoopPhase("final_response");
    const hist = getModeHistory();
    expect(hist[hist.length - 1]).toBe(getCognitiveMode());
  });
});
