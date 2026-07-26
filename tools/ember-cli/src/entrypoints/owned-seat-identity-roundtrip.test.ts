// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// cond3 (owned seat): a VALID owned identity manifest round-trips the ember-cli
// RUNTIME consumer with NO field reinterpretation (EMBER-01 completion
// condition 3), on the DEFAULT seat. The borrowed/reference twin of this test
// (borrowed-reference-identity-roundtrip.test.ts) already gates the explicit
// reference seat; THIS test gates the seat the goal directive names as the
// default: OWNED. It drives the REAL production chain -- never a
// reimplementation:
//
//   admitted resolver verdict (scripts/ember_restart/cli_seat.py stdout)
//     -> loadOwnedModelIdentity   (owned-seat-loader.ts, the manifest consumer)
//     -> resolveModelSeat         (model-seat.ts, DEFAULT invocation: no
//                                  --reference-seat flag, no env, no gpu-free)
//     -> selectedModelContract    (model-seat.ts, the final consumer surface)
//
// "No field reinterpretation" is asserted FIELD BY FIELD, never as one
// whole-object deep-equal: a deep-equal passes for the wrong reason when a
// field is absent from both sides. Every identity field the resolver emits is
// enumerated below and each is asserted to survive VERBATIM at every layer.

import { describe, expect, it } from "bun:test";

import {
  resolveModelSeat,
  selectedModelContract,
  type OwnedModelContract,
} from "./model-seat.ts";
import { loadOwnedModelIdentity } from "./owned-seat-loader.ts";

// The exact byte values of the admitted identity, named once so every layer's
// assertion binds to the SAME source values -- a reinterpretation at any layer
// breaks a comparison against these, not against a copy derived through the
// code under test.
const CHECKPOINT_SHA256 = "1234567890abcdef".repeat(4);
const MODEL_CONFIG_SHA256 = "f0e1d2c3b4a59687".repeat(4);
const SERVER_SOURCE_SHA256 = "aabbccddeeff0011".repeat(4);
const TOKENIZER_SHA256 = "99887766554433221100ffeeddccbbaa".repeat(2);
const ENDPOINT_URL = "http://127.0.0.1:8083";
const IDENTITY_URL = ENDPOINT_URL + "/v1/models";
const MODEL_NAME = "ember-owned:" + CHECKPOINT_SHA256.slice(0, 12);
const MODEL_FORMAT = "pytorch-checkpoint-v3";

const MANIFEST_PATH = "/config/owned/current.json";
const REGISTRY_PATH = "/config/owned/trusted-verifiers.json";

// The launch descriptor the trusted resolver binds to the admitted identity.
// run_manifest_path / trusted_verifier_registry_path MUST denote the same
// files the loader was pointed at -- that identity-of-paths is itself part of
// the no-reinterpretation contract (parseOwnedLaunch enforces it).
const LAUNCH = {
  checkpoint_dir: "/repo/checkpoints/step-final",
  mode: "INTERACTIVE",
  model_config_path: "/repo/configs/ember-restart-3b.json",
  run_manifest_path: MANIFEST_PATH,
  server_path: "/repo/tools/ember-restart-3b/serve_owned_openai.py",
  tokenizer_path: "/repo/tokenizer/tokenizer.json",
  trusted_verifier_registry_path: REGISTRY_PATH,
} as const;

function admittedResolverPayload(): string {
  return JSON.stringify({
    valid: true,
    seat: "OWNED_ADMITTED",
    checkpoint_sha256: CHECKPOINT_SHA256,
    endpoint_url: ENDPOINT_URL,
    identity_url: IDENTITY_URL,
    model_name: MODEL_NAME,
    model_config_sha256: MODEL_CONFIG_SHA256,
    model_format: MODEL_FORMAT,
    server_source_sha256: SERVER_SOURCE_SHA256,
    tokenizer_sha256: TOKENIZER_SHA256,
    model_config_capabilities: {
      model_config_sha256: MODEL_CONFIG_SHA256,
      structured_outputs: true,
    },
    launch: LAUNCH,
  });
}

function loadAdmittedIdentity() {
  return loadOwnedModelIdentity(
    {
      repoRoot: "/repo",
      configHome: "/config",
      manifestPath: MANIFEST_PATH,
      verifierRegistryPath: REGISTRY_PATH,
    },
    {
      // All bound files "exist" so the resolver verdict itself is the surface
      // under test, exactly as the borrowed twin does.
      exists: () => true,
      execute: () => ({
        status: 0,
        stdout: admittedResolverPayload(),
        stderr: "",
      }),
    },
  );
}

