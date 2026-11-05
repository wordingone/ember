// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import {
  isModelFreeFastPath,
  openWeightsModelName,
  resolveModelSeat,
  selectedModelContract,
} from "./model-seat.ts";

const base = {
  explicitModelUrl: undefined,
  gpuFreeRequested: false,
  referenceSeatEnv: undefined,
};

describe("OPEN_WEIGHTS harness seat", () => {
  it("is selected by --open-weights and the flag is stripped from argv", () => {
    const d = resolveModelSeat({ ...base, argv: ["bun", "ember", "--open-weights", "-p", "hi"], referenceModelName: "qwen3-coder" });
    expect(d.allowed).toBe(true);
    expect(d.seat).toBe("OPEN_WEIGHTS");
    expect(d.source).toBe("flag");
    expect(d.argv).toEqual(["bun", "ember", "-p", "hi"]);
  });

  it("is selected by EMBER_OPEN_WEIGHTS=1 and by models.json seat", () => {
    expect(resolveModelSeat({ ...base, argv: ["bun", "ember"], openWeightsEnv: "1" }).source).toBe("env");
    const fromConfig = resolveModelSeat({ ...base, argv: ["bun", "ember"], openWeightsConfig: true });
    expect(fromConfig.seat).toBe("OPEN_WEIGHTS");
    expect(fromConfig.source).toBe("config");
  });

  it("never outranks an explicit --reference-seat request", () => {
    const d = resolveModelSeat({ ...base, argv: ["bun", "ember", "--reference-seat", "--open-weights"], openWeightsConfig: true });
    expect(d.seat).toBe("REFERENCE_ONLY");
  });

  it("is never presented as owned: labelled, no config hash, no structured outputs", () => {
    const d = resolveModelSeat({ ...base, argv: ["bun", "ember", "--open-weights"], referenceModelName: "qwen3-coder" });
    const c = selectedModelContract(d);
    expect(c).toEqual({ seat: "OPEN_WEIGHTS", modelName: "OPEN_WEIGHTS: qwen3-coder", modelConfigSha256: null, structuredOutputs: false });
    expect(openWeightsModelName("OPEN_WEIGHTS: x")).toBe("OPEN_WEIGHTS: x");
    expect(openWeightsModelName(undefined)).toBe("OPEN_WEIGHTS: unidentified-model");
  });

  it("without any open-weights request, a plain launch still refuses an unbound seat", () => {
    const d = resolveModelSeat({ ...base, argv: ["bun", "ember"] });
    expect(d.allowed).toBe(false);
    expect(d.seat).toBeNull();
  });

  it("`pull` is a model-free fast path and the flag does not hide --mcp", () => {
    expect(isModelFreeFastPath(["bun", "ember", "pull", "--auto"])).toBe(true);
    expect(isModelFreeFastPath(["bun", "ember", "--open-weights", "--mcp"])).toBe(false);
  });
});
