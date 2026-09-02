// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// welcome-v2-border-check.test.ts — B2 site-specific check: WelcomeV2 has a FIXED width
// (WELCOME_THRESHOLD) when not compact, so a real 1-cell-per-side border reservation narrows its
// content area by 2 cells versus the previous (no-op) border. Confirms the greeting still renders
// whole (not clipped) and the border actually paints, at all three PTY-required widths.
import { describe, test, expect } from "bun:test";
import React from "react";
import { WelcomeV2 } from "./logo-homescreen.ts";
import { mountInk } from "../ink/reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols: number, rows = 10): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

describe("WelcomeV2 with real border painted", () => {
  for (const cols of [80, 100, 125]) {
    test(`renders a closed border with no clipped greeting at width ${cols}`, () => {
      const out = mountAndCapture(React.createElement(WelcomeV2, { viewportWidth: cols }), cols);
      expect(out).toContain("╭");
      expect(out).toContain("╮");
      expect(out).toContain("Welcome back!");
    });
  }
});
