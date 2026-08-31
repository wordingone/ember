// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// cond3 (borrowed_reference): a borrowed/REFERENCE_ONLY seat round-trips the
// ember-cli RUNTIME consumer as a reference seat with NO owned identity, NO
// owned config-sha, and NO capability (completion) credit -- and can never be
// silently upgraded to owned. This is the runtime-layer twin of the identity-
// manifest prohibition already enforced (and tested) in the validator:
//   src/ember/governance/scripts/ember_01_identity/validate_identity.py
//     L960-965  disposition!=OWNED_ADMITTED + selected/completion -> admission.disposition
//     L967-971  REFERENCE_ONLY + selected/completion ->
//               reference.selected_as_owned / reference.owned_completion_credit
//   tests/ember_01_identity/test_validate_identity.py
//     test_reference_only_cannot_be_owned_or_counted (L534)
//     test_only_owned_admitted_can_be_selected_or_counted[REFERENCE_ONLY] (L733)
//
// The validator gates the on-disk manifest's disposition. THIS test gates the
// SECOND, independent gate: the runtime seat resolver the ember-cli consumer
// actually calls. It imports the REAL consumer functions -- resolveModelSeat /
// selectedModelContract (model-seat.ts) and loadOwnedModelIdentity
// (owned-seat-loader.ts) -- never a reimplementation. A borrowed seat that is
// laundered into owned credit at EITHER gate is the exact prohibited event.

import { describe, expect, it } from "bun:test";

import {
  resolveModelSeat,
  selectedModelContract,
  type OwnedModelIdentity,
} from "./model-seat.ts";
import { loadOwnedModelIdentity } from "./owned-seat-loader.ts";

// A real, fully-formed OWNED_ADMITTED identity. Its mere availability must not
// leak into a borrowed seat's contract -- the negative below proves the runtime
// consumer never reads these owned fields when a reference seat is requested.
const OWNED_IDENTITY: OwnedModelIdentity = {
  checkpointSha256: "a".repeat(64),
  endpointUrl: "http://127.0.0.1:8083",
  identityUrl: "http://127.0.0.1:8083/v1/models",
  modelConfigSha256: "b".repeat(64),
  serverSourceSha256: "c".repeat(64),
  tokenizerSha256: "d".repeat(64),
  modelName: "ember-owned:" + "a".repeat(12),
  modelConfigCapabilities: {
    modelConfigSha256: "b".repeat(64),
    structuredOutputs: true,
  },
};

describe("cond3 borrowed_reference — ember-cli runtime consumer round-trip", () => {
  it("POSITIVE: a borrowed --reference-seat round-trips as REFERENCE_ONLY with no owned config-sha and no capability credit", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hi"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      referenceModelName: "Qwen2.5-72B-Instruct",
    });
    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("REFERENCE_ONLY");
    // A REFERENCE_ONLY decision structurally never carries an owned identity.
    expect(decision.ownedIdentity).toBeUndefined();

    const contract = selectedModelContract(decision);
    expect(contract).toBeDefined();
    expect(contract!.seat).toBe("REFERENCE_ONLY");
    // Borrowed stays borrowed: labeled as REFERENCE_ONLY, never presented owned.
    expect(contract!.modelName).toBe("REFERENCE_ONLY: Qwen2.5-72B-Instruct");
    // No owned config identity (the owned-completion / owned-selection surface).
    expect(contract!.modelConfigSha256).toBeNull();
    // No capability credit -- a borrowed model never carries structured-outputs.
    expect(contract!.structuredOutputs).toBe(false);
  });

  it("NEGATIVE-1: an available OWNED_ADMITTED identity is NOT laundered into a borrowed seat's contract (no silent upgrade)", () => {
    // Both an explicit owned endpoint AND a full owned identity are present, yet
    // --reference-seat is requested. The runtime consumer must keep the seat
    // borrowed and must NOT copy the owned modelConfigSha256/capability into it.
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hi"],
      explicitModelUrl: "http://127.0.0.1:8083",
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      referenceModelName: "Qwen2.5-72B-Instruct",
      ownedIdentity: OWNED_IDENTITY,
    });
    expect(decision.seat).toBe("REFERENCE_ONLY");
    expect(decision.source).toBe("flag");
    expect(decision.ownedIdentity).toBeUndefined();

    const contract = selectedModelContract(decision);
    expect(contract!.seat).toBe("REFERENCE_ONLY");
    // The owned config-sha ("b"*64) and its structured-outputs capability MUST
    // NOT appear on the borrowed contract -- that would be the silent upgrade.
    expect(contract!.modelConfigSha256).toBeNull();
    expect(contract!.modelConfigSha256).not.toBe(OWNED_IDENTITY.modelConfigSha256);
    expect(contract!.structuredOutputs).toBe(false);
  });

  it("NEGATIVE-2: a borrowed model with no owned checkpoint cannot mint an OWNED_ADMITTED identity through the owned load path", () => {
    // Route a borrowed model through the REAL owned-seat loader. The trusted
    // resolver's payload declares a borrowed/reference disposition (not
    // OWNED_ADMITTED) with no valid owned checkpoint sha -- exactly what a
    // borrowed server yields. loadOwnedModelIdentity must fail closed, never
    // return an owned identity.
    const borrowedResolverPayload = JSON.stringify({
      valid: true,
      seat: "REFERENCE_ONLY", // borrowed: not OWNED_ADMITTED
      checkpoint_sha256: "", // no owned checkpoint bytes
      endpoint_url: "http://127.0.0.1:8082",
      identity_url: "http://127.0.0.1:8082/v1/models",
      model_name: "REFERENCE_ONLY: Qwen2.5-72B-Instruct",
    });

    expect(() =>
      loadOwnedModelIdentity(
        {
          repoRoot: "/repo",
          configHome: "/config",
          manifestPath: "/config/owned/current.json",
          verifierRegistryPath: "/config/owned/trusted-verifiers.json",
        },
        {
          // All required files "exist" so we reach the resolver verdict itself.
          exists: () => true,
          execute: () => ({
            status: 0,
            stdout: borrowedResolverPayload,
            stderr: "",
          }),
        },
      ),
    ).toThrow("owned seat resolver returned an invalid admitted identity");
  });

  it("NEGATIVE-2b: even a well-formed-looking owned payload with a borrowed (non-OWNED_ADMITTED) seat is rejected", () => {
    // Harden the seat check: every other owned field is shaped correctly, only
    // the seat is borrowed. The owned load path must still fail closed.
    const cp = "e".repeat(64);
    const laundered = JSON.stringify({
      valid: true,
      seat: "REFERENCE_ONLY",
      checkpoint_sha256: cp,
      endpoint_url: "http://127.0.0.1:8082",
      identity_url: "http://127.0.0.1:8082/v1/models",
      model_name: "ember-owned:" + cp.slice(0, 12),
    });
    expect(() =>
      loadOwnedModelIdentity(
        {
          repoRoot: "/repo",
          configHome: "/config",
          manifestPath: "/config/owned/current.json",
          verifierRegistryPath: "/config/owned/trusted-verifiers.json",
        },
        {
          exists: () => true,
          execute: () => ({ status: 0, stdout: laundered, stderr: "" }),
        },
      ),
    ).toThrow("owned seat resolver returned an invalid admitted identity");
  });
});
