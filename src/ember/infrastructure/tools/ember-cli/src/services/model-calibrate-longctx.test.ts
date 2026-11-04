// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #2371: calibrate defaults to the model's full native context, q4_0 KV and MTP speculative
// decoding, gated by a long-context needle check.  Everything here runs on injected fakes:
// no llama-server is started and no hardware is touched.

import { describe, expect, it } from "bun:test";

import { calibrationKvChoices, parseHelp } from "./llama-backend.ts";
import { parseGgufMeta } from "./gguf-meta.ts";
import {
  RECALL_FRACTION, applyCalibration, buildNeedlePrompt, buildReceipt, ctxLadderFor, makeCandidate, mtpAvailable, needleFor, runRecallCheck,
  searchConfigs, serverArgsFor, type Candidate, type CandidateResult, type RecallDeps, type RecallResult,
} from "./model-calibrate.ts";
import { parsePullArgs, _internals } from "./model-pull.ts";

const GiB = 1024 ** 3;
const TOTAL = 24 * GiB;
const HELP_MTP = [
  "-fa, --flash-attn [on|off|auto]",
  "-ctk, --cache-type-k TYPE",
  "  allowed values: f16, q8_0, q4_0, turbo3, turbo4",
  "  (default: f16)",
  "--spec-type [none|draft-simple|draft-eagle3|draft-mtp]",
  "  speculative decoding type",
  "-ub, --ubatch-size N",
].join("\n");
const HELP_NO_MTP = HELP_MTP.replace("|draft-mtp", "");
const capsMtp = parseHelp(HELP_MTP);
const capsPlain = parseHelp(HELP_NO_MTP);

function u32(n: number): Buffer { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; }
function str(s: string): Buffer { const b = Buffer.from(s, "utf-8"); const l = Buffer.alloc(8); l.writeBigUInt64LE(BigInt(b.length)); return Buffer.concat([l, b]); }
function kv(key: string, type: number, value: Buffer): Buffer { return Buffer.concat([str(key), u32(type), value]); }
function gguf(entries: Buffer[]): Buffer {
  const head = Buffer.alloc(24); head.write("GGUF", 0, "ascii"); head.writeUInt32LE(3, 4); head.writeBigUInt64LE(0n, 8); head.writeBigUInt64LE(BigInt(entries.length), 16);
  return Buffer.concat([head, ...entries]);
}
const metaWithHead = parseGgufMeta(gguf([kv("general.architecture", 8, str("qwen35")), kv("qwen35.context_length", 4, u32(262144)), kv("qwen35.nextn_predict_layers", 4, u32(1))]));
const metaNoHead = parseGgufMeta(gguf([kv("general.architecture", 8, str("qwen3")), kv("qwen3.context_length", 4, u32(40960))]));

const passed = (ctx: number): RecallResult => ({ status: "passed", ctx, promptTokens: Math.floor(ctx * 0.9), fractionOfCtx: 0.9, needle: "NX-TEST", answer: "NX-TEST", seconds: 1 });
const failed = (ctx: number): RecallResult => ({ status: "failed", ctx, promptTokens: Math.floor(ctx * 0.9), fractionOfCtx: 0.9, needle: "NX-TEST", answer: "?", seconds: 1, error: "needle NX-TEST not recalled" });

function measured(c: Candidate, o: { recall?: boolean } | undefined, speed: (c: Candidate) => number, recall: (c: Candidate) => RecallResult, peakGiB = 21): CandidateResult {
  return {
    candidate: c, ok: true, coherent: true, ppTps: 3000, tgTps: speed(c), peakVramBytes: peakGiB * GiB, headroomBytes: TOTAL - peakGiB * GiB,
    draftAcceptance: c.mtp ? 0.87 : null, ...(o?.recall ? { recall: recall(c) } : {}), at: "t",
  };
}

describe("MTP flag (requirements 2, 3, 7)", () => {
  it("serverArgs carry --spec-type draft-mtp only for an MTP candidate", () => {
    const on = makeCandidate({ kvK: "q4_0", kvV: "q4_0", ctx: 262144, ubatch: 512, batch: 2048, flashAttn: true, mtp: true });
    const off = makeCandidate({ kvK: "q4_0", kvV: "q4_0", ctx: 262144, ubatch: 512, batch: 2048, flashAttn: true });
    expect(serverArgsFor(on, capsMtp)).toEqual(["-ngl", "999", "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-ub", "512", "-b", "2048", "--parallel", "1", "--spec-type", "draft-mtp"]);
    expect(serverArgsFor(off, capsMtp)).not.toContain("--spec-type");
    expect(on.id).toContain("_mtp");
    expect(off.id).not.toContain("mtp");
  });

  it("MTP needs BOTH the GGUF head and the backend's draft-mtp", () => {
    expect(mtpAvailable(metaWithHead, capsMtp)).toBe(true);
    expect(mtpAvailable(metaWithHead, capsPlain)).toBe(false);
    expect(mtpAvailable(metaNoHead, capsMtp)).toBe(false);
    expect(mtpAvailable(metaWithHead, null)).toBe(false);
  });
});

