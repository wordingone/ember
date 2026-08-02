// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// components/markdown-and-code.test.ts — increment 6 step B: identity/primary tokens applied to
// markdown headings + inline code (previously bold-only heading, hardcoded "cyan" inline code).

import { describe, it, expect } from "bun:test";
import { Markdown, renderInline, isSyntaxHighlightEnabled, parseMarkdown } from "./markdown-and-code.ts";
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

// Issue #111 must-win checklist item: "Markdown headings h1-h6 render distinctly" -- the parser
// was capped at (#{1,4}) (h5/h6 silently fell through to the paragraph branch, rendering the raw
// "##### text" including hashes), and the renderer collapsed all headings to a bold/non-bold
// binary (levels 3-6 were visually identical). Both gaps are closed here through the real
// production entry points (parseMarkdown + Markdown), not a reimplementation.
describe("Markdown headings h1-h6 — issue #111 must-win checklist", () => {
  it("parseMarkdown recognizes ATX headings at every level 1-6 (was capped at 4)", () => {
    for (let level = 1; level <= 6; level++) {
      const nodes = parseMarkdown(`${"#".repeat(level)} Section ${level}`);
      expect(nodes).toEqual([{ type: "heading", level, content: `Section ${level}` }]);
    }
  });

  it("a 5-hash line no longer falls through to a raw-text paragraph", () => {
    const nodes = parseMarkdown("##### Deep heading");
    expect(nodes[0]!.type).toBe("heading");
    expect(nodes[0]!.content).toBe("Deep heading");
  });

  it("every level 1-6 renders with a visually distinct style tuple (bold/italic/dim/underline/color)", () => {
    const seen = new Set<string>();
    for (let level = 1; level <= 6; level++) {
      const el = Markdown({ content: `${"#".repeat(level)} H${level}` });
      const headingText = children(el)[0];
      const tuple = JSON.stringify({
        bold: !!headingText.props.bold,
        italic: !!headingText.props.italic,
        dim: !!headingText.props.dimColor,
        underline: !!headingText.props.underline,
        color: headingText.props.color,
      });
      seen.add(tuple);
    }
    // all 6 levels distinct from each other -- no two levels share the same rendered tuple
    expect(seen.size).toBe(6);
  });

  it("level 1 keeps the pre-existing identity fg token (backward-compat with #581)", () => {
    const el = Markdown({ content: "# Title" });
    const headingText = children(el)[0];
    expect(headingText.props.color).toBe(color("identity", "fg", "dark"));
  });
});

// Issue #111 must-win checklist item: "Links render (distinguishable, not raw URLs mid-prose)" --
// previously unimplemented; a markdown link rendered as the literal, unstyled string
// "[label](https://...)" indistinguishable from surrounding prose.
describe("Markdown links — issue #111 must-win checklist", () => {
  it("renders only the label text, not the raw URL, styled distinctly from plain prose", () => {
    const el = renderInline("see [the docs](https://example.com/x) for more");
    const kids = children(el);
    const rawUrlPresent = kids.some((c: any) =>
      typeof c?.props?.children === "string" && c.props.children.includes("https://example.com"),
    );
    expect(rawUrlPresent).toBe(false);
    const linkSpan = kids.find((c: any) => c?.props?.children === "the docs");
    expect(linkSpan).toBeTruthy();
    expect(linkSpan.props.underline).toBe(true);
    expect(linkSpan.props.color).toBe(color("primary", "fg", "dark"));
  });

  it("a link mid-paragraph still renders its surrounding plain text", () => {
    const el = renderInline("before [x](https://a.b) after");
    const kids = children(el);
    const before = kids.some((c: any) => c?.props?.children === "before ");
    expect(before).toBe(true);
  });

  it("bold text still works on a line that also contains no link (regression guard)", () => {
    const el = renderInline("**bold** plain");
    const kids = children(el);
    const boldSpan = kids.find((c: any) => c?.props?.bold === true);
    expect(boldSpan?.props?.children).toBe("bold");
  });
});

// Issue #111 must-win checklist item: "Tables render aligned" -- previously unimplemented; a
// pipe-delimited GFM table fell through to the paragraph branch, one raw "| a | b |" line at a
// time, no column alignment.
describe("Markdown tables — issue #111 must-win checklist", () => {
  const TABLE = ["| id | defect |", "|---|---|", "| 1 | short |", "| 2 | a longer cell |"].join("\n");

  it("parseMarkdown groups a header + delimiter + body rows into one table node", () => {
    const nodes = parseMarkdown(TABLE);
    expect(nodes.length).toBe(1);
    expect(nodes[0]).toEqual({
      type: "table",
      header: ["id", "defect"],
      rows: [["1", "short"], ["2", "a longer cell"]],
    });
  });

  it("Markdown renders one row per table line, each column padded to the widest cell", () => {
    const el = Markdown({ content: TABLE });
    const tableBox = children(el)[0]; // Markdown's single top-level block: the table
    const rows = children(tableBox); // [headerRow, row1, row2] Box elements
    expect(rows.length).toBe(3);
    const cellsOf = (rowEl: any) => children(rowEl).map((cellBox: any) => children(cellBox)[0].props.children);
    const headerCells = cellsOf(rows[0]);
    const row2Cells   = cellsOf(rows[2]);
    // "defect" column's widest cell is "a longer cell" (13 chars) -- every cell in that column
    // pads to that width, including the header.
    expect(headerCells[1]!.length).toBe("a longer cell".length);
    expect(row2Cells[1]).toBe("a longer cell");
  });

  it("a non-table pipe-less paragraph is unaffected (regression guard)", () => {
    const nodes = parseMarkdown("plain text, no pipes here");
    expect(nodes).toEqual([{ type: "paragraph", content: "plain text, no pipes here" }]);
  });
});
