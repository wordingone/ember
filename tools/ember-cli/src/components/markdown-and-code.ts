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

// Re-export shared cache primitives for backward-compatibility.
export { LRUCache, HIGHLIGHT_CACHE_MAX, highlightCache, hashPair };

// ---------------------------------------------------------------------------
// Syntax-highlight gate + helpers
// ---------------------------------------------------------------------------

export function isSyntaxHighlightEnabled(): boolean {
  return !!process.env["EMBER_SYNTAX_HIGHLIGHT"];
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
  | "paragraph";

export interface MarkdownNode {
  type:      MarkdownNodeType;
  content?:  string;
  language?: string;
  level?:    number;
  index?:    number;
  depth?:    number;
}

// ---------------------------------------------------------------------------
// parseMarkdown — streaming line-by-line parser
// ---------------------------------------------------------------------------

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

    // ATX heading (up to ####)
    const headingMatch = line.match(/^(#{1,4})\s+(.*)/);
    if (headingMatch) {
      nodes.push({ type: "heading", level: headingMatch[1]!.length, content: headingMatch[2] ?? "" });
      i++;
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

export function renderInline(text: string): React.ReactElement {
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

// ---------------------------------------------------------------------------
// Markdown — root component
// ---------------------------------------------------------------------------

export interface MarkdownProps { content: string; }

export function Markdown({ content }: MarkdownProps): React.ReactElement {
  const nodes = parseMarkdown(content);

  const elements = nodes.map((node, idx) => {
    switch (node.type) {
      case "heading": {
        const weight = (node.level ?? 1) <= 2;
        return React.createElement(Text, { key: idx, bold: weight }, node.content ?? "");
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
