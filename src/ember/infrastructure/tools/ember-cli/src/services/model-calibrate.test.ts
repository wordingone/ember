// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { allowedKvChoices, parseHelp } from "./llama-backend.ts";
import {
  HEADROOM_BYTES, applyCalibration, buildReceipt, makeCandidate, modelledTurnSeconds, searchConfigs, selectBest, serverArgsFor,
  type Candidate, type CandidateResult,
} from "./model-calibrate.ts";

const GiB = 1024 ** 3;
const TOTAL = 24 * GiB;
const caps = parseHelp("-fa, --flash-attn [on|off|auto]\n-ctk, --cache-type-k TYPE\n  allowed values: f16, q8_0, turbo3, turbo4\n  (default: f16)\n");

function res(kv: string, pp: number, tg: number, peakGiB: number, over: Partial<Candidate> = {}, coherent = true): CandidateResult {
  const candidate = makeCandidate({ kvK: kv, kvV: kv, ctx: 65536, ubatch: 512, batch: 2048, flashAttn: true, ...over });
  return { candidate, ok: true, coherent, ppTps: pp, tgTps: tg, peakVramBytes: peakGiB * GiB, headroomBytes: TOTAL - peakGiB * GiB, at: "t" };
}

describe("config selection", () => {
  it("takes the lowest modelled turn time", () => {
    const fast = res("q8_0", 4000, 60, 18);
    const slow = res("turbo3", 2000, 50, 14);
    expect(selectBest([slow, fast], TOTAL)?.candidate.kvK).toBe("q8_0");
    expect(modelledTurnSeconds(4000, 60)).toBeCloseTo(8000 / 4000 + 500 / 60, 6);
  });

  it("rejects candidates that leave less than 1 GiB free, however fast", () => {
    const tooBig = res("q8_0", 9000, 90, 23.5);
    const ok = res("turbo3", 2000, 50, 14);
    expect(selectBest([tooBig, ok], TOTAL)?.candidate.kvK).toBe("turbo3");
    expect(selectBest([res("q8_0", 9000, 90, 23.0)], TOTAL, HEADROOM_BYTES)).not.toBeNull(); // exactly 1 GiB left is allowed
    expect(selectBest([tooBig], TOTAL)).toBeNull();
  });

  it("rejects an incoherent or unmeasured-memory candidate", () => {
    expect(selectBest([res("turbo3", 9000, 90, 10, {}, false)], TOTAL)).toBeNull();
    const unmeasured = { ...res("q8_0", 9000, 90, 10), peakVramBytes: null };
    expect(selectBest([unmeasured], TOTAL)).toBeNull();
  });

  it("within 3% prefers the higher-quality KV type; beyond 3% speed wins", () => {
    const q8 = res("q8_0", 4000, 60, 18);
    const t3near = res("turbo3", 4040, 60.6, 14); // ~1% faster
    expect(selectBest([t3near, q8], TOTAL)?.candidate.kvK).toBe("q8_0");
    const t3far = res("turbo3", 5000, 75, 14); // ~20% faster
    expect(selectBest([t3far, q8], TOTAL)?.candidate.kvK).toBe("turbo3");
  });
});

