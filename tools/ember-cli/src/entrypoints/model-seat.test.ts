// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import {
  isModelFreeFastPath,
  referenceSeatModelName,
  resolveModelSeat,
} from "./model-seat.ts";

describe("ember-cli model seat authority", () => {
  it("exempts diagnostics but never exempts the MCP server from seat gating", () => {
    expect(isModelFreeFastPath(["node", "ember", "--help"])).toBe(true);
    expect(isModelFreeFastPath(["node", "ember", "--version"])).toBe(true);
    expect(isModelFreeFastPath(["node", "ember", "gh", "doctor"])).toBe(true);
    expect(isModelFreeFastPath(["node", "ember", "--mcp"])).toBe(false);
    expect(
      isModelFreeFastPath(["node", "ember", "--reference-seat", "--mcp"]),
    ).toBe(false);
  });

  it("fails closed when ordinary launch has no admitted owned identity", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
    });

    expect(decision.allowed).toBe(false);
    expect(decision.seat).toBeNull();
    expect(decision.error).toContain("no admitted owned Ember identity");
  });

  it("selects a verified owned identity for ordinary launch", () => {
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

    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("OWNED_ADMITTED");
    expect(decision.source).toBe("owned-manifest");
    expect(decision.ownedIdentity?.checkpointSha256).toBe("a".repeat(64));
  });

  it("does not let an explicit endpoint override an admitted owned identity", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: "http://127.0.0.1:9999",
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
      },
    });

    expect(decision.allowed).toBe(false);
    expect(decision.error).toContain("does not match the admitted owned endpoint");
  });

  it("keeps explicit reference testing separate from an available owned identity", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      explicitModelUrl: "http://127.0.0.1:9999",
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
      ownedIdentity: {
        checkpointSha256: "c".repeat(64),
        endpointUrl: "http://127.0.0.1:8083",
        identityUrl: "http://127.0.0.1:8083/v1/models",
        modelConfigSha256: "d".repeat(64),
        serverSourceSha256: "e".repeat(64),
        tokenizerSha256: "f".repeat(64),
        modelName: "ember-owned:c" + "c".repeat(11),
      },
    });

    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("REFERENCE_ONLY");
    expect(decision.source).toBe("flag");
  });

  it("allows an explicit --reference-seat and strips it before downstream parsing", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      explicitModelUrl: undefined,
      gpuFreeRequested: false,
      referenceSeatEnv: undefined,
    });

    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("REFERENCE_ONLY");
    expect(decision.source).toBe("flag");
    expect(decision.argv).toEqual(["node", "ember", "-p", "hello"]);
  });

  it("allows an explicit EMBER_REFERENCE_SEAT=1 automation signal", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember", "-p", "hello"],
      explicitModelUrl: "http://localhost:8081",
      gpuFreeRequested: false,
      referenceSeatEnv: "1",
    });

    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("REFERENCE_ONLY");
    expect(decision.source).toBe("env");
  });

  it("allows offline observation when GPU-free is requested without an explicit model URL", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember"],
      explicitModelUrl: undefined,
      gpuFreeRequested: true,
      referenceSeatEnv: undefined,
    });

    expect(decision.allowed).toBe(true);
    expect(decision.seat).toBe("OFFLINE");
  });

  it("does not let GPU-free launder an explicit endpoint into an owned seat", () => {
    const decision = resolveModelSeat({
      argv: ["node", "ember"],
      explicitModelUrl: "http://localhost:8081",
      gpuFreeRequested: true,
      referenceSeatEnv: undefined,
    });

    expect(decision.allowed).toBe(false);
    expect(decision.error).toContain("--reference-seat");
  });

  it("makes the reference identity visible and idempotent", () => {
    expect(referenceSeatModelName("qwen3.6-27b")).toBe(
      "REFERENCE_ONLY: qwen3.6-27b",
    );
    expect(referenceSeatModelName("REFERENCE_ONLY: qwen3.6-27b")).toBe(
      "REFERENCE_ONLY: qwen3.6-27b",
    );
    expect(referenceSeatModelName(undefined)).toBe(
      "REFERENCE_ONLY: unidentified-model",
    );
  });
});
