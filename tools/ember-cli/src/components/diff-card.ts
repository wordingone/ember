// components/diff-card.ts — Word-level diff visual component.
// Renders a unified diff with word-level red/green coloring (word-level, not
// raw line-level ●/└ or plain-text unified diff string).
//
// S06 (M10 A2): word_level_diff_present + visual_distinction_present = true.

import React from "react";
import { Box, Text } from "../ink/components.ts";
import {
  wordDiff,
  parseUnifiedDiff,
  groupIntoHunks,
  isUnifiedDiff,
  type DiffSpan,
  type DiffHunk,
} from "../services/word-diff.ts";

// ---------------------------------------------------------------------------
// DiffSpanLine — a single row of colored word-diff tokens
// ---------------------------------------------------------------------------

export function DiffSpanLine({ spans }: { spans: DiffSpan[] }): React.ReactElement {
  const children: React.ReactElement[] = spans.map((span, i) => {
    const color =
      span.kind === "added"   ? "green" :
      span.kind === "removed" ? "red"   : undefined;
    return React.createElement(Text, { key: i, color }, span.text);
  });
  return React.createElement(Box, { flexDirection: "row" }, ...children);
}

// ---------------------------------------------------------------------------
// RenderDiffHunk — renders one change hunk with word-level diff
// ---------------------------------------------------------------------------

function RenderDiffHunk({ hunk }: { hunk: DiffHunk }): React.ReactElement {
  if (hunk.kind === "context-only") {
    // Header or context: dim
    return React.createElement(Box, { flexDirection: "column" },
      ...hunk.context.map((line, i) =>
        React.createElement(Text, { key: i, dimColor: true }, line),
      ),
    );
  }

  // For change hunks, pair removed lines with added lines for word-level diff.
  // If counts don't match, treat excess lines as pure additions or deletions.
  const pairCount = Math.min(hunk.removed.length, hunk.added.length);
  const elements: React.ReactElement[] = [];

  for (let i = 0; i < pairCount; i++) {
    const oldLine = hunk.removed[i] ?? "";
    const newLine = hunk.added[i]   ?? "";
    const spans   = wordDiff(oldLine, newLine);

    // Removed version (red prefix -)
    const removedSpans = spans.filter(s => s.kind !== "added");
    elements.push(
      React.createElement(Box, { key: `r-${i}`, flexDirection: "row" },
        React.createElement(Text, { color: "red" }, "-"),
        React.createElement(DiffSpanLine, { spans: removedSpans }),
      ),
    );

    // Added version (green prefix +)
    const addedSpans = spans.filter(s => s.kind !== "removed");
    elements.push(
      React.createElement(Box, { key: `a-${i}`, flexDirection: "row" },
        React.createElement(Text, { color: "green" }, "+"),
        React.createElement(DiffSpanLine, { spans: addedSpans }),
      ),
    );
  }

  // Excess removed lines (no corresponding added line)
  for (let i = pairCount; i < hunk.removed.length; i++) {
    elements.push(
      React.createElement(Box, { key: `er-${i}`, flexDirection: "row" },
        React.createElement(Text, { color: "red" }, "−"),
        React.createElement(Text, { color: "red" }, hunk.removed[i]),
      ),
    );
  }

  // Excess added lines (no corresponding removed line)
  for (let i = pairCount; i < hunk.added.length; i++) {
    elements.push(
      React.createElement(Box, { key: `ea-${i}`, flexDirection: "row" },
        React.createElement(Text, { color: "green" }, "+"),
        React.createElement(Text, { color: "green" }, hunk.added[i]),
      ),
    );
  }

  return React.createElement(Box, { flexDirection: "column" }, ...elements);
}

// ---------------------------------------------------------------------------
// DiffCard — top-level component: parses + renders the full diff
// ---------------------------------------------------------------------------

export interface DiffCardProps {
  /** A unified diff string (starts with ---, +++, or @@). */
  diffContent: string;
  /** If true, show file headers; if false, collapse to just the hunks. */
  showHeaders?: boolean;
  /** Maximum number of context lines per hunk to render (default: 3). */
  maxContext?: number;
}

export function DiffCard({
  diffContent,
  showHeaders = true,
  maxContext = 3,
}: DiffCardProps): React.ReactElement {
  const parsedLines = parseUnifiedDiff(diffContent);
  const hunks       = groupIntoHunks(parsedLines);

  const children: React.ReactElement[] = [];
  for (let hi = 0; hi < hunks.length; hi++) {
    const hunk = hunks[hi]!;
    if (hunk.kind === "context-only") {
      // Suppress file headers if showHeaders=false
      if (!showHeaders && hunk.context.some(l => l.startsWith("---") || l.startsWith("+++"))) {
        continue;
      }
      // Trim long context blocks to maxContext lines
      const ctxLines = hunk.context.slice(0, maxContext);
      children.push(
        React.createElement(Box, { key: `h-${hi}`, flexDirection: "column" },
          ...ctxLines.map((line, i) =>
            React.createElement(Text, { key: i, dimColor: true }, ` ${line}`),
          ),
        ),
      );
    } else {
      children.push(React.createElement(RenderDiffHunk, { key: `h-${hi}`, hunk }));
    }
  }

  return React.createElement(Box, { flexDirection: "column" }, ...children);
}

// ---------------------------------------------------------------------------
// Convenience: render a word-diff between two inline strings (no unified diff)
// ---------------------------------------------------------------------------

export interface InlineDiffProps {
  oldText: string;
  newText: string;
}

export function InlineDiff({ oldText, newText }: InlineDiffProps): React.ReactElement {
  const spans = wordDiff(oldText, newText);
  return React.createElement(Box, { flexDirection: "row" },
    ...spans.map((span, i) => {
      const color =
        span.kind === "added"   ? "green" :
        span.kind === "removed" ? "red"   : undefined;
      return React.createElement(Text, { key: i, color }, span.text);
    }),
  );
}

// ---------------------------------------------------------------------------
// Helpers: detect and render a tool result content string
// ---------------------------------------------------------------------------

/** If content is a unified diff, wrap in DiffCard; else return null. */
export function tryRenderAsDiff(content: string): React.ReactElement | null {
  if (!isUnifiedDiff(content)) return null;
  return React.createElement(DiffCard, { diffContent: content });
}