describe("candidate search", () => {
  it("serverArgs carry the KV pair, batch sizes, the flash-attn dialect and one slot", () => {
    const c = makeCandidate({ kvK: "turbo3", kvV: "turbo3", ctx: 65536, ubatch: 1024, batch: 2048, flashAttn: true });
    expect(serverArgsFor(c, caps)).toEqual(["-ngl", "999", "-fa", "on", "-ctk", "turbo3", "-ctv", "turbo3", "-ub", "1024", "-b", "2048", "--parallel", "1"]);
    expect(serverArgsFor(c, caps, { chatTemplateFile: "/t.jinja" }).slice(-2)).toEqual(["--chat-template-file", "/t.jinja"]);
  });

  it("walks KV pairs, then batch sizes for the winner, skipping pairs that cannot fit", async () => {
    const seen: string[] = [];
    const out = await searchConfigs({
      caps, kvChoices: allowedKvChoices(caps, { includeF16: true }), weightsBytes: 12 * GiB, extraBytes: 0, kvBytesPerToken: 262144,
      startCtx: 65536, ctxLadder: [65536, 32768], totalVramBytes: TOTAL, log: () => {},
      run: async (c) => {
        seen.push(c.id);
        const speed = c.kvK === "q8_0" ? 1.3 : 1;
        return res(c.kvK, 3000 * speed * (c.ubatch === 2048 ? 1.1 : 1), 50, 18, { ubatch: c.ubatch, batch: c.batch });
      },
    });
    // f16 (12 GiB weights + 16 GiB fp16 KV) is estimated over budget and never launched.
    expect(seen.some((s) => s.startsWith("f16-f16_ctx65536_ub512"))).toBe(false);
    expect(out.results.find((r) => r.candidate.kvK === "f16")?.error).toContain("exceeds budget");
    expect(seen.filter((s) => s.includes("_ub512_")).map((s) => s.split("_ctx")[0])).toEqual(["q8_0-q8_0", "turbo4-turbo4", "turbo3-turbo3"]);
    expect(seen.filter((s) => /_ub(1024|2048)_/.test(s)).every((s) => s.startsWith("q8_0-q8_0"))).toBe(true);
    expect(out.selected?.candidate).toMatchObject({ kvK: "q8_0", ubatch: 2048 });
    // flash attention off is recorded as not tried for quantised KV
    expect(out.results.find((r) => !r.candidate.flashAttn)?.error).toContain("only valid for unquantised f16");
  });

  it("steps the context down when nothing leaves the headroom", async () => {
    const ctxs: number[] = [];
    const out = await searchConfigs({
      caps, kvChoices: allowedKvChoices(caps), weightsBytes: 8 * GiB, extraBytes: 0, kvBytesPerToken: 1000, startCtx: 65536, ctxLadder: [65536, 32768, 16384],
      totalVramBytes: TOTAL, log: () => {},
      run: async (c) => { ctxs.push(c.ctx); return res(c.kvK, 3000, 50, c.ctx > 40000 ? 23.9 : 12, { ctx: c.ctx }); },
    });
    expect(Math.max(...ctxs)).toBe(65536);
    expect(out.selected?.candidate.ctx).toBe(32768);
  });

  it("survives a candidate whose measurement throws", async () => {
    const out = await searchConfigs({
      caps, kvChoices: allowedKvChoices(caps), weightsBytes: GiB, extraBytes: 0, kvBytesPerToken: 1000, startCtx: 8192, ctxLadder: [8192],
      totalVramBytes: TOTAL, log: () => {},
      run: async (c) => { if (c.kvK === "turbo4") throw new Error("boom"); return res(c.kvK, 3000, 50, 5, { ctx: 8192, ubatch: c.ubatch }); },
    });
    expect(out.results.find((r) => r.candidate.kvK === "turbo4" && !r.ok)?.error).toContain("boom");
    expect(out.selected).not.toBeNull();
  });
});

describe("models.json update", () => {
  it("writes the winner's serverArgs, nCtx and a calibration receipt, keeping other keys", () => {
    const winner = res("turbo3", 4000, 60, 14, { ubatch: 2048 });
    const receipt = buildReceipt({ selected: winner, results: [winner], rule: "r" }, caps, TOTAL, "/r.json", "2026-01-01T00:00:00.000Z")!;
    const next = applyCalibration({ model: "/m.gguf", seat: "open-weights", serverArgs: ["old"] }, receipt, caps);
    expect(next["model"]).toBe("/m.gguf");
    expect(next["nCtx"]).toBe(65536);
    expect(next["serverArgs"]).toEqual(["-ngl", "999", "-fa", "on", "-ctk", "turbo3", "-ctv", "turbo3", "-ub", "2048", "-b", "2048", "--parallel", "1"]);
    expect(next["calibration"]).toMatchObject({ at: "2026-01-01T00:00:00.000Z", ppTokensPerSecond: 4000, tgTokensPerSecond: 60, peakVramBytes: 14 * GiB, headroomBytes: 10 * GiB, resultsFile: "/r.json" });
  });

  it("builds no receipt (so models.json stays untouched) when nothing is feasible", () => {
    expect(buildReceipt({ selected: null, results: [], rule: "r" }, caps, TOTAL, "/r.json")).toBeNull();
  });
});