describe("context steps (requirement 3)", () => {
  const base = [65536, 49152, 32768, 24576, 16384, 8192];
  it("native maximum, then 196608, 131072, then the existing smaller steps", () => {
    expect(ctxLadderFor(262144, base)).toEqual([262144, 196608, 131072, 65536, 49152, 32768, 24576, 16384, 8192]);
  });
  it("never offers a context above the model's native window", () => {
    expect(ctxLadderFor(40960, base)).toEqual([40960, 32768, 24576, 16384, 8192]);
    expect(ctxLadderFor(131072, base)[0]).toBe(131072);
  });
  it("without a native figure the ordinary ladder is used", () => {
    expect(ctxLadderFor(null, base)).toEqual(base);
  });
});

describe("the grid and the pick (requirements 3, 4)", () => {
  const input = (over: Partial<Parameters<typeof searchConfigs>[0]> = {}): Parameters<typeof searchConfigs>[0] => ({
    caps: capsMtp, kvChoices: calibrationKvChoices(capsMtp, { includeF16: true }), weightsBytes: 16 * GiB, extraBytes: 1 * GiB, kvBytesPerToken: 65536,
    startCtx: 262144, ctxLadder: ctxLadderFor(262144, [65536, 49152, 32768]), totalVramBytes: TOTAL, log: () => {}, run: async () => { throw new Error("run not set"); }, ...over,
  });

  it("a 24 GB card takes 262144 context, q4_0 KV and draft-mtp, and never launches what cannot fit", async () => {
    const launched: Candidate[] = [];
    const out = await searchConfigs(input({
      mtp: true, verifyRecall: true,
      run: async (c, o) => { launched.push(c); return measured(c, o, (x) => (x.kvK === "q4_0" && x.mtp ? 95 : 20), (x) => passed(x.ctx)); },
    }));
    expect(launched[0]).toMatchObject({ kvK: "q4_0", ctx: 262144, mtp: true });
    // q8_0 / f16 at 262144 are over the VRAM budget by estimate: skipped, not launched
    expect(launched.some((c) => c.ctx === 262144 && (c.kvK === "q8_0" || c.kvK === "f16"))).toBe(false);
    expect(out.results.find((r) => r.candidate.ctx === 262144 && r.candidate.kvK === "q8_0")?.error).toContain("exceeds budget");
    expect(Math.max(...launched.map((c) => c.ctx))).toBe(262144);
    expect(out.selected?.candidate).toMatchObject({ kvK: "q4_0", kvV: "q4_0", ctx: 262144, mtp: true });
    expect(out.selected!.tgTps).toBeGreaterThanOrEqual(80);
    expect(out.selected!.recall?.status).toBe("passed");
    expect(serverArgsFor(out.selected!.candidate, capsMtp)).toContain("draft-mtp");
  });

  it("without an MTP head no candidate is ever launched with --spec-type", async () => {
    const launched: Candidate[] = [];
    const out = await searchConfigs(input({
      mtp: mtpAvailable(metaNoHead, capsMtp), verifyRecall: true,
      run: async (c, o) => { launched.push(c); return measured(c, o, () => 40, (x) => passed(x.ctx)); },
    }));
    expect(launched.length).toBeGreaterThan(0);
    expect(launched.every((c) => !c.mtp && !serverArgsFor(c, capsMtp).includes("--spec-type"))).toBe(true);
    const receipt = buildReceipt(out, capsMtp, TOTAL, "/r.json")!;
    expect(receipt.specType).toBeNull();
    expect(applyCalibration({}, receipt, capsMtp)["serverArgs"]).not.toContain("--spec-type");
  });

  it("a candidate that will not load with MTP is retried at the same KV without it", async () => {
    const out = await searchConfigs(input({
      mtp: true, verifyRecall: false, startCtx: 65536, ctxLadder: [65536],
      run: async (c, o) => (c.mtp
        ? { candidate: c, ok: false, error: "llama-server exited during load", at: "t" }
        : measured(c, o, (x) => (x.kvK === "q4_0" ? 30 : 10), (x) => passed(x.ctx), 14)),
    }));
    expect(out.selected?.candidate.mtp).toBeUndefined();
    expect(out.selected?.candidate.kvK).toBe("q4_0");
    expect(serverArgsFor(out.selected!.candidate, capsMtp)).not.toContain("--spec-type");
  });

  it("a candidate that fails the needle is dropped and the next best KV type is verified", async () => {
    const recallCalls: string[] = [];
    const out = await searchConfigs(input({
      mtp: true, verifyRecall: true, weightsBytes: 8 * GiB, startCtx: 131072, ctxLadder: [131072, 65536],
      run: async (c, o) => {
        if (o?.recall) recallCalls.push(`${c.kvK}@${c.ctx}`);
        return measured(c, o, (x) => (x.kvK === "q4_0" ? 95 : x.kvK === "q8_0" ? 50 : 10), (x) => (x.kvK === "q4_0" ? failed(x.ctx) : passed(x.ctx)), 15);
      },
    }));
    expect(out.selected?.candidate).toMatchObject({ kvK: "q8_0", ctx: 131072 });
    expect(out.selected?.recall?.status).toBe("passed");
    // q4_0 was verified once (its batch-size siblings are covered by that verdict), then q8_0
    expect(recallCalls.filter((x) => x.startsWith("q4_0@131072"))).toHaveLength(1);
    expect(out.results.some((r) => r.candidate.kvK === "q4_0" && r.recall?.status === "failed")).toBe(true);
  });

  it("when nothing at a context passes recall, the next context down is tried", async () => {
    const recallCtxs = new Set<number>();
    const out = await searchConfigs(input({
      mtp: true, verifyRecall: true, weightsBytes: 6 * GiB, startCtx: 262144, ctxLadder: ctxLadderFor(262144, [65536, 49152, 32768]),
      run: async (c, o) => { if (o?.recall) recallCtxs.add(c.ctx); return measured(c, o, () => 80, (x) => (x.ctx >= 131072 ? failed(x.ctx) : passed(x.ctx)), 15); },
    }));
    expect(out.selected?.candidate.ctx).toBe(65536);
    expect([...recallCtxs].sort((a, b) => b - a)).toEqual([262144, 196608, 131072, 65536]);
  });

  it("a small card walks past every context the VRAM estimate rules out (skips are free) down to one that fits", async () => {
    const launched: number[] = [];
    const out = await searchConfigs(input({
      caps: capsPlain, kvChoices: calibrationKvChoices(parseHelp("-ctk, --cache-type-k TYPE\n  allowed values: f16, q8_0\n  (default: f16)\n")), // q8_0 only
      totalVramBytes: 8 * GiB, weightsBytes: 4.7 * GiB, extraBytes: 0, kvBytesPerToken: 147456, startCtx: 262144,
      ctxLadder: ctxLadderFor(262144, _internals.CTX_LADDER), verifyRecall: false,
      run: async (c, o) => { launched.push(c.ctx); return measured(c, o, () => 40, (x) => passed(x.ctx), 6.5); },
    }));
    // 262144 down to 24576 are all over budget by estimate: eight context steps, none launched
    expect(Math.max(...launched)).toBe(16384);
    expect(out.selected?.candidate.ctx).toBe(16384);
  });

  describe("headroom (lead decision 2026-11-03)", () => {
    // peak GiB as a function of the physical batch: a smaller -ub shrinks the compute buffer
    const peakFor = (c: Candidate, big: number, small: number) => (c.ubatch <= 256 ? small : big);
    const runWith = (launched: Candidate[], big: number, small: number, tgFor: (c0: Candidate) => number = (c) => (c.kvK === "q4_0" ? 95 : 20)) =>
      async (c: Candidate, o?: { recall?: boolean }) => { launched.push(c); return measured(c, o, tgFor, (x) => passed(x.ctx), peakFor(c, big, small)); };

    it("a native-context candidate that fails only on headroom is retried with -ub 256 and keeps 262144", async () => {
      const launched: Candidate[] = [];
      // 24 GiB card: 23.5 GiB used at -ub 512 leaves 0.5 GiB (< 1 GiB gate); 22.6 GiB at -ub 256 leaves 1.4 GiB
      const out = await searchConfigs(input({ mtp: true, verifyRecall: true, run: runWith(launched, 23.5, 22.6) }));
      const at262 = launched.filter((c) => c.ctx === 262144 && c.kvK === "q4_0");
      expect(at262.map((c) => c.ubatch).slice(0, 2)).toEqual([512, 256]);
      expect(launched.every((c) => c.ctx === 262144)).toBe(true); // never stepped down
      expect(out.selected?.candidate).toMatchObject({ ctx: 262144, kvK: "q4_0", ubatch: 256, mtp: true });
      expect(serverArgsFor(out.selected!.candidate, capsMtp)).toEqual(expect.arrayContaining(["-ub", "256"]));
      // a winner that only fit with the reduced buffer is not pushed back up to -ub 1024/2048
      expect(launched.some((c) => c.ubatch > 512)).toBe(false);
      expect(out.selected?.recall?.status).toBe("passed");
    });

    it("when -ub 256 still leaves too little, the context steps down", async () => {
      const launched: Candidate[] = [];
      const out = await searchConfigs(input({
        mtp: true, verifyRecall: false,
        run: async (c, o) => { launched.push(c); return measured(c, o, (x) => (x.kvK === "q4_0" ? 95 : 20), (x) => passed(x.ctx), c.ctx === 262144 ? (c.ubatch <= 256 ? 23.3 : 23.6) : 20); },
      }));
      expect(launched.filter((c) => c.ctx === 262144 && c.kvK === "q4_0").map((c) => c.ubatch)).toEqual([512, 256]);
      expect(out.selected?.candidate.ctx).toBe(196608);
    });

    it("a candidate that fits at the default -ub is not retried", async () => {
      const launched: Candidate[] = [];
      await searchConfigs(input({ mtp: true, verifyRecall: false, run: runWith(launched, 21, 20) }));
      expect(launched.some((c) => c.ubatch === 256)).toBe(false);
    });

    it("the headroom is a parameter, enforced everywhere it was 1 GiB, and recorded in the receipt", async () => {
      const launched: Candidate[] = [];
      // 23.5 GiB peak on 24 GiB leaves 512 MiB: rejected at the default gate, accepted at 400 MiB with no retry
      const out = await searchConfigs(input({ mtp: true, verifyRecall: false, headroomBytes: 400 * 1024 ** 2, run: runWith(launched, 23.5, 22.6) }));
      expect(out.selected?.candidate).toMatchObject({ ctx: 262144, ubatch: 512 });
      expect(launched.some((c) => c.ubatch === 256)).toBe(false);
      const receipt = buildReceipt(out, capsMtp, TOTAL, "/r.json")!;
      expect(receipt.headroomRequiredBytes).toBe(400 * 1024 ** 2);
      expect(receipt.rule).toContain("400 MiB");
      // default is unchanged
      const def = await searchConfigs(input({ mtp: true, verifyRecall: false, run: runWith([], 21, 20) }));
      expect(buildReceipt(def, capsMtp, TOTAL, "/r.json")!.headroomRequiredBytes).toBe(1024 ** 3);
    });

    it("--headroom-mib is parsed and range-checked", () => {
      expect(parsePullArgs(["--calibrate", "--headroom-mib", "512"]).headroomMib).toBe(512);
      expect(parsePullArgs(["--calibrate"]).headroomMib).toBeUndefined();
      expect(() => parsePullArgs(["--calibrate", "--headroom-mib", "abc"])).toThrow("--headroom-mib");
      expect(() => parsePullArgs(["--calibrate", "--headroom-mib"])).toThrow("--headroom-mib");
    });
  });

  it("recall can be skipped: the check never runs and the receipt says so", async () => {
    let recallRuns = 0;
    const out = await searchConfigs(input({
      mtp: true, verifyRecall: false, startCtx: 65536, ctxLadder: [65536],
      run: async (c, o) => { if (o?.recall) recallRuns++; return measured(c, o, () => 90, (x) => passed(x.ctx), 14); },
    }));
    expect(recallRuns).toBe(0);
    expect(out.selected).not.toBeNull();
    expect(buildReceipt(out, capsMtp, TOTAL, "/r.json")!.recall).toEqual({ status: "skipped" });
  });
});

