// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// markdown-and-code.ts — Markdown renderer and syntax-highlighted code blocks.
// Bundle: components/markdown-and-code.ts (line 321756)

import React from "react";
import { Box, Text, RawAnsi } from "../ink/components.ts";
import {
  LRUCache,
  HIGHLIGHT_CACHE_MAX,
  highlightCache,
  hashPair,
} from "../services/highlight-cache.ts";
import { populateHighlight } from "../services/syntax-highlight.ts";
import { color } from "./design-system.ts";

// Re-export shared cache primitives for backward-compatibility.
export { LRUCache, HIGHLIGHT_CACHE_MAX, highlightCache, hashPair };

// ---------------------------------------------------------------------------
// Syntax-highlight gate + helpers
// ---------------------------------------------------------------------------

// Issue #56 / #581: entrypoints/process-entry.ts seeds this env var with the STRING "0"
// (`??= "0"`, meant to mean "off"). The old gate used `!!process.env[...]`, and `!!"0"` is
// `true` in JavaScript (any non-empty string is truthy) -- so the module-level default flipped
// highlighting permanently ON for every process that ever imported the entrypoint, including
// unrelated test files sharing that process. Comparing against the literal enabled value ("1")
// makes "0" and unset both correctly read as disabled.
export function isSyntaxHighlightEnabled(): boolean {
  return process.env["EMBER_SYNTAX_HIGHLIGHT"] === "1";
}

// ---------------------------------------------------------------------------
// HighlightedCodeFallback — plain-text fallback when highlighting is off
// ---------------------------------------------------------------------------

export interface HighlightedCodeFallbackProps { code: string; }

export function HighlightedCodeFallback({ code }: HighlightedCodeFallbackProps): React.ReactElement {
  return React.createElement(Text, null, code);
}

/** Returns an ANSI string when highlighting is enabled (always populates cache),
 *  or null when the gate is off so the caller can render plain text. */
export function syncHighlight(language: string, code: string): string | null {
  if (!isSyntaxHighlightEnabled()) return null;
  return populateHighlight(language, code);
}

// ---------------------------------------------------------------------------
// HighlightedCode — renders ANSI-highlighted code via RawAnsi, or falls back
// ---------------------------------------------------------------------------

export interface HighlightedCodeProps { language: string; code: string; }

export function HighlightedCode({ language, code }: HighlightedCodeProps): React.ReactElement {
  const highlighted = syncHighlight(language, code);
  if (highlighted !== null) {
    // highlighted contains ANSI SGR escape codes — route through RawAnsi so
    // the ink rendering pipeline writes them directly to stdout (not escaped).
    return React.createElement(RawAnsi, null, highlighted);
  }
  return React.createElement(Text, null, code);
}

// ---------------------------------------------------------------------------
// Ordered-list label builder
// ---------------------------------------------------------------------------

export function buildOrderedListLabel(indices: number[]): string {
  return indices.join(".") + ".";
}

// ---------------------------------------------------------------------------
// Markdown AST node types
// ---------------------------------------------------------------------------

export type MarkdownNodeType =
  | "heading"
  | "code_block"
  | "hr"
  | "ul"
  | "ol"
  | "blockquote"
  | "paragraph"
  | "table";

export interface MarkdownNode {
  type:      MarkdownNodeType;
  content?:  string;
  language?: string;
  level?:    number;
  index?:    number;
  depth?:    number;
  /** table node only: header row + body rows, each a list of raw (untrimmed-inline) cell strings */
  header?:   string[];
  rows?:     string[][];
}

// ---------------------------------------------------------------------------
// parseMarkdown — streaming line-by-line parser
// ---------------------------------------------------------------------------

/** Splits a pipe-delimited table row into trimmed cells, dropping the optional leading/trailing
 * empty cell produced by a line that opens/closes with "|" (GFM table syntax). */
function parseTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|"))   trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map((cell) => cell.trim());
}

/** GFM table delimiter row: cells containing only "-", ":" and whitespace, e.g. `---|:---:|---`. */
function isTableSeparatorRow(line: string): boolean {
  const cells = parseTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-+:?$/.test(cell));
}

