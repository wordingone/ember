// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// components/message-renderers.test.ts — CompactionProgressMessage acceptance tests.
// Spec: contract L22 (compaction in-progress placeholder → real component).
//
// Observable: exact string equality on the rendered Text's children prop,
// testable via props(el)["children"] without a DOM renderer.

import { describe, it, expect } from "bun:test";
import React from "react";
import {
  CompactionProgressMessage,
  COMPACTION_IN_PROGRESS_TEXT,
  COMPACTION_COMPLETE_PREFIX,
} from "./message-renderers.ts";

// ---------------------------------------------------------------------------
// Test utilities (contract-specified; these are the L29-35 helpers)
// ---------------------------------------------------------------------------

/** Extract the props of a React element as a plain record. */
function props(el: React.ReactElement): Record<string, unknown> {
  return el.props as Record<string, unknown>;
}

/** Extract the first-level string children from a React element. */
function childText(el: React.ReactElement): string {
  const ch = (el.props as { children?: unknown }).children;
  if (typeof ch === "string") return ch;
  if (Array.isArray(ch)) {
    return ch.map((c: unknown) => (typeof c === "string" ? c : "")).join("");
  }
  return String(ch ?? "");
}

// ---------------------------------------------------------------------------
// AC13 — CompactionProgressMessage: in-progress (isComplete=false)
// ---------------------------------------------------------------------------

describe("AC13: CompactionProgressMessage — isComplete=false", () => {
  it("returns a React element (non-null)", () => {
    const el = CompactionProgressMessage({ isComplete: false });
    expect(el).not.toBeNull();
  });

  it("children prop === COMPACTION_IN_PROGRESS_TEXT ('Razzle-dazzling…')", () => {
    const el = CompactionProgressMessage({ isComplete: false });
    expect(props(el)["children"]).toBe(COMPACTION_IN_PROGRESS_TEXT);
  });

  it("exact string equality: children === 'Razzle-dazzling…'", () => {
    const el = CompactionProgressMessage({ isComplete: false });
    expect(props(el)["children"]).toBe("Razzle-dazzling…");
  });

  it("childText helper agrees with props helper", () => {
    const el = CompactionProgressMessage({ isComplete: false });
    expect(childText(el)).toBe(COMPACTION_IN_PROGRESS_TEXT);
  });

  it("elapsedSecs is ignored when isComplete=false", () => {
    const withSecs   = CompactionProgressMessage({ isComplete: false, elapsedSecs: 99 });
    const withoutSecs = CompactionProgressMessage({ isComplete: false });
    expect(props(withSecs)["children"]).toBe(props(withoutSecs)["children"]);
  });
});

// ---------------------------------------------------------------------------
// AC13 — CompactionProgressMessage: complete (isComplete=true)
// ---------------------------------------------------------------------------

describe("AC13: CompactionProgressMessage — isComplete=true", () => {
  it("returns a React element (non-null)", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 7 });
    expect(el).not.toBeNull();
  });

  it("children prop === '⌁ Crunched for 7s' (elapsedSecs=7)", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 7 });
    expect(props(el)["children"]).toBe("⌁ Crunched for 7s");
  });

  it("children starts with COMPACTION_COMPLETE_PREFIX", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 7 });
    const text = String(props(el)["children"] ?? "");
    expect(text.startsWith(COMPACTION_COMPLETE_PREFIX)).toBe(true);
  });

  it("elapsedSecs defaults to 0 when omitted", () => {
    const el = CompactionProgressMessage({ isComplete: true });
    expect(props(el)["children"]).toBe("⌁ Crunched for 0s");
  });

  it("elapsedSecs=0 renders '⌁ Crunched for 0s'", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 0 });
    expect(props(el)["children"]).toBe("⌁ Crunched for 0s");
  });

  it("elapsedSecs=120 renders '⌁ Crunched for 120s'", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 120 });
    expect(props(el)["children"]).toBe("⌁ Crunched for 120s");
  });

  it("childText helper agrees with props helper", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 7 });
    expect(childText(el)).toBe("⌁ Crunched for 7s");
  });
});

// ---------------------------------------------------------------------------
// AC13 — Integration: compaction flow simulation
//
// shouldTriggerCompaction is in screens/repl.ts (COMPACTION_TOKEN_THRESHOLD=180_000).
// The dispatch seam ('compaction_progress' case in renderMsgDispatch) is pending
// in a parallel builder lane — tested here at the component level instead.
// ---------------------------------------------------------------------------

describe("AC13: integration — compaction flow simulation", () => {
  /** Mirror the pure gate from screens/repl.ts without pulling in its full dep tree. */
  const COMPACTION_TOKEN_THRESHOLD = 180_000;
  function shouldTriggerCompaction(tokenCount: number): boolean {
    return tokenCount >= COMPACTION_TOKEN_THRESHOLD;
  }

  it("shouldTriggerCompaction returns false below 180k tokens", () => {
    expect(shouldTriggerCompaction(179_999)).toBe(false);
  });

  it("shouldTriggerCompaction returns true at exactly 180k tokens", () => {
    expect(shouldTriggerCompaction(180_000)).toBe(true);
  });

  it("shouldTriggerCompaction returns true above 180k tokens", () => {
    expect(shouldTriggerCompaction(200_000)).toBe(true);
  });

  it("emit in-progress message at compaction start: renders 'Razzle-dazzling…'", () => {
    // Simulate: context hits 180k → shouldTriggerCompaction fires → render in-progress message.
    const triggered = shouldTriggerCompaction(180_000);
    expect(triggered).toBe(true);
    const msgEl = CompactionProgressMessage({ isComplete: false });
    expect(props(msgEl)["children"]).toBe(COMPACTION_IN_PROGRESS_TEXT);
  });

  it("emit complete message after compaction: renders elapsed seconds", () => {
    // Simulate: compaction finishes after 5s → render complete message.
    const msgEl = CompactionProgressMessage({ isComplete: true, elapsedSecs: 5 });
    expect(props(msgEl)["children"]).toBe("⌁ Crunched for 5s");
  });

  it("state transition: in-progress then complete produce distinct children", () => {
    const inProgress = CompactionProgressMessage({ isComplete: false });
    const complete   = CompactionProgressMessage({ isComplete: true, elapsedSecs: 3 });
    expect(props(inProgress)["children"]).not.toBe(props(complete)["children"]);
  });
});

// ---------------------------------------------------------------------------
// Constants sanity-check (preserve exact spec values)
// ---------------------------------------------------------------------------

describe("CompactionProgressMessage — constant values", () => {
  it("COMPACTION_IN_PROGRESS_TEXT is 'Razzle-dazzling…'", () => {
    expect(COMPACTION_IN_PROGRESS_TEXT).toBe("Razzle-dazzling…");
  });

  it("COMPACTION_COMPLETE_PREFIX is '⌁ Crunched for '", () => {
    expect(COMPACTION_COMPLETE_PREFIX).toBe("⌁ Crunched for ");
  });
});
