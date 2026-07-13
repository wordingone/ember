// goal_id: EMBER-01
// workstream_id: EMBER-01A
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
