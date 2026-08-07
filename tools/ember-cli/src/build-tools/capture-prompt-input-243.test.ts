// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import xtermHeadless from "@xterm/headless";
import {
  buildCaptureReceipt,
  findClosedPromptRegion,
  redactHostPaths,
  visibleFrameLines,
  type CaptureReceiptInput,
  type CaptureStageInput,
} from "./capture-prompt-input-243.ts";

const { Terminal } = xtermHeadless;

function frame(width: number, status = "STATUS"): string {
  const content = width - 2;
  const row = (value: string) => `│${value.padEnd(content).slice(0, content)}│`;
  return [
    `╭${"─".repeat(content)}╮`,
    row(" ❯ hello"),
    row(` ${status}`),
    `╰${"─".repeat(content)}╯`,
    ...Array.from({ length: 20 }, () => " ".repeat(width)),
  ].join("\n") + "\n";
}

function stage(columns: number, index: number): CaptureStageInput {
  const frameText = frame(columns);
  return {
    columns,
    rows: 24,
    rawPath: `receipts/ember-cli/issue-243/live-resize-v1/stage-${index}-${columns}.raw`,
    privateRawLocator: `EMBER_PRIVATE_EVIDENCE:ember-cli/issue-243/live-resize-v1/stage-${index}-${columns}.raw`,
    privateRawBytes: Buffer.from(`raw-${index}`),
    redactions: [],
    framePath: `receipts/ember-cli/issue-243/live-resize-v1/stage-${index}-${columns}.frame.txt`,
    rawBytes: Buffer.from(`raw-${index}`),
    frameText,
    region: findClosedPromptRegion(frameText.replace(/\n$/, "").split("\n"), columns),
  };
}

test("visibleFrameLines clips stale xterm backing rows after a shrink", async () => {
  const terminal = new Terminal({ cols: 80, rows: 24, allowProposedApi: true });
  await new Promise<void>((done) => terminal.write("\u001b[?1049h" + "x".repeat(80), done));
  terminal.resize(40, 24);
  const lines = visibleFrameLines(terminal);
  expect(lines).toHaveLength(24);
  expect(lines.every((line) => line.length === 40)).toBe(true);
  terminal.dispose();
});

function valid(): CaptureReceiptInput {
  return {
    sourceCommit: "a".repeat(40),
    binaryArtifact: "tools/ember-cli/src/ember.exe",
    binarySha256Before: "b".repeat(64),
    binarySha256After: "b".repeat(64),
    rebuildBinarySha256: "b".repeat(64),
    builderExecutableBasename: "bun.exe",
    builderExecutableSha256Before: "c".repeat(64),
    builderExecutableSha256After: "c".repeat(64),
    builderVersion: "1.3.12",
    stages: [stage(80, 1), stage(40, 2), stage(80, 3)],
  };
}

describe("redactHostPaths", () => {
  test("replaces every supplied host path without changing byte length", () => {
    const source = Buffer.from(
      "\u001b]0;C:\\private-long-enough-long-enough\\ember.exe\u0007 cwd C:\\private-long-enough and C:\\private-long-enough-long-enough\\ember.exe",
      "utf8",
    );
    const result = redactHostPaths(source, ["C:\\private-long-enough", "C:\\private-long-enough-long-enough\\ember.exe"]);
    expect(result.publicBytes.byteLength).toBe(source.byteLength);
    expect(Buffer.from(result.publicBytes).toString("utf8")).not.toContain("C:\\private-long-enough");
    expect(result.redactions).toHaveLength(2);
  });

  test("redacts an unlisted absolute Windows path deterministically", () => {
    const source = Buffer.from("cwd D:\\other-private-long-enough\\ember");
    const result = redactHostPaths(source, ["C:\\private-long-enough"]);
    expect(result.publicBytes.byteLength).toBe(source.byteLength);
    expect(Buffer.from(result.publicBytes).toString("utf8")).not.toContain("D:\\other-private");
    expect(result.redactions).toHaveLength(1);
  });
  test("does not consume an adjacent terminal border glyph", () => {
    const source = Buffer.from(["B:", "M", "ember│"].join("\\"), "utf8");
    const result = redactHostPaths(source, []);
    const text = Buffer.from(result.publicBytes).toString("utf8");
    expect(result.publicBytes.byteLength).toBe(source.byteLength);
    expect(text.endsWith("│")).toBe(true);
  });
  test("redacts a short absolute path without changing byte length", () => {
    const source = Buffer.from("cwd C:\\x");
    const result = redactHostPaths(source, ["C:\\x"]);
    expect(result.publicBytes.byteLength).toBe(source.byteLength);
    expect(Buffer.from(result.publicBytes).toString("utf8")).not.toContain("C:\\x");
  });
});
describe("findClosedPromptRegion", () => {
  test("accepts one closed prompt/status region", () => {
    expect(findClosedPromptRegion(frame(40).replace(/\n$/, "").split("\n"), 40)).toEqual({
      top: 0,
      bottom: 3,
      contentColumns: 38,
    });
  });

  test("rejects a missing bottom edge", () => {
    const lines = frame(40).replace(/\n$/, "").split("\n");
    lines[3] = " ".repeat(40);
    expect(() => findClosedPromptRegion(lines, 40)).toThrow("closed prompt region");
  });

  test("rejects a missing side edge", () => {
    const lines = frame(40).replace(/\n$/, "").split("\n");
    lines[2] = ` ${lines[2]!.slice(1)}`;
    expect(() => findClosedPromptRegion(lines, 40)).toThrow("closed prompt region");
  });

  test("rejects terminal-width drift", () => {
    expect(() => findClosedPromptRegion(frame(40).replace(/\n$/, "").split("\n"), 80)).toThrow(
      "frame does not match terminal width",
    );
  });
});

