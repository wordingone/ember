// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Fix #51 scope: capability from seat descriptor, owned-default.
//
// This is the RED test for the bounded patch: `selectedModelContract` derives
// a truthful model identity + capability contract from `ModelSeatDecision` /
// `OwnedModelIdentity`. Qwen (or any borrowed model) is reachable only via an
// explicit REFERENCE_ONLY seat, always labeled through `referenceSeatModelName`.
// `structuredOutputs` is honored ONLY when declared and bound to the exact
// `modelConfigSha256` of the served identity — an owned identity without a
// declaration defaults to false, never inherited from a hardcoded model-id
// literal.

import { describe, expect, it } from "bun:test";

import {
  resolveModelSeat,
  selectedModelContract,
} from "./entrypoints/model-seat.ts";
import { modelSupportsStructuredOutputs } from "./model-config";

describe("model identity contract (Fix #51 scope)", () => {
  it("derives no contract when the seat decision is refused", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
    });

    expect(decision.allowed).toBe(false);
    expect(selectedModelContract(decision)).toBeNull();
  });

  it("labels a REFERENCE_ONLY seat (Qwen or any borrowed model) truthfully and never grants structured outputs", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
    });

    const contract = selectedModelContract(decision);
    expect(contract).not.toBeNull();
    expect(contract?.seat).toBe("REFERENCE_ONLY");
    expect(contract?.modelName.startsWith("REFERENCE_ONLY: ")).toBe(true);
    expect(contract?.modelConfigSha256).toBeNull();
    expect(contract?.structuredOutputs).toBe(false);
  });

  it("defaults an owned identity without a capability declaration to structuredOutputs=false", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: {
        checkpointSha256: "a".repeat(64),
        endpointUrl: "http://127.0.0.1:8083",
        identityUrl: "http://127.0.0.1:8083/v1/models",
        modelConfigSha256: "d".repeat(64),
        serverSourceSha256: "e".repeat(64),
        tokenizerSha256: "f".repeat(64),
        modelName: "ember-owned:a" + "a".repeat(11),
      },
    });

    const contract = selectedModelContract(decision);
    expect(contract?.seat).toBe("OWNED_ADMITTED");
    expect(contract?.modelName).toBe("ember-owned:a" + "a".repeat(11));
    expect(contract?.modelConfigSha256).toBe("d".repeat(64));
    expect(contract?.structuredOutputs).toBe(false);
    expect(modelSupportsStructuredOutputs(contract)).toBe(false);
  });

  it("honors structuredOutputs only when declared and bound to the exact modelConfigSha256", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: {
        checkpointSha256: "b".repeat(64),
        endpointUrl: "http://127.0.0.1:8083",
        identityUrl: "http://127.0.0.1:8083/v1/models",
        modelConfigSha256: "d".repeat(64),
        serverSourceSha256: "e".repeat(64),
        tokenizerSha256: "f".repeat(64),
        modelName: "ember-owned:b" + "b".repeat(11),
        capabilities: { structuredOutputs: true },
      },
    });

    const contract = selectedModelContract(decision);
    expect(contract?.structuredOutputs).toBe(true);
    expect(modelSupportsStructuredOutputs(contract)).toBe(true);
  });

  it("modelSupportsStructuredOutputs defaults false with no declaration and never trusts an unbound declaration", () => {
    expect(modelSupportsStructuredOutputs(null)).toBe(false);
    expect(modelSupportsStructuredOutputs(undefined)).toBe(false);
    expect(
      modelSupportsStructuredOutputs({
        modelConfigSha256: null,
        structuredOutputs: true,
      }),
    ).toBe(false);
  });

  it("an OFFLINE seat carries no model identity and no structured-outputs capability", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember"],
      explicitModelUrl: undefined,
      gpuFreeRequested: true,
      referenceSeatEnv: undefined,
    });

    const contract = selectedModelContract(decision);
    expect(contract?.seat).toBe("OFFLINE");
    expect(contract?.structuredOutputs).toBe(false);
    expect(contract?.modelConfigSha256).toBeNull();
  });
});
