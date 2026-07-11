// components/tool-result-renderers.test.ts — AC tests for large-output truncation.
//
// AC10a: isLargeOutput — returns true only when line count > LARGE_OUTPUT_LINE_THRESHOLD
// AC10b: splitLargeOutput — hiddenCount + tail correctness
// AC10c: signal constants — preserve exact values
// AC10d: classifyToolResult — priority order for cancel/reject/error/success

import { describe, it, expect } from "bun:test";
import {
  LARGE_OUTPUT_LINE_THRESHOLD,
  LARGE_OUTPUT_TAIL_LINES,
  isLargeOutput,
  splitLargeOutput,
  CANCEL_MESSAGE,
  REJECT_MESSAGE,
  INTERRUPT_MESSAGE,
  classifyToolResult,
  contentToString,
  summarizeToolResultLine,
  DIGEST_MAX_CHARS,
  UserToolSuccessMessage,
  type ToolResultContent,
} from "./tool-result-renderers.ts";
import type { Tool } from "../core/tool-interface.ts";

function ser(el: unknown): string {
  return JSON.stringify(el);
}

// ---------------------------------------------------------------------------
// AC10a — isLargeOutput
// ---------------------------------------------------------------------------

describe("AC10a: isLargeOutput — threshold at LARGE_OUTPUT_LINE_THRESHOLD lines", () => {
  it("returns false for empty text", () => {
    expect(isLargeOutput("")).toBe(false);
  });

  it("returns false when line count equals threshold exactly", () => {
    // LARGE_OUTPUT_LINE_THRESHOLD newlines = LARGE_OUTPUT_LINE_THRESHOLD+1 lines
    // but isLargeOutput triggers on count > threshold newlines
    const lines = Array.from({ length: LARGE_OUTPUT_LINE_THRESHOLD }, (_, i) => `line ${i}`);
    expect(isLargeOutput(lines.join("\n"))).toBe(false);
  });

  it("returns false for a single-line string", () => {
    expect(isLargeOutput("single line of text")).toBe(false);
  });

  it("returns true when line count exceeds LARGE_OUTPUT_LINE_THRESHOLD", () => {
    const lines = Array.from({ length: LARGE_OUTPUT_LINE_THRESHOLD + 1 }, (_, i) => `line ${i}`);
    expect(isLargeOutput(lines.join("\n"))).toBe(true);
  });

  it("returns true for a 55-line output (M10 battery fixture)", () => {
    const lines = Array.from({ length: 55 }, (_, i) => `component-${String(i + 1).padStart(3, "0")}: value`);
    expect(isLargeOutput(lines.join("\n"))).toBe(true);
  });

  it("LARGE_OUTPUT_LINE_THRESHOLD is exported and positive", () => {
    expect(LARGE_OUTPUT_LINE_THRESHOLD).toBeGreaterThan(0);
  });

  it("LARGE_OUTPUT_TAIL_LINES is exported and positive", () => {
    expect(LARGE_OUTPUT_TAIL_LINES).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC10b — splitLargeOutput
// ---------------------------------------------------------------------------

describe("AC10b: splitLargeOutput — tail + hiddenCount", () => {
  it("returns hiddenCount=0 and full text when below threshold", () => {
    const text = "short\ntext";
    const result = splitLargeOutput(text);
    expect(result.hiddenCount).toBe(0);
    expect(result.tail).toBe(text);
  });

  it("for 55-line input: hiddenCount = 55 - LARGE_OUTPUT_TAIL_LINES", () => {
    const lines = Array.from({ length: 55 }, (_, i) => `line-${i + 1}`);
    const { hiddenCount, tail } = splitLargeOutput(lines.join("\n"));
    expect(hiddenCount).toBe(55 - LARGE_OUTPUT_TAIL_LINES);
  });

  it("tail contains exactly LARGE_OUTPUT_TAIL_LINES lines for large input", () => {
    const lines = Array.from({ length: 55 }, (_, i) => `line-${i + 1}`);
    const { tail } = splitLargeOutput(lines.join("\n"));
    const tailLines = tail.split("\n");
    expect(tailLines.length).toBe(LARGE_OUTPUT_TAIL_LINES);
  });

  it("tail contains the LAST lines of the input (not the first)", () => {
    const lines = Array.from({ length: 55 }, (_, i) => `line-${i + 1}`);
    const { tail } = splitLargeOutput(lines.join("\n"));
    // Last line of input should be last line of tail
    expect(tail.split("\n").at(-1)).toBe("line-55");
    // First line of tail should be line-(55-LARGE_OUTPUT_TAIL_LINES+1)
    const firstTailLineNumber = 55 - LARGE_OUTPUT_TAIL_LINES + 1;
    expect(tail.split("\n")[0]).toBe(`line-${firstTailLineNumber}`);
  });

  it("for M10 component-NNN fixture: tail contains ≥20 component-NNN lines", () => {
    const lines = Array.from({ length: 55 }, (_, i) =>
      `component-${String(i + 1).padStart(3, "0")}: value`,
    );
    const { tail } = splitLargeOutput(lines.join("\n"));
    const componentLineCount = tail.split("\n").filter(l => /^component-\d+/.test(l)).length;
    expect(componentLineCount).toBeGreaterThanOrEqual(20);
  });

  it("hiddenCount is non-negative for any input", () => {
    const { hiddenCount } = splitLargeOutput("a\nb");
    expect(hiddenCount).toBeGreaterThanOrEqual(0);
  });
});

// ---------------------------------------------------------------------------
// AC10c — signal constants
// ---------------------------------------------------------------------------

describe("AC10c: signal constants", () => {
  it("CANCEL_MESSAGE is the expected sentinel string", () => {
    expect(CANCEL_MESSAGE).toBe("This operation has been canceled by the user.");
  });

  it("REJECT_MESSAGE is the expected sentinel string", () => {
    expect(REJECT_MESSAGE).toBe("<tool_use_rejected>");
  });

  it("INTERRUPT_MESSAGE is the expected sentinel string", () => {
    expect(INTERRUPT_MESSAGE).toBe("<interrupted>");
  });
});

// ---------------------------------------------------------------------------
// AC10d — classifyToolResult priority order
// ---------------------------------------------------------------------------

function mkResult(content: string, is_error = false): ToolResultContent {
  return { type: "tool_result", tool_use_id: "test", content, is_error };
}

describe("AC10d: classifyToolResult — priority order", () => {
  it("CANCEL_MESSAGE → 'canceled'", () => {
    expect(classifyToolResult(mkResult(CANCEL_MESSAGE))).toBe("canceled");
  });

  it("REJECT_MESSAGE → 'rejected'", () => {
    expect(classifyToolResult(mkResult(REJECT_MESSAGE))).toBe("rejected");
  });

  it("INTERRUPT_MESSAGE → 'rejected'", () => {
    expect(classifyToolResult(mkResult(INTERRUPT_MESSAGE))).toBe("rejected");
  });

  it("is_error=true with normal text → 'error'", () => {
    expect(classifyToolResult(mkResult("some error text", true))).toBe("error");
  });

  it("plain success text → 'success'", () => {
    expect(classifyToolResult(mkResult("File written successfully."))).toBe("success");
  });

  it("content array is stringified before classification", () => {
    const result: ToolResultContent = {
      type:        "tool_result",
      tool_use_id: "t1",
      content:     [{ type: "text", text: CANCEL_MESSAGE }],
    };
    expect(classifyToolResult(result)).toBe("canceled");
  });
});

// ---------------------------------------------------------------------------
// AC10e — contentToString
// ---------------------------------------------------------------------------

describe("AC10e: contentToString", () => {
  it("string input → same string", () => {
    expect(contentToString("hello")).toBe("hello");
  });

  it("array of text blocks → joined text", () => {
    const blocks = [
      { type: "text", text: "hello " },
      { type: "text", text: "world" },
    ];
    expect(contentToString(blocks)).toBe("hello world");
  });

  it("non-text blocks in array are filtered out", () => {
    const blocks = [
      { type: "image", text: "ignored" },
      { type: "text", text: "shown" },
    ];
    expect(contentToString(blocks)).toBe("shown");
  });

  it("empty array → empty string", () => {
    expect(contentToString([])).toBe("");
  });
});

// ---------------------------------------------------------------------------
// #240 — summarizeToolResultLine: compact one-line digest, never raw JSON
// ---------------------------------------------------------------------------

describe("#240: summarizeToolResultLine — one-line digest, no raw JSON syntax", () => {
  it("a short single-line result is its own digest (not truncated)", () => {
    const { digest, truncated } = summarizeToolResultLine("command output here");
    expect(digest).toBe("command output here");
    expect(truncated).toBe(false);
  });

  it("truncates a single line longer than DIGEST_MAX_CHARS with an ellipsis", () => {
    const long = "x".repeat(DIGEST_MAX_CHARS + 50);
    const { digest, truncated } = summarizeToolResultLine(long);
    expect(digest.length).toBeLessThanOrEqual(DIGEST_MAX_CHARS);
    expect(digest.endsWith("…")).toBe(true);
    expect(truncated).toBe(true);
  });

  it("multi-line text digests to the first line and reports truncated=true", () => {
    const { digest, truncated } = summarizeToolResultLine("line one\nline two\nline three");
    expect(digest).toBe("line one");
    expect(truncated).toBe(true);
  });

  it("empty text gets a non-empty placeholder digest", () => {
    const { digest } = summarizeToolResultLine("");
    expect(digest.length).toBeGreaterThan(0);
  });

  it("a pretty-printed JSON object never surfaces '{' as the digest -- structural summary instead", () => {
    const text = JSON.stringify({ stdout: "ok", exitCode: 0, extra: "x" }, null, 2);
    const { digest, truncated } = summarizeToolResultLine(text);
    expect(digest).not.toBe("{");
    expect(digest).not.toContain("{\n");
    expect(digest).toContain("3 keys");
    expect(truncated).toBe(true);
  });

  it("a pretty-printed JSON array never surfaces '[' as the digest -- structural summary instead", () => {
    const text = JSON.stringify(["a.ts", "b.ts"], null, 2);
    const { digest, truncated } = summarizeToolResultLine(text);
    expect(digest).not.toBe("[");
    expect(digest).toContain("2 items");
    expect(truncated).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// #240 — UserToolSuccessMessage: compact-by-default, full text behind isExpanded
// ---------------------------------------------------------------------------

describe("#240: UserToolSuccessMessage — glyph + tool name + digest, raw payload behind expand", () => {
  const bashLikeTool = {
    name: "Bash",
    userFacingName: () => "Bash",
  } as unknown as Tool;

  it("renders the tool name in the header when a tool is supplied", () => {
    const result: ToolResultContent = { type: "tool_result", tool_use_id: "t1", content: "ok" };
    const el = UserToolSuccessMessage({ result, tool: bashLikeTool });
    expect(ser(el)).toContain("Bash");
  });

  it("collapses a multi-line result to its first-line digest by default, with an expand hint", () => {
    const content = Array.from({ length: 5 }, (_, i) => `line ${i}`).join("\n");
    const result: ToolResultContent = { type: "tool_result", tool_use_id: "t2", content };
    const el = UserToolSuccessMessage({ result });
    const s = ser(el);
    expect(s).toContain("line 0");
    expect(s).not.toContain("line 4");
    expect(s).toContain("Ctrl+O to expand");
  });

  it("shows the full multi-line result when isExpanded is true", () => {
    const content = Array.from({ length: 5 }, (_, i) => `line ${i}`).join("\n");
    const result: ToolResultContent = { type: "tool_result", tool_use_id: "t3", content };
    const el = UserToolSuccessMessage({ result, isExpanded: true });
    const s = ser(el);
    expect(s).toContain("line 0");
    expect(s).toContain("line 4");
  });

  it("never renders a bare '{' or '[' for a structured JSON tool result, even collapsed", () => {
    const content = JSON.stringify({ filenames: ["a.ts", "b.ts"], numFiles: 2, extra: "x", more: "y" });
    const result: ToolResultContent = { type: "tool_result", tool_use_id: "t4", content };
    const el = UserToolSuccessMessage({ result });
    const s = ser(el);
    // formatToolResultForDisplay recognizes the {filenames,numFiles} shape and returns the
    // plain filename list -- so this must render as readable text, never the raw wire JSON.
    expect(s).not.toContain('"filenames"');
    expect(s).toContain("a.ts");
  });
});
