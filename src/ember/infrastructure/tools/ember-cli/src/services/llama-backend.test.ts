// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { STOCK_KV_CHOICE, allowedKvChoices, calibrationKvChoices, parseDraftMtp, flashAttnArgs, kvChoicesFor, kvScale, parseHelp, parseKvTypes } from "./llama-backend.ts";

// Real `--help` excerpts (stdout) from the two binaries on the operator's machine.
const TURBO_HELP = `
-fa,   --flash-attn [on|off|auto]       set Flash Attention use ('on', 'off', or 'auto', default: 'auto')
                                        (env: LLAMA_ARG_FLASH_ATTN)
-ctk,  --cache-type-k TYPE              KV cache data type for K
                                        allowed values: f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1,
                                        turbo2, turbo3, turbo4
                                        (default: f16)
                                        (env: LLAMA_ARG_CACHE_TYPE_K)
-ctv,  --cache-type-v TYPE              KV cache data type for V
                                        allowed values: f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1,
                                        turbo2, turbo3, turbo4
-ub,   --ubatch-size N                  physical maximum batch size (default: 512)
-np,   --parallel N                     number of server slots (default: -1, -1 = auto)
--slot-save-path PATH                   path to save slot kv cache (default: disabled)
--chat-template-file JINJA_TEMPLATE_FILE
`;
const STOCK_HELP = `
-fa,   --flash-attn [on|off|auto]       set Flash Attention use
-ctk,  --cache-type-k TYPE              KV cache data type for K
                                        allowed values: f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1
                                        (default: f16)
                                        (env: LLAMA_ARG_CACHE_TYPE_K)
-ctv,  --cache-type-v TYPE              KV cache data type for V
`;

describe("backend detection from --help", () => {
  it("reads the wrapped allowed-values list of the turbo fork", () => {
    expect(parseKvTypes(TURBO_HELP)).toEqual(["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1", "turbo2", "turbo3", "turbo4"]);
    const caps = parseHelp(TURBO_HELP, "version: 8786 (32ec212a5)");
    expect(caps.turboTypes).toEqual(["turbo2", "turbo3", "turbo4"]);
    expect(caps).toMatchObject({ flashAttn: "value", slotSavePath: true, chatTemplateFile: true, ubatch: true, parallel: true, version: "version: 8786 (32ec212a5)" });
  });

  it("stock llama.cpp has no turbo types and falls back to q8_0", () => {
    const caps = parseHelp(STOCK_HELP);
    expect(caps.turboTypes).toEqual([]);
    expect(caps.kvTypes).toContain("q8_0");
    expect(kvChoicesFor(caps).map((c) => [c.k, c.v, c.scale])).toEqual([[STOCK_KV_CHOICE.k, STOCK_KV_CHOICE.v, STOCK_KV_CHOICE.scale]]);
  });

  it("unparseable help (or no probe) also falls back to q8_0", () => {
    expect(parseHelp("garbage").kvTypes).toEqual([]);
    expect(kvChoicesFor(parseHelp("garbage"))).toEqual([STOCK_KV_CHOICE]);
    expect(kvChoicesFor(null)).toEqual([STOCK_KV_CHOICE]);
  });

  it("detects the bare -fa flag dialect", () => {
    expect(parseHelp("-fa, --flash-attn           enable flash attention").flashAttn).toBe("flag");
    expect(flashAttnArgs({ flashAttn: "flag" }, true)).toEqual(["-fa"]);
    expect(flashAttnArgs({ flashAttn: "flag" }, false)).toEqual([]);
    expect(flashAttnArgs({ flashAttn: "value" }, false)).toEqual(["-fa", "off"]);
  });
});

describe("KV sizes and the quality floor", () => {
  it("derives scale from the compiled block structs: (bitsK + bitsV) / 32", () => {
    expect(kvScale("q8_0", "q8_0")).toBeCloseTo(0.53125, 5); // ~ the legacy 0.53 constant
    expect(kvScale("turbo3", "turbo3")).toBeCloseTo(3.5 / 16, 5); // 14 B / 32 elements
    expect(kvScale("turbo4", "turbo4")).toBeCloseTo(4.125 / 16, 5); // 66 B / 128 elements
    expect(kvScale("turbo3", "q8_0")).toBeCloseTo((3.5 + 8.5) / 32, 5);
    expect(() => kvScale("nope", "q8_0")).toThrow();
  });

  it("allows only documented uniform pairs, best first, and never turbo2", () => {
    const c = allowedKvChoices(parseHelp(TURBO_HELP));
    expect(c.map((x) => `${x.k}/${x.v}`)).toEqual(["q8_0/q8_0", "turbo4/turbo4", "turbo3/turbo3"]);
    expect(c.every((x) => x.evidence.length > 0)).toBe(true);
    expect(allowedKvChoices(parseHelp(TURBO_HELP), { includeF16: true })[0]!.k).toBe("f16");
  });
});

describe("draft-mtp detection and the long-context KV order", () => {
  const MTP_HELP = `
--spec-type [none|draft-simple|draft-eagle3|draft-mtp|ngram-simple]
                                        speculative decoding type (default: none)
                                        (env: LLAMA_ARG_SPEC_TYPE)
-ub,   --ubatch-size N                  physical maximum batch size (default: 512)
`;
  const WRAPPED_HELP = `
--spec-type TYPE                        speculative decoding type, one of: none,
                                        draft-simple, draft-eagle3,
                                        draft-mtp
-ub,   --ubatch-size N                  draft-mtp mentioned in a later option must not count
`;
  const OLD_HELP = `
--spec-type [none|ngram-simple|ngram-map-k]
                                        speculative decoding type (default: none)
-ub,   --ubatch-size N                  physical maximum batch size (default: 512)
--model-draft FNAME                     draft-mtp is only named here, in another option's text
`;

  it("lists draft-mtp from the --spec-type block, as turbo types are read from --cache-type-k", () => {
    expect(parseHelp(MTP_HELP).draftMtp).toBe(true);
    expect(parseDraftMtp(WRAPPED_HELP)).toBe(true);
  });

  it("a backend whose --spec-type lacks draft-mtp (or has no --spec-type) does not have it", () => {
    expect(parseHelp(OLD_HELP).draftMtp).toBe(false);
    expect(parseHelp(TURBO_HELP).draftMtp).toBe(false);
    expect(parseHelp("garbage").draftMtp).toBe(false);
  });

  it("q4_0 is tried first when the backend lists it, then the usual list; absent otherwise", () => {
    expect(kvScale("q4_0", "q4_0")).toBeCloseTo(9 / 32, 6);
    const turbo = parseHelp(TURBO_HELP);
    expect(calibrationKvChoices(turbo).map((c) => c.k)).toEqual(["q4_0", "q8_0", "turbo4", "turbo3"]);
    expect(calibrationKvChoices(parseHelp(STOCK_HELP), { includeF16: true }).map((c) => c.k)).toEqual(["q4_0", "f16", "q8_0"]);
    expect(calibrationKvChoices({ kvTypes: ["f16", "q8_0"] }).map((c) => c.k)).toEqual(["q8_0"]);
  });
});
