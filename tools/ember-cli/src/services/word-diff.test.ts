// word-diff.test.ts — AC tests for word-level diff service.
//
// AC1: tokenize — words / whitespace / punctuation are separate tokens
// AC2: wordDiff — identical text → single unchanged span
// AC3: wordDiff — single word change → removed + added spans
// AC4: wordDiff — multi-word mixed change preserves context
// AC5: wordDiff — empty old → all added; empty new → all removed
// AC6: isUnifiedDiff — detects --- / +++ / @@ prefixes; rejects plain text
// AC7: parseUnifiedDiff — typed line extraction (header/hunk/removed/added/context)
// AC8: groupIntoHunks — change hunk + context-only hunk extraction

import { describe, it, expect } from "bun:test";
import {
  tokenize,
  wordDiff,
  isUnifiedDiff,
  parseUnifiedDiff,
  groupIntoHunks,
} from "./word-diff.ts";

// ---------------------------------------------------------------------------
// AC1 — tokenize
// ---------------------------------------------------------------------------

describe("AC1: tokenize", () => {
  it("splits words from punctuation and whitespace", () => {
    const tokens = tokenize("hello, world!");
    expect(tokens).toContain("hello");
    expect(tokens).toContain(",");
    expect(tokens).toContain(" ");
    expect(tokens).toContain("world");
    expect(tokens).toContain("!");
  });

  it("preserves whitespace runs as single tokens", () => {
    const tokens = tokenize("a  b"); // two spaces
    expect(tokens).toContain("  ");
  });

  it("empty string → empty array", () => {
    expect(tokenize("")).toHaveLength(0);
  });

  it("single word → single token", () => {
    expect(tokenize("word")).toEqual(["word"]);
  });
});

// ---------------------------------------------------------------------------
// AC2 — wordDiff identical
// ---------------------------------------------------------------------------

describe("AC2: wordDiff identical", () => {
  it("identical strings → single unchanged span", () => {
    const result = wordDiff("hello world", "hello world");
    expect(result).toHaveLength(1);
    expect(result[0]!.kind).toBe("unchanged");
    expect(result[0]!.text).toBe("hello world");
  });

  it("identical empty strings → one unchanged empty span", () => {
    const result = wordDiff("", "");
    expect(result).toHaveLength(1);
    expect(result[0]!.kind).toBe("unchanged");
  });
});

// ---------------------------------------------------------------------------
// AC3 — wordDiff single word change
// ---------------------------------------------------------------------------

describe("AC3: wordDiff single word change", () => {
  it("foo→bar: produces removed(foo) + added(bar) with unchanged context", () => {
    const result = wordDiff("the foo thing", "the bar thing");
    const kinds = result.map(s => s.kind);
    expect(kinds).toContain("removed");
    expect(kinds).toContain("added");
    expect(kinds).toContain("unchanged");
    // The removed span must contain 'foo'
    const removed = result.filter(s => s.kind === "removed").map(s => s.text).join("");
    expect(removed).toContain("foo");
    const added = result.filter(s => s.kind === "added").map(s => s.text).join("");
    expect(added).toContain("bar");
  });
});

// ---------------------------------------------------------------------------
// AC4 — wordDiff multi-word mixed
// ---------------------------------------------------------------------------

describe("AC4: wordDiff multi-word mixed", () => {
  it("common prefix/suffix preserved as unchanged", () => {
    const result = wordDiff("start changed end", "start MODIFIED end");
    const unchanged = result.filter(s => s.kind === "unchanged").map(s => s.text).join("");
    expect(unchanged).toContain("start");
    expect(unchanged).toContain("end");
  });

  it("concatenating all spans reconstructs a reasonable output (no tokens lost)", () => {
    const old = "a b c d e";
    const nw  = "a b X d e";
    const spans = wordDiff(old, nw);
    // All tokens of old must appear in removed+unchanged spans
    const fromOld = spans.filter(s => s.kind !== "added").map(s => s.text).join("");
    expect(fromOld.replace(/\s+/g, " ").trim()).toMatch(/a.*b.*c.*d.*e/);
  });
});

// ---------------------------------------------------------------------------
// AC5 — edge cases: empty inputs
// ---------------------------------------------------------------------------