describe("buildCaptureReceipt", () => {
  test("binds the exact 80x24, 40x24, 80x24 evidence", () => {
    const receipt = buildCaptureReceipt(valid());
    expect(receipt["result"]).toBe("PASS");
    expect(receipt["evidence_class"]).toBe("LIVE_COMPILED_BINARY_CONPTY");
    expect(receipt["goal_id"]).toBe("EMBER-02");
    expect(receipt["workstream_id"]).toBe("EMBER-02A");
    expect(receipt["binary"]).toEqual({
      artifact: "tools/ember-cli/src/ember.exe",
      sha256: "b".repeat(64),
      reproducible_rebuild: {
        source_commit: "a".repeat(40),
        sha256: "b".repeat(64),
        equals_captured_binary: true,
      },
    });
    expect(receipt["claim_boundary"]).toEqual({
      derived: [
        "captured binary equals an independent rebuild from source_commit",
        "independent rebuild used the recorded external builder executable",
      ],
      not_proven: [
        "source_commit review acceptance",
        "model, training, benchmark, or capability completion",
      ],
    });
    expect(receipt["builder"]).toEqual({
      executable_basename: "bun.exe",
      sha256: "c".repeat(64),
      version: "1.3.12",
      invocation: [
        "bun.exe",
        "build",
        "./entrypoints/main.ts",
        "--compile",
        "--outfile",
        "<owned-temp>/ember.exe",
        "--banner",
        "<derived-from-source-commit>",
        "--windows-title",
        "Ember",
        "--windows-publisher",
        "wordingone",
        "--windows-version",
        "0.1.0.0",
        "--windows-description",
        "Ember local AI laboratory",
      ],
    });
    const stages = receipt["stages"] as Array<Record<string, unknown>>;
    expect(stages[0]!["raw_private_exact"]).toEqual({
      logical_locator: "EMBER_PRIVATE_EVIDENCE:ember-cli/issue-243/live-resize-v1/stage-1-80.raw",
      bytes: 5,
      sha256: "e72e2581cffd8fef935b300f398a5a18bcb730d59ebd2fc267c5dfd7d5fe149e",
    });
  });

  test("rejects missing raw output", () => {
    const input = valid();
    input.stages[1]!.rawBytes = new Uint8Array();
    expect(() => buildCaptureReceipt(input)).toThrow("raw output is empty");
  });

  test("rejects missing private raw output", () => {
    const input = valid();
    input.stages[1]!.privateRawBytes = new Uint8Array();
    expect(() => buildCaptureReceipt(input)).toThrow("private raw output is empty");
  });
  test("rejects a missing frame", () => {
    const input = valid();
    input.stages[1]!.frameText = "";
    expect(() => buildCaptureReceipt(input)).toThrow("frame is empty");
  });

  test("rejects zero narrow content", () => {
    const input = valid();
    input.stages[1]!.region.contentColumns = 0;
    expect(() => buildCaptureReceipt(input)).toThrow("region does not match frame bytes");
  });

  test("rejects binary drift", () => {
    const input = valid();
    input.binarySha256After = "c".repeat(64);
    expect(() => buildCaptureReceipt(input)).toThrow("binary changed during capture");
  });

  test("rejects a stale or hand-patched binary that differs from an independent rebuild", () => {
    const input = valid();
    input.rebuildBinarySha256 = "d".repeat(64);
    expect(() => buildCaptureReceipt(input)).toThrow(
      "captured binary does not equal independent rebuild",
    );
  });

  test("rejects builder executable drift", () => {
    const input = valid();
    input.builderExecutableSha256After = "d".repeat(64);
    expect(() => buildCaptureReceipt(input)).toThrow("builder executable changed");
  });

  test("rejects incomplete builder identity", () => {
    const input = valid();
    input.builderVersion = "";
    expect(() => buildCaptureReceipt(input)).toThrow("builder version is invalid");
    input.builderVersion = "1.3.12";
    input.builderExecutableBasename = "../bun.exe";
    expect(() => buildCaptureReceipt(input)).toThrow("builder executable basename is invalid");
  });

  test("rejects a dimension other than 80, 40, 80", () => {
    const input = valid();
    input.stages[1] = stage(41, 2);
    expect(() => buildCaptureReceipt(input)).toThrow("capture dimensions");
  });

  test("rejects escaping paths in receipt artifacts", () => {
    const input = valid();
    input.binaryArtifact = "../escape/ember.exe";
    expect(() => buildCaptureReceipt(input)).toThrow("repository-relative");
  });
});
