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
    expect(selectedModelContract(decision)).toBeUndefined();
  });

  it("labels a REFERENCE_ONLY seat (Qwen or any borrowed model) truthfully and never grants structured outputs", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
    });

    const contract = selectedModelContract(decision);
    expect(contract).not.toBeUndefined();
    expect(contract?.seat).toBe("REFERENCE_ONLY");
    expect(contract?.modelName.startsWith("REFERENCE_ONLY: ")).toBe(true);
    expect(contract?.modelConfigSha256).toBeNull();
    expect(contract?.structuredOutputs).toBe(false);
  });

  it("carries the exact reference model identity via referenceModelName, never collapsing to unidentified-model", () => {
    // Fix #51 P1 repair (1): resolveModelSeat never attaches an ownedIdentity
    // to a REFERENCE_ONLY decision, so selectedModelContract must read the
    // identity from decision.referenceModelName -- an explicit closed
    // ReferenceModelContract -- never from ownedIdentity.
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      referenceModelName: "Qwen2.5-72B-Instruct",
    });

    expect(decision.ownedIdentity).toBeUndefined();

    const contract = selectedModelContract(decision);
    expect(contract?.seat).toBe("REFERENCE_ONLY");
    expect(contract?.modelName).toBe("REFERENCE_ONLY: Qwen2.5-72B-Instruct");
    expect(contract?.modelName).not.toContain("unidentified-model");
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
    expect(modelSupportsStructuredOutputs(contract, contract?.modelConfigSha256)).toBe(false);
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
        modelConfigCapabilities: { modelConfigSha256: "d".repeat(64), structuredOutputs: true },
      },
    });

    const contract = selectedModelContract(decision);
    expect(contract?.structuredOutputs).toBe(true);
    expect(modelSupportsStructuredOutputs(contract, "d".repeat(64))).toBe(true);
  });

  it("rejects a capability declaration whose modelConfigSha256 does not match the served identity's hash", () => {
    // Fix #51 P1 repair (2): the declaration must carry its OWN modelConfigSha256
    // and be granted only on exact equality with the served identity's hash.
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: {
        checkpointSha256: "c".repeat(64),
        endpointUrl: "http://127.0.0.1:8083",
        identityUrl: "http://127.0.0.1:8083/v1/models",
        modelConfigSha256: "d".repeat(64), // served identity's actual hash
        serverSourceSha256: "e".repeat(64),
        tokenizerSha256: "f".repeat(64),
        modelName: "ember-owned:c" + "c".repeat(11),
        modelConfigCapabilities: { modelConfigSha256: "9".repeat(64), structuredOutputs: true }, // mismatched
      },
    });

    const contract = selectedModelContract(decision);
    expect(contract?.modelConfigSha256).toBe("d".repeat(64));
    expect(contract?.structuredOutputs).toBe(false);
    expect(modelSupportsStructuredOutputs(contract, contract?.modelConfigSha256)).toBe(false);
  });

  it("modelSupportsStructuredOutputs defaults false with no declaration and never trusts an unbound declaration", () => {
    expect(modelSupportsStructuredOutputs(null, "d".repeat(64))).toBe(false);
    expect(modelSupportsStructuredOutputs(undefined, "d".repeat(64))).toBe(false);
    expect(
      modelSupportsStructuredOutputs(
        {
          modelConfigSha256: null,
          structuredOutputs: true,
        },
        "d".repeat(64),
      ),
    ).toBe(false);
  });

  it("an OFFLINE seat produces no callable model contract at all", () => {
    // Fix #51 P1 repair (5): OFFLINE must never return a callable-looking
    // contract -- selectedModelContract returns undefined, not a stub object.
    const decision = resolveModelSeat({
      argv: ["node", "ember"],
      explicitModelUrl: undefined,
      gpuFreeRequested: true,
      referenceSeatEnv: undefined,
    });

    expect(decision.seat).toBe("OFFLINE");
    expect(selectedModelContract(decision)).toBeUndefined();
  });

  it("a refused decision and an OFFLINE seat both hand consumers undefined, never a stub contract", () => {
    // Negative test asserting consumers handle undefined (Fix #51 P1 repair (5)).
    const refused = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
    });
    const offline = resolveModelSeat({
      argv: ["node", "ember"],
      explicitModelUrl: undefined,
      gpuFreeRequested: true,
      referenceSeatEnv: undefined,
    });

    for (const decision of [refused, offline]) {
      const contract = selectedModelContract(decision);
      expect(contract).toBeUndefined();
      // A consumer written as `if (!contract) { /* no model call */ }`
      // correctly fails closed for both cases.
      expect(Boolean(contract)).toBe(false);
    }
  });
});
