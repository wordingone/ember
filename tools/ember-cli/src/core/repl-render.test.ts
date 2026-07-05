// core/repl-render.test.ts — unit coverage for the shared REPL-wide render helpers: prompt
// rendering, ANSI-aware word wrap (no mid-word cuts), and the new compact 4-line banner.

import { describe, it, expect } from "bun:test";
import { ANSI } from "./monitor-render.ts";
import { PROMPT_TEXT, renderPrompt, wrapAnsi, wrapForDisplay, renderBanner } from "./repl-render.ts";

const ANSI_RE = /\x1b\[[0-9;]*m/g;
const visible = (s: string) => s.replace(ANSI_RE, "");

// ---------------------------------------------------------------------------
// renderPrompt
// ---------------------------------------------------------------------------

describe("renderPrompt", () => {
  it("plain prompt is exactly the prompt text when color is disabled", () => {
    expect(renderPrompt(false)).toBe(PROMPT_TEXT);
  });

  it("colored prompt wraps the same text in cyan + reset", () => {
    const colored = renderPrompt(true);
    expect(colored).toBe(`${ANSI.cyan}${PROMPT_TEXT}${ANSI.reset}`);
    expect(visible(colored)).toBe(PROMPT_TEXT);
  });

  it("prompt text itself is 'ember> ' (trailing space, no newline)", () => {
    expect(PROMPT_TEXT).toBe("ember> ");
    expect(PROMPT_TEXT.endsWith("\n")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// wrapAnsi — word-boundary, ANSI-safe
// ---------------------------------------------------------------------------

describe("wrapAnsi", () => {
  it("returns the text unchanged (one line) when it already fits", () => {
    expect(wrapAnsi("short line", 100)).toEqual(["short line"]);
  });

  it("never breaks a word mid-character: every wrapped line's words appear intact", () => {
    const words = Array.from({ length: 20 }, (_, i) => `word${i}`);
    const text = words.join(" ");
    const lines = wrapAnsi(text, 30);
    const rejoined = lines.join(" ").split(/\s+/).filter(Boolean);
    // Every original word must appear, verbatim, somewhere in the rejoined token stream --
    // i.e. no word was ever split across a line boundary.
    for (const w of words) expect(rejoined).toContain(w);
    // And no wrapped line exceeds the requested width.
    for (const l of lines) expect(visible(l).length).toBeLessThanOrEqual(30);
  });

  it("does not split a single word longer than the width -- puts it on its own line", () => {
    const longWord = "x".repeat(50);
    const lines = wrapAnsi(`short ${longWord} tail`, 20);
    expect(lines.some((l) => l.includes(longWord))).toBe(true);
    for (const l of lines) {
      // the long-word line necessarily exceeds width (unavoidable), but no OTHER line does
      if (!l.includes(longWord)) expect(visible(l).length).toBeLessThanOrEqual(20);
    }
  });

  it("preserves multi-space runs (column-alignment padding) when no wrap is needed", () => {
    const padded = "C0         AUDIT-INCIDENT reason text here";
    const lines = wrapAnsi(padded, 100);
    expect(lines).toEqual([padded]);
  });

  it("ANSI escape codes are never split and never counted toward width", () => {
    const colored = `${ANSI.red}word1 word2 word3 word4 word5${ANSI.reset}`;
    const lines = wrapAnsi(colored, 12);
    // Every escape code that appears is a COMPLETE, valid code (never a partial/truncated one).
    for (const l of lines) {
      const codes = l.match(/\x1b\[[0-9;]*m?/g) ?? [];
      for (const c of codes) expect(/^\x1b\[[0-9;]*m$/.test(c)).toBe(true);
    }
    // Visible width per line stays within budget.
    for (const l of lines) expect(visible(l).length).toBeLessThanOrEqual(12);
  });

  it("a color still open at a line break is reset at the break and reopened on the next line (never bleeds)", () => {
    const colored = `${ANSI.dim}alpha beta gamma delta epsilon${ANSI.reset}`;
    const lines = wrapAnsi(colored, 12);
    expect(lines.length).toBeGreaterThan(1);
    // Every line except possibly the very last carries a matching open+reset pair, or is fully
    // plain -- i.e. no line ends with an unterminated color code that could bleed into whatever
    // prints next.
    for (const l of lines) {
      const hasOpen = l.includes(ANSI.dim);
      const hasReset = l.includes(ANSI.reset);
      expect(hasOpen === hasReset || !hasOpen).toBe(true);
    }
  });

  it("collapses to a safe minimum width instead of looping forever on width <= 0", () => {
    const lines = wrapAnsi("a b c", 0);
    expect(lines.length).toBeGreaterThan(0);
    expect(lines.join(" ").replace(/\s+/g, " ").trim()).toBe("a b c");
  });
});

// ---------------------------------------------------------------------------
// wrapForDisplay — adds indentation to continuation lines
// ---------------------------------------------------------------------------

describe("wrapForDisplay", () => {
  it("single-line text is returned as-is, no indent applied", () => {
    expect(wrapForDisplay("short", 50)).toEqual(["short"]);
  });

  it("continuation lines are indented and the first line is not", () => {
    const text = Array.from({ length: 15 }, (_, i) => `token${i}`).join(" ");
    const lines = wrapForDisplay(text, 30, "  ");
    expect(lines.length).toBeGreaterThan(1);
    expect(lines[0]!.startsWith("  ")).toBe(false);
    for (const l of lines.slice(1)) expect(l.startsWith("  ")).toBe(true);
  });

  it("indented continuation lines never exceed the requested width", () => {
    const text = Array.from({ length: 15 }, (_, i) => `token${i}`).join(" ");
    const width = 30;
    const lines = wrapForDisplay(text, width, "  ");
    for (const l of lines) expect(visible(l).length).toBeLessThanOrEqual(width);
  });
});

// ---------------------------------------------------------------------------
// renderBanner — compact 4-line header, line-count cap
// ---------------------------------------------------------------------------

describe("renderBanner", () => {
  it("produces exactly 4 logical lines (compact header replacing the old 7-line dump)", () => {
    const lines = renderBanner({ red: 7, green: 23 }, false);
    expect(lines.length).toBe(4);
  });

  it("includes the title, the command list, a try-nudge, and the not-green count", () => {
    const lines = renderBanner({ red: 7, green: 23 }, false);
    expect(lines[0]).toContain("Ember Observatory");
    expect(lines[1]).toContain("commands:");
    expect(lines[2]).toBe("try: monitor | evidence monitor 0");
    expect(lines[3]).toBe("board: 7 not-green of 30 - type monitor");
  });

  it("title is colored cyan when colorEnabled, plain otherwise", () => {
    const plain = renderBanner({ red: 1, green: 2 }, false);
    const colored = renderBanner({ red: 1, green: 2 }, true);
    expect(plain[0]).not.toContain("\x1b[");
    expect(colored[0]).toContain(ANSI.cyan);
    expect(visible(colored[0]!)).toBe(plain[0]);
  });

  it("not-green count denominator is green+red, matching the boot banner's own math", () => {
    const lines = renderBanner({ red: 3, green: 27 }, false);
    expect(lines[3]).toBe("board: 3 not-green of 30 - type monitor");
  });
});