export function parseMarkdown(content: string): MarkdownNode[] {
  const nodes: MarkdownNode[] = [];
  const lines = content.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i] ?? "";

    // Fenced code block
    if (line.startsWith("```")) {
      const language  = line.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").startsWith("```")) {
        codeLines.push(lines[i] ?? "");
        i++;
      }
      nodes.push({ type: "code_block", language, content: codeLines.join("\n") });
      i++;
      continue;
    }

    // ATX heading — issue #111 must-win checklist ("headings h1-h6 render distinctly"):
    // was capped at (#{1,4}), silently demoting h5/h6 to plain paragraphs.
    const headingMatch = line.match(/^(#{1,6})\s+(.*)/);
    if (headingMatch) {
      nodes.push({ type: "heading", level: headingMatch[1]!.length, content: headingMatch[2] ?? "" });
      i++;
      continue;
    }

    // GFM table: a header row immediately followed by a `---|---` delimiter row.
    // Issue #111 must-win checklist ("Tables render aligned") — previously unimplemented,
    // every pipe row fell through to the paragraph case and rendered as raw "| a | b |" text.
    if (line.includes("|") && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1] ?? "")) {
      const header = parseTableRow(line);
      i += 2; // skip header + delimiter
      const rows: string[][] = [];
      while (i < lines.length && (lines[i] ?? "").includes("|") && (lines[i] ?? "").trim() !== "") {
        rows.push(parseTableRow(lines[i]!));
        i++;
      }
      nodes.push({ type: "table", header, rows });
      continue;
    }

    // Thematic break (---)
    if (/^---+$/.test(line.trim())) {
      nodes.push({ type: "hr" });
      i++;
      continue;
    }

    // Unordered list item (-, *, +)
    if (/^[-*+]\s/.test(line)) {
      nodes.push({ type: "ul", content: line.slice(2) });
      i++;
      continue;
    }

    // Ordered list item (N. text)
    const olMatch = line.match(/^(\d+)\.\s+(.*)/);
    if (olMatch) {
      nodes.push({ type: "ol", content: olMatch[2] ?? "", index: parseInt(olMatch[1]!, 10), depth: 0 });
      i++;
      continue;
    }

    // Blockquote
    if (line.startsWith("> ")) {
      nodes.push({ type: "blockquote", content: line.slice(2) });
      i++;
      continue;
    }

    // Paragraph (skip blank lines)
    if (line.trim()) {
      nodes.push({ type: "paragraph", content: line });
    }
    i++;
  }

  return nodes;
}

// ---------------------------------------------------------------------------
// renderInline — handles **bold** and `inline code` spans
// ---------------------------------------------------------------------------

/** [label](url) — issue #111 must-win checklist ("Links render (distinguishable, not raw URLs
 * mid-prose)"): previously unimplemented, a markdown link rendered as literal
 * "[label](https://...)" text indistinguishable from surrounding prose. Renders just the label,
 * styled with the primary accent + underline so it reads as interactive without dumping the raw
 * URL into the flow (terminals have no href — the label IS the visible affordance). Non-link
 * segments recurse through renderInlinePlain so bold/inline-code still work around a link. */
function renderInlineWithLinks(text: string): React.ReactElement {
  const linkParts = text.split(/(\[[^\]]+\]\([^)]+\))/g);
  if (linkParts.length === 1) return renderInlinePlain(text);
  return React.createElement(
    React.Fragment,
    null,
    ...linkParts.filter((part) => part !== "").map((part, idx) => {
      const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        return React.createElement(
          Text,
          { key: idx, color: color("primary", "fg", "dark"), underline: true },
          linkMatch[1],
        );
      }
      return React.cloneElement(renderInlinePlain(part), { key: idx });
    }),
  );
}

function renderInlinePlain(text: string): React.ReactElement {
  // **bold** takes precedence
  const boldParts = text.split(/(\*\*[^*]+\*\*)/g);
  if (boldParts.length > 1) {
    return React.createElement(
      React.Fragment,
      null,
      ...boldParts.map((part, idx) => {
        const boldMatch = part.match(/^\*\*([^*]+)\*\*$/);
        return boldMatch
          ? React.createElement(Text, { key: idx, bold: true }, boldMatch[1])
          : React.createElement(Text, { key: idx }, part);
      }),
    );
  }

  // `inline code`
  const codeParts = text.split(/(`[^`]+`)/g);
  if (codeParts.length > 1) {
    return React.createElement(
      React.Fragment,
      null,
      ...codeParts.map((part, idx) => {
        const codeMatch = part.match(/^`([^`]+)`$/);
        return codeMatch
          ? React.createElement(Text, { key: idx, color: "cyan" }, codeMatch[1])
          : React.createElement(Text, { key: idx }, part);
      }),
    );
  }

  return React.createElement(Text, null, text);
}

/** Public entry point: bold/inline-code (renderInlinePlain) plus link spans, composable. */
export function renderInline(text: string): React.ReactElement {
  return renderInlineWithLinks(text);
}

// ---------------------------------------------------------------------------
// heading style — issue #111 must-win checklist ("headings h1-h6 render distinctly"): a fixed,
// monotonically-decreasing weight/color/style ramp so all 6 levels are visually distinguishable
// from each other, not just a bold/non-bold binary that collapsed h3-h6 into one look.
// ---------------------------------------------------------------------------

interface HeadingStyle { bold: boolean; italic: boolean; dimColor: boolean; underline: boolean; colorKey: "identity" | "primary" | "muted"; }

const HEADING_STYLES: Record<number, HeadingStyle> = {
  1: { bold: true,  italic: false, dimColor: false, underline: true,  colorKey: "identity" },
  2: { bold: true,  italic: false, dimColor: false, underline: false, colorKey: "identity" },
  3: { bold: true,  italic: false, dimColor: false, underline: false, colorKey: "primary" },
  4: { bold: false, italic: false, dimColor: false, underline: false, colorKey: "primary" },
  5: { bold: false, italic: true,  dimColor: false, underline: false, colorKey: "muted" },
  6: { bold: false, italic: true,  dimColor: true,  underline: false, colorKey: "muted" },
};

function headingStyle(level: number): HeadingStyle {
  return HEADING_STYLES[Math.min(6, Math.max(1, level))] ?? HEADING_STYLES[1]!;
}

// ---------------------------------------------------------------------------
// Markdown — root component
// ---------------------------------------------------------------------------

export interface MarkdownProps { content: string; }

export function Markdown({ content }: MarkdownProps): React.ReactElement {
  const nodes = parseMarkdown(content);

  const elements = nodes.map((node, idx) => {
    switch (node.type) {
      case "heading": {
        // Issue #581: headings carry the identity fg token (was bold-only, no color).
        // Issue #111: extended to a 6-level distinct ramp (was a 2-tier bold/non-bold binary).
        const style = headingStyle(node.level ?? 1);
        return React.createElement(
          Text,
          {
            key: idx,
            bold: style.bold,
            italic: style.italic,
            dimColor: style.dimColor,
            underline: style.underline,
            color: color(style.colorKey, "fg", "dark"),
          },
          node.content ?? "",
        );
      }
      case "table": {
        // Issue #111 must-win checklist ("Tables render aligned"): each column padded to its
        // widest cell (header included) across the whole table, so pipes line up like a real grid.
        const header = node.header ?? [];
        const rows = node.rows ?? [];
        const colCount = Math.max(header.length, ...rows.map((r) => r.length), 0);
        const colWidths: number[] = [];
        for (let c = 0; c < colCount; c++) {
          const cellsInCol = [header[c] ?? "", ...rows.map((r) => r[c] ?? "")];
          colWidths[c] = Math.max(...cellsInCol.map((cell) => cell.length));
        }
        const renderRow = (cells: string[], rowIdx: number, isHeader: boolean) =>
          React.createElement(
            Box, { key: rowIdx, flexDirection: "row" },
            ...Array.from({ length: colCount }, (_, c) => {
              const cellText = (cells[c] ?? "").padEnd(colWidths[c] ?? 0, " ");
              return React.createElement(
                Box, { key: c, marginRight: 1 },
                React.createElement(Text, { bold: isHeader }, cellText),
              );
            }),
          );
        return React.createElement(
          Box, { key: idx, flexDirection: "column" },
          renderRow(header, -1, true),
          ...rows.map((row, rIdx) => renderRow(row, rIdx, false)),
        );
      }
      case "code_block": {
        return React.createElement(HighlightedCode, {
          key:      idx,
          language: node.language ?? "",
          code:     node.content  ?? "",
        });
      }
      case "hr": {
        return React.createElement(Text, { key: idx, dimColor: true }, "─".repeat(40));
      }
      case "ul": {
        return React.createElement(
          Box, { key: idx, flexDirection: "row" },
          React.createElement(Text, null, "• "),
          renderInline(node.content ?? ""),
        );
      }
      case "ol": {
        const label = buildOrderedListLabel([node.index ?? 1]);
        return React.createElement(
          Box, { key: idx, flexDirection: "row" },
          React.createElement(Text, null, `${label} `),
          renderInline(node.content ?? ""),
        );
      }
      case "blockquote": {
        return React.createElement(
          Box, { key: idx, flexDirection: "row", paddingLeft: 2 },
          React.createElement(Text, { dimColor: true }, "│ "),
          renderInline(node.content ?? ""),
        );
      }
      case "paragraph": {
        return React.createElement(Box, { key: idx }, renderInline(node.content ?? ""));
      }
      default:
        return React.createElement(Text, { key: idx }, node.content ?? "");
    }
  });

  return React.createElement(Box, { flexDirection: "column" }, ...elements);
}
