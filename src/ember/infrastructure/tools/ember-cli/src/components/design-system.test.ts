// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// components/design-system.test.ts — Observatory identity tokens + glyph vocabulary (increment 6, step B).
// Spec: state/field-ux-map.md §8b/§9; step-A mockups (state/design-mockups/).

import { describe, it, expect } from "bun:test";
import {
  color,
  glyph,
  asciiModeEnabled,
  PANEL_BORDER_STYLE,
  UI_GLYPHS,
  type ColorKey,
} from "./design-system.ts";

// ---------------------------------------------------------------------------
// Identity color token — the Observatory ember/coal lineage, reused (not reinvented)
// ---------------------------------------------------------------------------

describe("identity color token", () => {
  it("is a member of ColorKey and resolves an fg hex in dark theme", () => {
    const key: ColorKey = "identity";
    expect(color(key, "fg", "dark")).toBe("#FF7A3D");
  });

  it("resolves a distinct fg in light theme (still on the coal/ember lineage)", () => {
    expect(color("identity", "fg", "light")).toBe("#C43410");
  });

  it("existing primary token is reused as the interaction/code accent (cyan) — not duplicated", () => {
    expect(color("primary", "fg", "dark")).toBe("cyan");
  });
});

// ---------------------------------------------------------------------------
// Glyph vocabulary — unicode + ascii pair per glyph, mirrors cognitive-mode.ts's
// EMBER_ASCII discipline so every new Step-B glyph degrades safely.
// ---------------------------------------------------------------------------

describe("glyph vocabulary", () => {
  it("turnMarker is a BMP-safe bullet, not an emoji-class glyph", () => {
    const g = UI_GLYPHS.turnMarker;
    expect(g.unicode).toBe("●");
    // U+25CF is a single BMP codepoint (not a surrogate pair / astral emoji).
    expect(g.unicode.codePointAt(0)).toBeLessThanOrEqual(0xffff);
  });

  it("glyph() returns unicode form when EMBER_ASCII is unset", () => {
    const saved = process.env["EMBER_ASCII"];
    delete process.env["EMBER_ASCII"];
    expect(glyph("turnMarker")).toBe("●");
    expect(glyph("boardHex")).toBe("⬢");
    expect(glyph("gear")).toBe("⚙");
    if (saved !== undefined) process.env["EMBER_ASCII"] = saved;
  });

  it("glyph() returns ascii fallback when EMBER_ASCII=1", () => {
    const saved = process.env["EMBER_ASCII"];
    process.env["EMBER_ASCII"] = "1";
    expect(glyph("turnMarker")).toBe("*");
    expect(glyph("boardHex")).toBe("#");
    expect(glyph("gear")).toBe("~");
    for (const name of Object.keys(UI_GLYPHS) as (keyof typeof UI_GLYPHS)[]) {
      for (const ch of [...glyph(name)]) {
        expect(ch.codePointAt(0)!).toBeLessThanOrEqual(0x7f);
      }
    }
    if (saved === undefined) delete process.env["EMBER_ASCII"];
    else process.env["EMBER_ASCII"] = saved;
  });

  it("asciiModeEnabled reflects EMBER_ASCII=1 exactly", () => {
    const saved = process.env["EMBER_ASCII"];
    process.env["EMBER_ASCII"] = "1";
    expect(asciiModeEnabled()).toBe(true);
    process.env["EMBER_ASCII"] = "0";
    expect(asciiModeEnabled()).toBe(false);
    delete process.env["EMBER_ASCII"];
    expect(asciiModeEnabled()).toBe(false);
    if (saved !== undefined) process.env["EMBER_ASCII"] = saved;
  });
});

// ---------------------------------------------------------------------------
// Panel border style — one semantic default so every bordered surface matches
// ---------------------------------------------------------------------------

describe("panel border style token", () => {
  it("is the round style used across the Step-A mockups", () => {
    expect(PANEL_BORDER_STYLE).toBe("round");
  });
});
