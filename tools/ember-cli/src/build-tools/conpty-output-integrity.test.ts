// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Issue #354: the compiled-product ConPTY gate must reject transport-injected NUL bytes.
import { describe, expect, test } from "bun:test";
import { requireNulFreeConptyOutput } from "./conpty-output-integrity.ts";

describe("ConPTY raw-output integrity", () => {
  test("accepts an ordinary ANSI stream and binds its byte count", () => {
    expect(requireNulFreeConptyOutput("\x1b[2JEmber ✓\r\n")).toEqual({
      raw_bytes_utf8: Buffer.byteLength("\x1b[2JEmber ✓\r\n"),
      raw_nul_count: 0,
    });
  });

  test("refuses transport-injected NUL bytes with count and first offset", () => {
    expect(() => requireNulFreeConptyOutput("abc\0def\0")).toThrow(
      "CONPTY_RAW_NUL_INJECTION count=2 first_index=3",
    );
  });
});
