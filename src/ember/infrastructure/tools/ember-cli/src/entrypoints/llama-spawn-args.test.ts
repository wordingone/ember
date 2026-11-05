// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// #2371 requirement 6: the managed spawn passes the flags `ember pull --calibrate` recorded in
// models.json `serverArgs`, including `--spec-type draft-mtp`.  Pure argument-vector tests: no
// llama-server is started.

import { describe, expect, it } from "bun:test";

import { buildLlamaServerArgs } from "./process-entry.ts";
import { applyCalibration, buildReceipt, makeCandidate, type CandidateResult } from "../services/model-calibrate.ts";
import { parseHelp } from "../services/llama-backend.ts";

const GiB = 1024 ** 3;
const caps = parseHelp("-fa, --flash-attn [on|off|auto]\n--spec-type [none|draft-mtp]\n");

function calibratedServerArgs(mtp: boolean): string[] {
  const candidate = makeCandidate({ kvK: "q4_0", kvV: "q4_0", ctx: 262144, ubatch: 512, batch: 2048, flashAttn: true, ...(mtp ? { mtp: true } : {}) });
  const r: CandidateResult = { candidate, ok: true, coherent: true, ppTps: 330, tgTps: 95, peakVramBytes: 22 * GiB, headroomBytes: 2 * GiB, at: "t" };
  const receipt = buildReceipt({ selected: r, results: [r], rule: "r" }, caps, 24 * GiB, "/r.json")!;
  return applyCalibration({}, receipt, caps)["serverArgs"] as string[];
}

describe("managed spawn argument vector", () => {
  const base = { binaryPath: "llama-server", modelPath: "/m.gguf", port: 18810, nCtx: 262144, logPath: "/l.log" };

  it("passes the recorded flags after the model / port / context flags, --spec-type draft-mtp included", () => {
    const args = buildLlamaServerArgs({ ...base, mmproj: "/mm.gguf", extraArgs: calibratedServerArgs(true) });
    expect(args.slice(0, 7)).toEqual(["--model", "/m.gguf", "--port", "18810", "--ctx-size", "262144", "-n"]);
    expect(args).toContain("--mmproj");
    const i = args.indexOf("--spec-type");
    expect(i).toBeGreaterThan(0);
    expect(args[i + 1]).toBe("draft-mtp");
    expect(args.slice(args.indexOf("-ctk"), args.indexOf("-ctk") + 4)).toEqual(["-ctk", "q4_0", "-ctv", "q4_0"]);
    expect(args.slice(args.indexOf("--parallel"), args.indexOf("--parallel") + 2)).toEqual(["--parallel", "1"]);
  });

  it("a calibration without MTP records no --spec-type, so the spawn has none", () => {
    const args = buildLlamaServerArgs({ ...base, extraArgs: calibratedServerArgs(false) });
    expect(args).not.toContain("--spec-type");
    expect(args).toContain("--ctx-size");
  });

  it("an uncalibrated models.json (no serverArgs) spawns with the base flags only", () => {
    expect(buildLlamaServerArgs(base)).toEqual(["--model", "/m.gguf", "--port", "18810", "--ctx-size", "262144", "-n", "32768", "--jinja"]);
  });
});