describe("AC5: wordDiff empty edges", () => {
  it("empty old, non-empty new → all added", () => {
    const result = wordDiff("", "hello");
    expect(result.every(s => s.kind === "added")).toBe(true);
    expect(result.map(s => s.text).join("")).toBe("hello");
  });

  it("non-empty old, empty new → all removed", () => {
    const result = wordDiff("hello", "");
    expect(result.every(s => s.kind === "removed")).toBe(true);
    expect(result.map(s => s.text).join("")).toBe("hello");
  });
});

// ---------------------------------------------------------------------------
// AC6 — isUnifiedDiff detection
// ---------------------------------------------------------------------------

describe("AC6: isUnifiedDiff", () => {
  it("recognizes --- prefix", () => {
    expect(isUnifiedDiff("--- old/file.ts\n+++ new/file.ts")).toBe(true);
  });

  it("recognizes +++ prefix", () => {
    expect(isUnifiedDiff("+++ new/file.ts")).toBe(true);
  });

  it("recognizes @@ hunk header", () => {
    expect(isUnifiedDiff("@@ -1,5 +1,5 @@")).toBe(true);
  });

  it("rejects plain text", () => {
    expect(isUnifiedDiff("File written successfully.")).toBe(false);
    expect(isUnifiedDiff("hello world")).toBe(false);
    expect(isUnifiedDiff("")).toBe(false);
  });

  it("leading whitespace is trimmed before detection", () => {
    expect(isUnifiedDiff("  --- old")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC7 — parseUnifiedDiff line classification
// ---------------------------------------------------------------------------

describe("AC7: parseUnifiedDiff", () => {
  const sample = `--- old/foo.ts
+++ new/foo.ts
@@ -1,3 +1,3 @@
 unchanged line
-removed line
+added line`;

  it("extracts header lines for --- and +++", () => {
    const lines = parseUnifiedDiff(sample);
    const headers = lines.filter(l => l.kind === "header");
    expect(headers).toHaveLength(2);
    expect(headers[0]!.text).toContain("old/foo.ts");
    expect(headers[1]!.text).toContain("new/foo.ts");
  });

  it("extracts hunk header (@@)", () => {
    const lines = parseUnifiedDiff(sample);
    expect(lines.some(l => l.kind === "hunk")).toBe(true);
  });

  it("classifies - lines as removed (without the leading -)", () => {
    const lines = parseUnifiedDiff(sample);
    const removed = lines.filter(l => l.kind === "removed");
    expect(removed).toHaveLength(1);
    expect(removed[0]!.text).toBe("removed line");
  });

  it("classifies + lines as added (without the leading +)", () => {
    const lines = parseUnifiedDiff(sample);
    const added = lines.filter(l => l.kind === "added");
    expect(added).toHaveLength(1);
    expect(added[0]!.text).toBe("added line");
  });

  it("classifies context lines (leading space, or no prefix)", () => {
    const lines = parseUnifiedDiff(sample);
    const context = lines.filter(l => l.kind === "context");
    expect(context).toHaveLength(1);
    expect(context[0]!.text).toBe("unchanged line");
  });
});

// ---------------------------------------------------------------------------
// AC8 — groupIntoHunks
// ---------------------------------------------------------------------------

describe("AC8: groupIntoHunks", () => {
  it("produces a change hunk for consecutive removed + added lines", () => {
    const lines = parseUnifiedDiff(`--- a
+++ b
@@ -1,2 +1,2 @@
-old line
+new line`);
    const hunks = groupIntoHunks(lines);
    const change = hunks.find(h => h.kind === "change");
    expect(change).toBeDefined();
    expect(change!.removed).toContain("old line");
    expect(change!.added).toContain("new line");
  });

  it("produces context-only hunks for @@ headers and context lines", () => {
    const lines = parseUnifiedDiff(`@@ -1,3 +1,3 @@
 context line`);
    const hunks = groupIntoHunks(lines);
    expect(hunks.some(h => h.kind === "context-only")).toBe(true);
  });

  it("multiple change blocks produce multiple change hunks", () => {
    const lines = parseUnifiedDiff(`--- a
+++ b
-line1
+LINE1
 context
-line2
+LINE2`);
    const hunks = groupIntoHunks(lines);
    const changes = hunks.filter(h => h.kind === "change");
    expect(changes.length).toBeGreaterThanOrEqual(2);
  });
});