describe("the recall check (requirement 4)", () => {
  const WORDS_TO_TOKENS = 1.6; // the fake tokenizer disagrees with filler()'s own 1.3 guess on purpose
  const tokenizer = (text: string) => Math.round(text.split(/\s+/).length * WORDS_TO_TOKENS);
  function deps(answer: (prompt: string) => string, extra: Partial<RecallDeps> = {}): { d: RecallDeps; prompts: string[] } {
    const prompts: string[] = [];
    return {
      prompts,
      d: {
        tokenize: async (t) => tokenizer(t),
        ask: async (prompt) => { prompts.push(prompt); return { ok: true, status: 200, text: answer(prompt), reasoning: "", promptTokens: tokenizer(prompt) }; },
        ...extra,
      },
    };
  }
  const needleIn = (prompt: string) => prompt.match(/NX-[0-9A-F]{8}/)![0];

  it("sizes the prompt to ~90% of the context by the server's own token count, needle in the middle", async () => {
    const ctx = 8192;
    const { d, prompts } = deps((p) => needleIn(p));
    const r = await runRecallCheck(d, ctx, "salt-1");
    expect(r.status).toBe("passed");
    const counted = tokenizer(prompts[0]!);
    expect(counted).toBeGreaterThan(ctx * RECALL_FRACTION * 0.96);
    expect(counted).toBeLessThan(ctx * RECALL_FRACTION * 1.04);
    expect(r.fractionOfCtx).toBeGreaterThan(0.85);
    expect(r.fractionOfCtx).toBeLessThan(0.95);
    const pos = prompts[0]!.indexOf(needleFor("salt-1")) / prompts[0]!.length;
    expect(pos).toBeGreaterThan(0.35);
    expect(pos).toBeLessThan(0.65);
    expect(prompts[0]!.endsWith("Reply with only the passphrase.")).toBe(true);
  });

  it("fails when the model does not produce the needle", async () => {
    const r = await runRecallCheck(deps(() => "I do not know").d, 4096, "salt-2");
    expect(r.status).toBe("failed");
    expect(r.error).toContain("not recalled");
  });

  it("fails (does not throw) when the server rejects the request", async () => {
    const d = deps(() => "", { ask: async () => ({ ok: false, status: 400, text: "request exceeds the available context size", reasoning: "", promptTokens: null }) }).d;
    const r = await runRecallCheck(d, 4096, "salt-3");
    expect(r.status).toBe("failed");
    expect(r.error).toContain("HTTP 400");
  });

  it("still runs when the server cannot count tokens, and accepts the needle from reasoning", async () => {
    const d = deps(() => "", {
      tokenize: async () => null,
      ask: async (p) => ({ ok: true, status: 200, text: "", reasoning: "the passphrase is " + needleIn(p), promptTokens: null }),
    }).d;
    const r = await runRecallCheck(d, 4096, "salt-4");
    expect(r.status).toBe("passed");
    expect(r.promptTokens).toBeNull();
  });

  it("the needle is a function of the salt and the prompt carries it exactly once", () => {
    expect(needleFor("a")).toBe(needleFor("a"));
    expect(needleFor("a")).not.toBe(needleFor("b"));
    const n = needleFor("a");
    expect(buildNeedlePrompt(500, "a", n).split(n)).toHaveLength(2);
  });
});

