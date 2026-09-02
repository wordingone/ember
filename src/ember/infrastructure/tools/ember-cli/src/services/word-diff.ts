// services/word-diff.ts — Word-level diff for rendering edit tool results.
// Computes a token-level diff between old and new text so the renderer can
// colorize additions (green) and deletions (red) inline.
//
// Design: a simple Myers-like LCS over tokens (words + whitespace + punctuation
// as atomic units). The result is an array of spans that the component turns into
// colored Ink Text elements. No external dependencies.

// ---------------------------------------------------------------------------
// Token type and tokenizer
// ---------------------------------------------------------------------------

/** Split text into word/whitespace/punctuation tokens.
 *  Each token is an atomic unit for the diff; whitespace is preserved so
 *  the rendered output aligns with the original layout. */
export function tokenize(text: string): string[] {
  // Match: sequences of word chars OR sequences of whitespace OR single punctuation
  const tokens: string[] = [];
  const re = /\w+|\s+|[^\w\s]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    tokens.push(m[0]);
  }
  return tokens;
}

// ---------------------------------------------------------------------------
// LCS (longest common subsequence) over token arrays
// ---------------------------------------------------------------------------

/** Compute LCS lengths table (Wagner-Fischer). Returns (m+1) × (n+1) int array. */
function lcsTable(a: string[], b: string[]): number[][] {
  const m = a.length;
  const n = b.length;
  // Allocate row-major: table[i][j] = LCS length of a[0..i) and b[0..j)
  const table: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        table[i]![j] = table[i - 1]![j - 1]! + 1;
      } else {
        table[i]![j] = Math.max(table[i - 1]![j]!, table[i]![j - 1]!);
      }
    }
  }
  return table;
}

// ---------------------------------------------------------------------------
// Diff span output type
// ---------------------------------------------------------------------------

export type DiffSpanKind = "unchanged" | "added" | "removed";

export interface DiffSpan {
  kind: DiffSpanKind;
  text: string;
}

// ---------------------------------------------------------------------------
// Backtrack to produce diff spans
// ---------------------------------------------------------------------------

function backtrack(table: number[][], a: string[], b: string[], i: number, j: number): DiffSpan[] {
  if (i === 0 && j === 0) return [];
  if (i === 0) {
    return [...backtrack(table, a, b, 0, j - 1), { kind: "added",   text: b[j - 1]! }];
  }
  if (j === 0) {
    return [...backtrack(table, a, b, i - 1, 0), { kind: "removed", text: a[i - 1]! }];
  }
  if (a[i - 1] === b[j - 1]) {
    return [...backtrack(table, a, b, i - 1, j - 1), { kind: "unchanged", text: a[i - 1]! }];
  }
  if (table[i - 1]![j]! >= table[i]![j - 1]!) {
    return [...backtrack(table, a, b, i - 1, j), { kind: "removed", text: a[i - 1]! }];
  }
  return [...backtrack(table, a, b, i, j - 1), { kind: "added", text: b[j - 1]! }];
}

/** Core word-level diff.
 *  @param oldText The old (before) text.
 *  @param newText The new (after) text.
 *  @returns Array of DiffSpan in order, covering old text completely. */
export function wordDiff(oldText: string, newText: string): DiffSpan[] {
  const a = tokenize(oldText);
  const b = tokenize(newText);

  // Short-circuit: identical
  if (oldText === newText) {
    return [{ kind: "unchanged", text: oldText }];
  }

  // Stack-safe: guard large inputs (>512 tokens per side) by falling back to
  // a single-span changed diff to avoid O(N²) stack depth. For terminal display
  // this is fine — large diffs should be line-level anyway.
  if (a.length > 512 || b.length > 512) {
    return [
      { kind: "removed", text: oldText },
      { kind: "added",   text: newText },
    ];
  }

  const table = lcsTable(a, b);
  return backtrack(table, a, b, a.length, b.length);
}

// ---------------------------------------------------------------------------
// Unified diff parser — produces hunk records for line-level + word-level diffs
// ---------------------------------------------------------------------------

export interface DiffLine {
  kind: "header" | "hunk" | "removed" | "added" | "context";
  text: string;
}

/** Parse a unified diff string into typed lines.
 *  Returns an empty array if the input is not a recognizable unified diff. */
export function parseUnifiedDiff(content: string): DiffLine[] {
  const lines = content.split("\n");
  const result: DiffLine[] = [];

  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith("--- ") || line.startsWith("+++ ")) {
      result.push({ kind: "header", text: line });
    } else if (line.startsWith("@@ ")) {
      result.push({ kind: "hunk", text: line });
    } else if (line.startsWith("-")) {
      result.push({ kind: "removed", text: line.slice(1) });
    } else if (line.startsWith("+")) {
      result.push({ kind: "added",   text: line.slice(1) });
    } else {
      result.push({ kind: "context", text: line.startsWith(" ") ? line.slice(1) : line });
    }
  }

  return result;
}

/** Returns true when the content string looks like a unified diff. */
export function isUnifiedDiff(content: string): boolean {
  return /^(---|\+\+\+|@@\s)/.test(content.trimStart());
}

// ---------------------------------------------------------------------------
// Merge adjacent removed/added hunks for word-level highlighting
// ---------------------------------------------------------------------------

export interface DiffHunk {
  removed: string[];
  added:   string[];
  context: string[];
  kind: "change" | "context-only";
}

/** Group parsed diff lines into hunks suitable for word-level rendering.
 *  Each returned hunk is either a change (has removed + added) or a context block. */
export function groupIntoHunks(lines: DiffLine[]): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  let removed: string[] = [];
  let added:   string[] = [];

  function flush() {
    if (removed.length > 0 || added.length > 0) {
      hunks.push({ removed, added, context: [], kind: "change" });
      removed = [];
      added   = [];
    }
  }

  for (const line of lines) {
    if (line.kind === "removed") {
      removed.push(line.text);
    } else if (line.kind === "added") {
      added.push(line.text);
    } else {
      flush();
      if (line.kind === "context") {
        // Append to the last context hunk or create a new one
        const last = hunks[hunks.length - 1];
        if (last && last.kind === "context-only") {
          last.context.push(line.text);
        } else {
          hunks.push({ removed: [], added: [], context: [line.text], kind: "context-only" });
        }
      }
      // header / hunk lines — emit as context-only with hunk header text
      if (line.kind === "hunk" || line.kind === "header") {
        hunks.push({ removed: [], added: [], context: [line.text], kind: "context-only" });
      }
    }
  }
  flush();
  return hunks;
}
