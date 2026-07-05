// components/markdown-and-code.test.ts — increment 6 step B: identity/primary tokens applied to
// markdown headings + inline code (previously bold-only heading, hardcoded "cyan" inline code).

import { describe, it, expect } from "bun:test";
import { Markdown, renderInline, isSyntaxHighlightEnabled } from "./markdown-and-code.ts";
import { color } from "./design-system.ts";

function children(el: any): any[] {
  const c = el.props.children;
  return Array.isArray(c) ? c : [c];
}

describe("Markdown headings — identity color token (was bold-only, no color)", () => {
  it("a heading's Text element carries the identity fg color", () => {
    const el = Markdown({ content: "# Title" });
    const headingText = children(el)[0];
    expect(headingText.props.color).toBe(color("identity", "fg", "dark"));
  });
});

// issue #56 root cause: entrypoints/process-entry.ts defaults this flag via
// `process.env["EMBER_SYNTAX_HIGHLIGHT"] ??= "0"` -- a STRING "0", meant to mean "off". The gate
// used `!!process.env["EMBER_SYNTAX_HIGHLIGHT"]`, and `!!"0"` is `true` in JavaScript (any
// non-empty string is truthy) -- so once process-entry.ts's module-level default ran even once in
// a process, highlighting was permanently ON for every test that shared that process, including
// ones (like d5-chat-turn-render.test.ts) that never touch the env var and assume the default
// (unset) plain-text behavior. This is the actual singleton carrier behind the #56 test-isolation
// bleed: not stale cache content, a JS truthy-string footgun on a process-global env var.
describe("isSyntaxHighlightEnabled — issue #56: '0' must mean disabled, not merely 'a set string'", () => {
  const KEY = "EMBER_SYNTAX_HIGHLIGHT";

  function withEnv<T>(value: string | undefined, fn: () => T): T {
    const saved = process.env[KEY];
    if (value === undefined) delete process.env[KEY]; else process.env[KEY] = value;
    try { return fn(); } finally {
      if (saved === undefined) delete process.env[KEY]; else process.env[KEY] = saved;
    }
  }

  it("EMBER_SYNTAX_HIGHLIGHT='0' (process-entry.ts's own default) is DISABLED, not enabled", () => {
    expect(withEnv("0", () => isSyntaxHighlightEnabled())).toBe(false);
  });

  it("unset is disabled", () => {
    expect(withEnv(undefined, () => isSyntaxHighlightEnabled())).toBe(false);
  });

  it("EMBER_SYNTAX_HIGHLIGHT='1' is enabled", () => {
    expect(withEnv("1", () => isSyntaxHighlightEnabled())).toBe(true);
  });
});

describe("renderInline inline code — primary token (was hardcoded 'cyan' literal)", () => {
  it("inline `code` span color equals the primary fg token, not a bare string literal", () => {
    const el = renderInline("see `foo()` now");
    const codeSpan = children(el).find((c: any) => c?.props?.children === "foo()");
    expect(codeSpan.props.color).toBe(color("primary", "fg", "dark"));
    expect(codeSpan.props.color).toBe("cyan"); // primary token IS cyan -- same value, sourced from the token
  });
});
