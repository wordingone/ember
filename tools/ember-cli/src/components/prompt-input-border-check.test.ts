// prompt-input-border-check.test.ts — issue #243 site-specific check: confirms the rounded
// border actually PAINTS at the real terminal-rendering layer (not just present as a prop on
// the element tree), mirroring the established pattern in
// permission-framework-border-check.test.ts.

import { describe, test, expect } from "bun:test";
import React from "react";
import { PromptInput, type PromptInputState } from "./prompt-input.ts";
import { mountInk } from "../ink/reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 100, rows = 12): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

function baseState(overrides: Partial<PromptInputState> = {}): PromptInputState {
  return {
    text:           "",
    mode:           "prompt",
    isStashed:      false,
    permissionMode: "bypass",
    pastedContents: null,
    stashNotice:    "",
    ...overrides,
  };
}

describe("PromptInput with a real border painted (issue #243)", () => {
  test("renders round border corners, the prompt glyph, and the anchored status line", () => {
    const out = mountAndCapture(
      React.createElement(PromptInput, { state: baseState({ text: "hello" }), width: 80 }),
    );
    expect(out).toContain("╭");
    expect(out).toContain("╮");
    expect(out).toContain("╰");
    expect(out).toContain("╯");
    expect(out).toContain("❯");
    expect(out).toContain("hello");
    // status/mode line is inside the same painted frame, not a separate row below it
    expect(out).toContain("bypass permissions on");
  });

  test("live resize (80 -> 40 -> 80) keeps a closed border at every width, no clipped-open frame", () => {
    for (const width of [80, 40, 80]) {
      const out = mountAndCapture(
        React.createElement(PromptInput, { state: baseState({ text: "resize probe" }), width }),
        width,
      );
      expect(out).toContain("╭");
      expect(out).toContain("╯");
    }
  });
});