describe("what models.json records (requirements 5, 6)", () => {
  it("chosen flags (incl. --spec-type draft-mtp), tok/s, acceptance and the recall result", async () => {
    const out = await searchConfigs({
      caps: capsMtp, kvChoices: calibrationKvChoices(capsMtp), weightsBytes: 16 * GiB, extraBytes: GiB, kvBytesPerToken: 65536, startCtx: 262144,
      ctxLadder: ctxLadderFor(262144, [65536]), totalVramBytes: TOTAL, log: () => {}, mtp: true, verifyRecall: true,
      run: async (c, o) => measured(c, o, (x) => (x.kvK === "q4_0" ? 95 : 20), (x) => passed(x.ctx)),
    });
    const receipt = buildReceipt(out, capsMtp, TOTAL, "/r.json", "2026-11-03T00:00:00.000Z")!;
    expect(receipt).toMatchObject({ specType: "draft-mtp", draftAcceptance: 0.87, tgTokensPerSecond: 95, selected: { ctx: 262144, kvK: "q4_0", mtp: true } });
    expect(receipt.recall).toMatchObject({ status: "passed", ctx: 262144 });
    const next = applyCalibration({ model: "/m.gguf", serverArgs: ["old"] }, receipt, capsMtp);
    expect(next["nCtx"]).toBe(262144);
    const args = next["serverArgs"] as string[];
    expect(args).toEqual(expect.arrayContaining(["-ctk", "q4_0", "-ctv", "q4_0", "--parallel", "1"]));
    expect(args.slice(args.indexOf("--spec-type"), args.indexOf("--spec-type") + 2)).toEqual(["--spec-type", "draft-mtp"]);
    expect(next["calibration"]).toMatchObject({ specType: "draft-mtp", recall: { status: "passed" } });
  });
});

describe("--skip-recall", () => {
  it("is parsed alongside --calibrate and off by default", () => {
    expect(parsePullArgs(["--calibrate", "--skip-recall"])).toMatchObject({ calibrate: true, skipRecall: true });
    expect(parsePullArgs(["--calibrate"]).skipRecall).toBeUndefined();
    expect(_internals.CTX_LADDER[0]).toBe(65536);
  });
});
