// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/benchmark.test.ts — unit tests for /benchmark status|list|run.

import { describe, it, expect } from "bun:test";
import {
  createBenchmarkCommand,
  renderBenchmarkTable,
  _loadBenchmarkRegistry,
  type BenchmarkRegistry,
} from "./benchmark.ts";
import type { CommandContext } from "../types/command-types.ts";

const mockCtx: CommandContext = {
  sessionId: "test-session",
  mode: "test",
  cwd: "/test",
};

const VALID_REGISTRY: BenchmarkRegistry = {
  authority: {
    goal_id: "EMBER-01",
    workstream_id: "EMBER-01B",
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
  },
  schema: "ember-01-benchmark-registry-v1",
  direct_recovered_minimum: 13,
  operator_recollection_minimum: 15,
  completion_rule: "exact allowed benchmark, official/comparable boundary",
  benchmarks: [
    {
      benchmark_id: "swe-bench-pro",
      display_name: "SWE-Bench Pro",
      version: "unresolved",
      provenance_class: "direct_mandate",
      subject_requirement: "owned_admissible_ember_checkpoint",
      harness_status: "research_stub",
      data_status: "unresolved",
      license_status: "unresolved",
      execution_status: "not_executed",
      subject_class: "none",
      completion: false,
      evidence: ["repo:GOAL.md"],
      split: "unresolved",
      harness_path: null,
      harness_identity: null,
      comparator_requirements: {
        owned_subject_required: true,
        borrowed_reference_role: "frozen_reference_only",
        lineage_signal_allowed: false,
      },
      lineage_admissibility: "owned_subject_only",
      completion_eligibility: "ineligible_until_exact_owned_execution",
    },
    {
      benchmark_id: "automationbench",
      display_name: "AutomationBench",
      version: "git-eda214109cf891ebe8102ca826b87fb98911e103",
      provenance_class: "direct_mandate",
      subject_requirement: "owned_admissible_ember_checkpoint",
      harness_status: "present_but_historical_subject_and_borrowed_default",
      data_status: "checkout_present_unverified",
      license_status: "local_license_present_unadjudicated",
      execution_status: "not_executed",
      subject_class: "none",
      completion: false,
      evidence: ["bench:AutomationBench/ab_config_2.2b.ps1"],
      split: "unresolved",
      harness_path: "bench:AutomationBench/ab_config_2.2b.ps1",
      harness_identity: { algorithm: "sha256-byte-stream-v1", value: "bd4a" },
      comparator_requirements: {
        owned_subject_required: true,
        borrowed_reference_role: "frozen_reference_only",
        lineage_signal_allowed: false,
      },
      lineage_admissibility: "owned_subject_only",
      completion_eligibility: "ineligible_until_exact_owned_execution",
    },
  ],
};

function makeReader(payload: string): (path: string) => string {
  return () => payload;
}

describe("/benchmark status|list|run", () => {
  describe("registration", () => {
    it("has name 'benchmark' and is enabled", () => {
      const cmd = createBenchmarkCommand();
      expect(cmd.name).toBe("benchmark");
      expect(cmd.isEnabled()).toBe(true);
      expect(cmd.description.toLowerCase()).toContain("benchmark");
    });
  });

  describe("positive render of a valid registry", () => {
    it("renders a per-benchmark table for 'list' (default subcommand)", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const result = await cmd.execute("", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBeUndefined();
      expect(result?.message).toContain("swe-bench-pro");
      expect(result?.message).toContain("automationbench");
      expect(result?.message).toContain("research_stub");
      expect(result?.message).toContain("ineligible_until_exact_owned_execution");
      expect(result?.message).toContain("2 benchmark(s)");
    });

    it("'status' and 'list' render identically", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const viaStatus = await cmd.execute("status", mockCtx);
      const viaList = await cmd.execute("list", mockCtx);

      expect(viaStatus?.message).toBe(viaList?.message);
    });

    it("renderBenchmarkTable includes all required columns", () => {
      const table = renderBenchmarkTable(VALID_REGISTRY);
      expect(table).toContain("benchmark_id");
      expect(table).toContain("harness_status");
      expect(table).toContain("data_status");
      expect(table).toContain("license_status");
      expect(table).toContain("execution_status");
      expect(table).toContain("completion");
      expect(table).toContain("completion_eligibility");
    });
  });

  describe("fail-closed: never a fake-empty pass", () => {
    it("exits 1 with a clear message when the registry file is missing/unreadable", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/does-not-exist.json",
        readRegistryFile: () => {
          throw new Error("ENOENT: no such file or directory");
        },
      });

      const result = await cmd.execute("list", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("error:");
      expect(result?.message).toContain("registry unavailable");
    });

    it("exits 1 with a clear message when the registry is malformed JSON", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader("{ not valid json"),
      });

      const result = await cmd.execute("list", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("error:");
    });

    it("exits 1 when the registry JSON is missing the benchmarks array", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify({ schema: "v1" })),
      });

      const result = await cmd.execute("list", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain('"benchmarks" array');
    });

    it("_loadBenchmarkRegistry rejects a row missing benchmark_id (never a partial row)", () => {
      const malformed = { schema: "v1", benchmarks: [{ harness_status: "research_stub", completion: false }] };
      const loaded = _loadBenchmarkRegistry(
        "/fake/path.json",
        makeReader(JSON.stringify(malformed)),
      );
      expect(loaded.ok).toBe(false);
      if (!loaded.ok) {
        expect(loaded.error).toContain("benchmark_id");
      }
    });
  });

  describe("run subcommand: truthful not-executed report, never fakes a harness run", () => {
    it("reports not_executed with the row's harness_status for a stub row", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const result = await cmd.execute("run swe-bench-pro", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toBe("swe-bench-pro: not_executed: harness is research_stub");
      expect(result?.exitCode).toBe(1);
    });

    it("reports the exact harness_status string for a non-stub row too", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const result = await cmd.execute("run automationbench", mockCtx);

      expect(result?.message).toBe(
        "automationbench: not_executed: harness is present_but_historical_subject_and_borrowed_default",
      );
      expect(result?.exitCode).toBe(1);
    });

    it("errors on an unknown benchmark_id", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const result = await cmd.execute("run nonexistent-bench", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("unknown benchmark_id");
    });

    it("errors on a missing benchmark_id argument", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const result = await cmd.execute("run", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("usage: /benchmark run");
    });

    it("run also fails closed when the registry itself is unreadable", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/does-not-exist.json",
        readRegistryFile: () => {
          throw new Error("ENOENT");
        },
      });

      const result = await cmd.execute("run swe-bench-pro", mockCtx);

      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("registry unavailable");
    });
  });

  describe("unknown subcommand", () => {
    it("returns a usage line for an unrecognized subcommand", async () => {
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      const result = await cmd.execute("bogus", mockCtx);

      expect(result?.message).toContain("usage: /benchmark status|list|run");
    });
  });

  describe("read-only: no mutation", () => {
    it("never touches process.env", async () => {
      const before = { ...process.env };
      const cmd = createBenchmarkCommand({
        registryPath: "/fake/benchmark-registry.json",
        readRegistryFile: makeReader(JSON.stringify(VALID_REGISTRY)),
      });

      await cmd.execute("list", mockCtx);

      expect(process.env).toEqual(before);
    });
  });
});