describe("cond3 owned seat — ember-cli runtime consumer round-trip", () => {
  it("POSITIVE: every admitted identity field survives loadOwnedModelIdentity verbatim (no reinterpretation)", () => {
    const identity = loadAdmittedIdentity();
    expect(identity).toBeDefined();

    // Field-by-field: each resolver-emitted identity field, asserted against
    // the named source constant. No deep-equal.
    expect(identity!.checkpointSha256).toBe(CHECKPOINT_SHA256);
    expect(identity!.endpointUrl).toBe(ENDPOINT_URL);
    expect(identity!.identityUrl).toBe(IDENTITY_URL);
    expect(identity!.modelConfigSha256).toBe(MODEL_CONFIG_SHA256);
    expect(identity!.modelFormat).toBe(MODEL_FORMAT);
    expect(identity!.modelName).toBe(MODEL_NAME);
    expect(identity!.serverSourceSha256).toBe(SERVER_SOURCE_SHA256);
    expect(identity!.tokenizerSha256).toBe(TOKENIZER_SHA256);

    // The admitted seat carries NO development-only fields -- their presence
    // would itself be a reinterpretation of an OWNED_ADMITTED manifest.
    expect(identity!.seat).toBeUndefined();
    expect(identity!.claimStatus).toBeUndefined();
    expect(identity!.tokensSeen).toBeUndefined();
    expect(identity!.allocatedParameters).toBeUndefined();
    expect(identity!.activeParameters).toBeUndefined();

    // Capability declaration survives, bound to the SAME served config hash.
    expect(identity!.modelConfigCapabilities).toBeDefined();
    expect(identity!.modelConfigCapabilities!.modelConfigSha256).toBe(MODEL_CONFIG_SHA256);
    expect(identity!.modelConfigCapabilities!.structuredOutputs).toBe(true);

    // Launch descriptor: every field, ADMISSION authority, paths preserved
    // (resolve() may normalize separators/drive; compare case-insensitively on
    // the path tail exactly as the loader's own fallback compare does).
    const launch = identity!.launch!;
    expect(launch.authorityKind).toBe("ADMISSION");
    expect(launch.mode).toBe("INTERACTIVE");
    expect(launch.pythonExecutable).toBe("python");
    const tail = (p: string) => p.replace(/\\/g, "/").toLowerCase();
    expect(tail(launch.checkpointDir)).toEndWith(tail(LAUNCH.checkpoint_dir));
    if (launch.authorityKind === "ADMISSION") {
      expect(tail(launch.modelConfigPath)).toEndWith(tail(LAUNCH.model_config_path));
      expect(tail(launch.runManifestPath)).toEndWith(tail(MANIFEST_PATH));
      expect(tail(launch.trustedVerifierRegistryPath)).toEndWith(tail(REGISTRY_PATH));
    }
    expect(tail(launch.serverPath)).toEndWith(tail(LAUNCH.server_path));
    expect(tail(launch.tokenizerPath)).toEndWith(tail(LAUNCH.tokenizer_path));
  });

  it("POSITIVE: the loaded identity round-trips resolveModelSeat's DEFAULT invocation as the OWNED seat, byte-identical", () => {
    const identity = loadAdmittedIdentity()!;

    // DEFAULT invocation: no --reference-seat flag, no reference env, no
    // gpu-free, no explicit model URL. This is the seat the goal directive
    // names as the default; the owned identity must carry it unchanged.
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hi"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: identity,
    });
    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("OWNED_ADMITTED");
    expect(decision.source).toBe("owned-manifest");
    // The decision carries the SAME identity object -- not a re-derived copy.
    expect(decision.ownedIdentity).toBe(identity);
    // An owned decision never carries a reference-model identity.
    expect(decision.referenceModelName).toBeUndefined();

    // Field-by-field through the decision, against the named source values.
    expect(decision.ownedIdentity!.checkpointSha256).toBe(CHECKPOINT_SHA256);
    expect(decision.ownedIdentity!.endpointUrl).toBe(ENDPOINT_URL);
    expect(decision.ownedIdentity!.identityUrl).toBe(IDENTITY_URL);
    expect(decision.ownedIdentity!.modelConfigSha256).toBe(MODEL_CONFIG_SHA256);
    expect(decision.ownedIdentity!.modelFormat).toBe(MODEL_FORMAT);
    expect(decision.ownedIdentity!.modelName).toBe(MODEL_NAME);
    expect(decision.ownedIdentity!.serverSourceSha256).toBe(SERVER_SOURCE_SHA256);
    expect(decision.ownedIdentity!.tokenizerSha256).toBe(TOKENIZER_SHA256);
  });

  it("POSITIVE: selectedModelContract presents the owned identity unrelabeled, with capability bound to the exact served hash", () => {
    const identity = loadAdmittedIdentity()!;
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hi"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: identity,
    });

    const contract = selectedModelContract(decision);
    expect(contract).toBeDefined();
    // The final consumer surface: seat stays OWNED_ADMITTED, the model name is
    // the admitted name -- never relabeled, never prefixed REFERENCE_ONLY.
    expect(contract!.seat).toBe("OWNED_ADMITTED");
    const owned = contract as OwnedModelContract;
    expect(owned.modelName).toBe(MODEL_NAME);
    expect(owned.modelName.startsWith("REFERENCE_ONLY:")).toBe(false);
    // The served config hash survives to the contract verbatim.
    expect(owned.modelConfigSha256).toBe(MODEL_CONFIG_SHA256);
    // Capability credit is granted -- and only because the declaration is
    // bound to EXACTLY the served hash (the borrowed twin proves the negative).
    expect(owned.structuredOutputs).toBe(true);
  });

  it("NEGATIVE: an explicit model URL matching the admitted endpoint does not redirect or relabel the owned seat", () => {
    const identity = loadAdmittedIdentity()!;
    // Same endpoint, trailing slash: normalization is permitted, redirection
    // and relabeling are not.
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hi"],
      explicitModelUrl: ENDPOINT_URL + "/",
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: identity,
    });
    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("OWNED_ADMITTED");
    expect(decision.ownedIdentity).toBe(identity);

    const contract = selectedModelContract(decision)!;
    expect(contract.seat).toBe("OWNED_ADMITTED");
    expect(contract.modelName).toBe(MODEL_NAME);
    expect(contract.modelConfigSha256).toBe(MODEL_CONFIG_SHA256);
  });
});
