// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// cognitive-mode.test.ts — unit tests for cognitive-mode module.
// Spec: specs/surface6-fireball-observatory.md (AC1-AC3)

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import {
  deriveCognitiveMode,
  modeGlyph,
} from "./cognitive-mode.ts";
import type { LoopPhase, CognitiveMode } from "./cognitive-mode.ts";

// ---------------------------------------------------------------------------
// AC1: deriveCognitiveMode — total mapping over all LoopPhase values
// ---------------------------------------------------------------------------

describe("AC1: deriveCognitiveMode — total phase mapping", () => {
  const cases: Array<[LoopPhase, CognitiveMode]> = [
    ["idle", "observe"],
    ["streaming_text", "orient"],
    ["tool_call", "act"],
    ["tool_result", "verify"],
    ["compacting", "consolidate"],
    ["awaiting_input", "ask"],
    ["final_response", "report"],
    ["error", "rollback"],
  ];
  for (const [phase, expected] of cases) {
    it(`${phase} → ${expected}`, () => {
      expect(deriveCognitiveMode(phase)).toBe(expected);
    });
  }
});

// ---------------------------------------------------------------------------
// AC2: modeGlyph — correct glyph, label, color per mode
// ---------------------------------------------------------------------------

describe("AC2: modeGlyph — glyphs and colors", () => {
  it("observe returns ○ with gray color", () => {
    const g = modeGlyph("observe");
    expect(g.glyph).toBe("○");
    expect(g.color).toBe("gray");
    expect(g.label).toBe("observe");
  });

  it("orient uses fireball glyph 🔥", () => {
    const g = modeGlyph("orient");
    expect(g.glyph).toBe("🔥");
    expect(g.label).toBe("orient");
  });

  it("act uses fireball glyph 🔥 with red color", () => {
    const g = modeGlyph("act");
    expect(g.glyph).toBe("🔥");
    expect(g.color).toBe("red");
    expect(g.label).toBe("act");
  });

  it("verify uses fireball glyph 🔥", () => {
    const g = modeGlyph("verify");
    expect(g.glyph).toBe("🔥");
    expect(g.label).toBe("verify");
  });

  it("consolidate uses fireball glyph 🔥", () => {
    const g = modeGlyph("consolidate");
    expect(g.glyph).toBe("🔥");
    expect(g.label).toBe("consolidate");
  });

  it("ask returns ? with magenta color", () => {
    const g = modeGlyph("ask");
    expect(g.glyph).toBe("?");
    expect(g.color).toBe("magenta");
    expect(g.label).toBe("ask");
  });

  it("report returns ✓ with green color", () => {
    const g = modeGlyph("report");
    expect(g.glyph).toBe("✓");
    expect(g.color).toBe("green");
    expect(g.label).toBe("report");
  });

  it("rollback returns ⚠ with red color", () => {
    const g = modeGlyph("rollback");
    expect(g.glyph).toBe("⚠");
    expect(g.color).toBe("red");
    expect(g.label).toBe("rollback");
  });

  it("every mode returns non-empty glyph and label", () => {
    const modes: CognitiveMode[] = [
      "observe", "orient", "act", "verify",
      "consolidate", "ask", "report", "rollback",
    ];
    for (const mode of modes) {
      const g = modeGlyph(mode);
      expect(g.glyph.length).toBeGreaterThan(0);
      expect(g.label.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// AC3: EMBER_ASCII=1 forces ASCII-only glyphs (no codepoint > 0x7F)
// ---------------------------------------------------------------------------

describe("AC3: EMBER_ASCII=1 forces ASCII-only glyphs", () => {
  let orig: string | undefined;

  beforeEach(() => {
    orig = process.env["EMBER_ASCII"];
    process.env["EMBER_ASCII"] = "1";
  });

  afterEach(() => {
    if (orig === undefined) {
      delete process.env["EMBER_ASCII"];
    } else {
      process.env["EMBER_ASCII"] = orig;
    }
  });

  const activeModes: CognitiveMode[] = ["orient", "act", "verify", "consolidate"];

  for (const mode of activeModes) {
    it(`${mode} glyph is ASCII-only under EMBER_ASCII=1`, () => {
      const g = modeGlyph(mode);
      for (const ch of [...g.glyph]) {
        expect(ch.codePointAt(0)!).toBeLessThanOrEqual(0x7f);
      }
    });
  }

  it("all modes have ASCII-only glyphs under EMBER_ASCII=1", () => {
    const modes: CognitiveMode[] = [
      "observe", "orient", "act", "verify",
      "consolidate", "ask", "report", "rollback",
    ];
    for (const mode of modes) {
      const g = modeGlyph(mode);
      for (const ch of [...g.glyph]) {
        expect(ch.codePointAt(0)!).toBeLessThanOrEqual(0x7f);
      }
    }
  });

  it("glyphs are still non-empty under EMBER_ASCII=1", () => {
    const modes: CognitiveMode[] = [
      "observe", "orient", "act", "verify",
      "consolidate", "ask", "report", "rollback",
    ];
    for (const mode of modes) {
      const g = modeGlyph(mode);
      expect(g.glyph.length).toBeGreaterThan(0);
    }
  });
});
