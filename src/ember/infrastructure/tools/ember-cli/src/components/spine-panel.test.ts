// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/spine-panel.test.ts — unit tests for the /spine (B5.5 operator spine
// panel) command. RED-first, per PR948's execution-binding test class: every
// positive case proves the element's line content changes when its INJECTED real
// source is mutated (a hardcoded literal in the implementation would make these
// fail, because the assertion targets the exact mutated value); every negative case
// proves an absent/mutated source renders the honest BLOCKED/OFFLINE reason instead
// of silently succeeding or throwing.

import { describe, it, expect } from "bun:test";
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  assembleAuthorityElement,
  assembleSeatElement,
  assembleCustodyLegElement,
  assembleLaunchPacketElement,
  assembleBenchmarkElement,
  assembleFailureClassElement,
  assembleClaimScopeElement,
  assembleSpinePanelState,
  renderSpinePanel,
  renderSpineElement,
  driveSpineElement,
  createSpinePanelCommand,
} from "./spine-panel.ts";
import { resolveEmberRepoRoot } from "../utils/repo-root.ts";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import type { ModelSeatDecision } from "../entrypoints/model-seat.ts";
import type { RootBindingsStore } from "../services/custody-bindings.ts";
import type { EmberWorldState } from "../../../../../../../tools/ember-cli/src/core/ember-world-state.ts";

const mockCtx: CommandContext = { sessionId: "test-session", mode: "test", cwd: "/test" };

function makeBenchmarkRegistryJson(overrides: {
  goalId?: string;
  nextOutcome?: string;
  executedCount?: number;
  totalRows?: number;
} = {}): string {
  const totalRows = overrides.totalRows ?? 3;
  const executedCount = overrides.executedCount ?? 0;
  const benchmarks = Array.from({ length: totalRows }, (_, i) => ({
    benchmark_id: `bench-${i}`,
    display_name: `Bench ${i}`,
    version: "v1",
    provenance_class: "direct_mandate",
    subject_requirement: "owned_admissible_ember_checkpoint",
    harness_status: "research_stub",
    data_status: "unresolved",
    license_status: "unresolved",
    execution_status: i < executedCount ? "executed" : "not_executed",
    subject_class: "none",
    completion: false,
    evidence: ["repo:docs/domains/governance/authority/GOAL.md"],
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
  }));
  return JSON.stringify({
    authority: {
      goal_id: overrides.goalId ?? "EMBER-01",
      workstream_id: "EMBER-01B",
      next_executed_outcome:
        overrides.nextOutcome ?? "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    },
    schema: "ember-01-benchmark-registry-v1",
    direct_recovered_minimum: 1,
    operator_recollection_minimum: 1,
    completion_rule: "test",
    benchmarks,
  });
}

// ---------------------------------------------------------------------------
// Element 1 -- current authority + next executed outcome
// ---------------------------------------------------------------------------

describe("assembleAuthorityElement (element 1)", () => {
  it("BOUND: renders the authority block from the real registry file, call-count 1", () => {
    let calls = 0;
    const el = assembleAuthorityElement("/repo", {
      readAuthorityFile: (path) => {
        calls += 1;
        expect(path.replace(/\\/g, "/")).toContain("manifests/ember-01-custody/benchmark-registry.json");
        return makeBenchmarkRegistryJson({ goalId: "EMBER-01", nextOutcome: "outcome-A" });
      },
    });
    expect(calls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("goal_id: EMBER-01");
    expect(el.lines.join("\n")).toContain("next_executed_outcome: outcome-A");
  });

  it("mutating the source changes the rendered value (proves binding, not a literal)", () => {
    const elA = assembleAuthorityElement("/repo", {
      readAuthorityFile: () => makeBenchmarkRegistryJson({ nextOutcome: "outcome-A" }),
    });
    const elB = assembleAuthorityElement("/repo", {
      readAuthorityFile: () => makeBenchmarkRegistryJson({ nextOutcome: "outcome-B" }),
    });
    expect(elA.lines.join("\n")).toContain("outcome-A");
    expect(elB.lines.join("\n")).toContain("outcome-B");
    expect(elA.lines.join("\n")).not.toEqual(elB.lines.join("\n"));
  });

  it("BLOCKED: an absent registry file shows the honest blocked reason, never a placeholder", () => {
    const el = assembleAuthorityElement("/repo", {
      readAuthorityFile: () => {
        throw new Error("ENOENT: no such file");
      },
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED");
    expect(el.lines.join("\n")).not.toContain("goal_id: EMBER-01");
  });
});

// ---------------------------------------------------------------------------
// Element 2 -- current checkpoint + seat identity
// ---------------------------------------------------------------------------

const OWNED_DECISION: ModelSeatDecision = {
  allowed: true,
  seat: "OWNED_ADMITTED",
  source: "owned-manifest",
  argv: ["node", "ember"],
  ownedIdentity: {
    checkpointSha256: "a".repeat(64),
    endpointUrl: "http://127.0.0.1:8083",
    identityUrl: "http://127.0.0.1:8083/v1/models",
    modelConfigSha256: "d".repeat(64),
    serverSourceSha256: "e".repeat(64),
    tokenizerSha256: "f".repeat(64),
    modelName: "ember-owned:a" + "a".repeat(11),
    launch: {
      pythonExecutable: "python",
      serverPath: "/repo/server.py",
      checkpointDir: "/repo/checkpoints/rung-7",
      tokenizerPath: "/repo/tokenizer.json",
      mode: "INTERACTIVE",
      authorityKind: "ADMISSION",
      modelConfigPath: "/repo/model-config.json",
      runManifestPath: "/repo/run-manifest.json",
      trustedVerifierRegistryPath: "/repo/trusted-verifiers.json",
    },
  },
};

const OFFLINE_DECISION: ModelSeatDecision = {
  allowed: true,
  seat: "OFFLINE",
  source: "gpu-free",
  argv: ["node", "ember"],
};

describe("assembleSeatElement (element 2)", () => {
  it("BOUND: renders checkpoint sha from the injected seat decision, call-count 1", () => {
    let calls = 0;
    const el = assembleSeatElement({
      getModelSeatDecision: () => {
        calls += 1;
        return OWNED_DECISION;
      },
    });
    expect(calls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("a".repeat(64));
  });

  it("mutating the checkpoint sha changes the rendered value", () => {
    const elA = assembleSeatElement({ getModelSeatDecision: () => OWNED_DECISION });
    const mutated: ModelSeatDecision = {
      ...OWNED_DECISION,
      ownedIdentity: { ...OWNED_DECISION.ownedIdentity!, checkpointSha256: "b".repeat(64) },
    };
    const elB = assembleSeatElement({ getModelSeatDecision: () => mutated });
    expect(elA.lines.join("\n")).not.toEqual(elB.lines.join("\n"));
    expect(elB.lines.join("\n")).toContain("b".repeat(64));
  });

  it("OFFLINE: the genuinely-offline seat shows OFFLINE honestly (allowed, per spec L1653)", () => {
    const el = assembleSeatElement({ getModelSeatDecision: () => OFFLINE_DECISION });
    expect(el.status).toBe("OFFLINE");
    expect(el.lines.join("\n")).toContain("custody: OFFLINE");
  });

  it("BLOCKED: a seat-resolution throw shows the honest blocked reason", () => {
    const el = assembleSeatElement({
      getModelSeatDecision: () => {
        throw new Error("subprocess crash");
      },
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED");
  });
});

// ---------------------------------------------------------------------------
// Element 3 -- custody-leg state + persisted logical roots
// ---------------------------------------------------------------------------

function makeRootSpecJson(rootIds: string[]): string {
  return JSON.stringify({
    authority: { goal_id: "EMBER-01", workstream_id: "EMBER-01B", next_executed_outcome: "x" },
    schema: "ember-01-root-spec-v1",
    path_policy: "test",
    roots: rootIds.map((id) => ({ root_id: id, binding: `EMBER_${id.toUpperCase()}_ROOT`, required: true })),
  });
}

describe("assembleCustodyLegElement (element 3)", () => {
  it("BOUND: declared-vs-bound counts come from the real spec + real bindings store", () => {
    let specCalls = 0;
    let bindingsCalls = 0;
    const el = assembleCustodyLegElement("/repo", {
      readRootSpecFile: () => {
        specCalls += 1;
        return makeRootSpecJson(["root-a", "root-b", "root-c"]);
      },
      readRootBindingsStoreFn: (repoRoot) => {
        bindingsCalls += 1;
        expect(repoRoot).toBe("/repo");
        const store: RootBindingsStore = {
          roots: { "root-a": { root_id: "root-a", machine_path: "C:/a", binding_env: "EMBER_ROOT_A_ROOT" } },
        };
        return store;
      },
    });
    expect(specCalls).toBe(1);
    expect(bindingsCalls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("roots declared: 3");
    expect(el.lines.join("\n")).toContain("roots bound: 1");
  });

  it("mutating the bindings store changes the bound count (proves binding, not a literal)", () => {
    const specFile = () => makeRootSpecJson(["root-a", "root-b"]);
    const elNone = assembleCustodyLegElement("/repo", {
      readRootSpecFile: specFile,
      readRootBindingsStoreFn: () => ({ roots: {} }),
    });
    const elOne = assembleCustodyLegElement("/repo", {
      readRootSpecFile: specFile,
      readRootBindingsStoreFn: () => ({
        roots: { "root-a": { root_id: "root-a", machine_path: "C:/a", binding_env: "X" } },
      }),
    });
    expect(elNone.lines.join("\n")).toContain("roots bound: 0");
    expect(elOne.lines.join("\n")).toContain("roots bound: 1");
    expect(elNone.lines.join("\n")).not.toEqual(elOne.lines.join("\n"));
  });

  it("BLOCKED: an absent root-spec shows the honest blocked reason", () => {
    const el = assembleCustodyLegElement("/repo", {
      readRootSpecFile: () => {
        throw new Error("ENOENT");
      },
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED");
  });

  // PR #1027 defect fix: the root-spec read was already wrapped fail-closed, but the
  // bindings-store read after it was not -- a throwing readRootBindingsStoreFn used to
  // propagate straight out of assembleCustodyLegElement and crash the whole /spine
  // command instead of blocking element 3 alone. readRootBindingsStore's own default
  // implementation (services/custody-bindings.ts) is deliberately fail-open and does
  // not throw on a missing/malformed real store file, so there is no genuine fs
  // failure to reach through the production readFileSync path here; the injected
  // readRootBindingsStoreFn is the actual extension seam this component's own
  // Element3Deps exposes, and the malformed/missing-store scenario is exercised
  // through it, matching this file's existing element-3 convention throughout.
  it("BLOCKED: a bindings-store read failure blocks element 3 alone, never throws out of assembleCustodyLegElement", () => {
    const el = assembleCustodyLegElement("/repo", {
      readRootSpecFile: () => makeRootSpecJson(["root-a"]),
      readRootBindingsStoreFn: () => {
        throw new Error("root-bindings store: EACCES permission denied");
      },
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED");
    expect(el.lines[0]).toContain("root-bindings store");
  });

  it("BLOCKED element 3 does not crash /spine -- the other 6 elements still render", async () => {
    const state = await assembleSpinePanelState("/cwd", {
      resolveRepoRoot: () => "/repo",
      readAuthorityFile: () => makeBenchmarkRegistryJson({}),
      getModelSeatDecision: () => OFFLINE_DECISION,
      readRootSpecFile: () => makeRootSpecJson(["root-a"]),
      readRootBindingsStoreFn: () => {
        throw new Error("simulated bindings-store crash");
      },
      listLaunchPacketReceipts: () => [],
      readBenchmarkRegistryFile: () => makeBenchmarkRegistryJson({}),
      existsC0Ledger: () => false,
      goalforgeRoot: "",
    });
    expect(state.elements.map((e) => e.n)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    const el3 = state.elements.find((e) => e.n === 3)!;
    expect(el3.status).toBe("BLOCKED");
    expect(el3.lines[0]).toContain("root-bindings store");
    // every other element still assembled normally -- per-element isolation.
    const el1 = state.elements.find((e) => e.n === 1)!;
    expect(el1.status).toBe("BOUND");
    const el7 = state.elements.find((e) => e.n === 7)!;
    expect(el7.status).toBe("BLOCKED"); // unconfigured goalforgeRoot, expected honest state
    expect(el7.lines[0]).toContain("world-state source not configured");
  });
});

// ---------------------------------------------------------------------------
// Element 4 -- launch-packet state
// ---------------------------------------------------------------------------

describe("assembleLaunchPacketElement (element 4)", () => {
  it("BOUND: reads the newest receipt directory's summary record", () => {
    let listCalls = 0;
    let readCalls = 0;
    const el = assembleLaunchPacketElement("/repo", {
      listLaunchPacketReceipts: (dirPath) => {
        listCalls += 1;
        expect(dirPath.replace(/\\/g, "/")).toContain("receipts/ember-01-launch-packet");
        return ["20260101T000000Z", "20260201T000000Z"];
      },
      readLaunchPacketReceipt: (path) => {
        readCalls += 1;
        expect(path.replace(/\\/g, "/")).toContain("20260201T000000Z");
        return [
          JSON.stringify({ record: "preflight", name: "p1", status: "pass" }),
          JSON.stringify({
            record: "launch-packet-summary",
            overall_ready: true,
            implemented_all_pass: true,
            any_deferred: false,
            named_ember02_command: { command: "python run_vertical_slice.py --semantic" },
          }),
        ].join("\n");
      },
    });
    expect(listCalls).toBe(1);
    expect(readCalls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("overall_ready: true");
    expect(el.lines.join("\n")).toContain("run_vertical_slice.py");
  });

  it("mutating overall_ready changes the rendered value", () => {
    const list = () => ["20260101T000000Z"];
    const readReady = () =>
      JSON.stringify({
        record: "launch-packet-summary",
        overall_ready: true,
        implemented_all_pass: true,
        any_deferred: false,
        // overall_ready===true requires a real named command (closed-schema invariant,
        // PR #1027 round-2) -- null here would make this fixture itself invalid.
        named_ember02_command: { command: "python run_vertical_slice.py --semantic" },
      });
    const readNotReady = () =>
      JSON.stringify({ record: "launch-packet-summary", overall_ready: false, implemented_all_pass: false, any_deferred: false, named_ember02_command: null });
    const elReady = assembleLaunchPacketElement("/repo", { listLaunchPacketReceipts: list, readLaunchPacketReceipt: readReady });
    const elNotReady = assembleLaunchPacketElement("/repo", { listLaunchPacketReceipts: list, readLaunchPacketReceipt: readNotReady });
    expect(elReady.lines.join("\n")).toContain("overall_ready: true");
    expect(elNotReady.lines.join("\n")).toContain("overall_ready: false");
    expect(elReady.lines.join("\n")).not.toEqual(elNotReady.lines.join("\n"));
  });

  it("BLOCKED: no receipt directory yet -- exact real repo state today", () => {
    const el = assembleLaunchPacketElement("/repo", { listLaunchPacketReceipts: () => [] });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED: no launch-packet receipt yet");
  });
});

// ---------------------------------------------------------------------------
// Element 4 -- receipt discovery shadowing (PR #1027 defect fix). Production-shaped:
// real directories/files on a real temp filesystem, read through the real default
// readdirSync/readFileSync path (no injected listLaunchPacketReceipts/
// readLaunchPacketReceipt).
// ---------------------------------------------------------------------------

describe("assembleLaunchPacketElement (element 4) -- real-filesystem receipt-discovery shadowing", () => {
  function writeReceipt(dir: string, overallReady: boolean): void {
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "packet.jsonl"),
      JSON.stringify({
        record: "launch-packet-summary",
        overall_ready: overallReady,
        implemented_all_pass: overallReady,
        any_deferred: false,
        named_ember02_command: overallReady ? { command: "python run_vertical_slice.py --semantic" } : null,
      }) + "\n",
      "utf8",
    );
  }

  it("BOUND: a stray non-canonical file/dir sorting after the real receipt is filtered out, real newest receipt selected", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-receipts-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      mkdirSync(receiptsDir, { recursive: true });

      writeReceipt(join(receiptsDir, "20260101T000000Z"), true);

      // Both sort lexicographically AFTER the real receipt but are NOT canonical
      // receipt directories -- a naive readdirSync().sort()-then-last would shadow
      // the real receipt with one of these.
      writeFileSync(join(receiptsDir, "zzz-stray-file.txt"), "not a receipt", "utf8");
      mkdirSync(join(receiptsDir, "zzz-not-canonical"), { recursive: true });
      writeFileSync(join(receiptsDir, "zzz-not-canonical", "packet.jsonl"), "not json at all", "utf8");

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: true");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: the newest canonical receipt dir is empty/unreadable -- falls back to the next-newest VALID receipt, real fs", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-receipts-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      mkdirSync(receiptsDir, { recursive: true });

      writeReceipt(join(receiptsDir, "20260101T000000Z"), false);
      // Newest by name, canonical-shaped, but no packet.jsonl inside it (real ENOENT
      // on read) -- must not crash and must not block when an older valid receipt
      // exists.
      mkdirSync(join(receiptsDir, "20260201T000000Z"), { recursive: true });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: false");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BLOCKED: every canonical receipt dir is invalid -- honest blocked reason, never a crash", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-receipts-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      mkdirSync(join(receiptsDir, "20260101T000000Z"), { recursive: true });
      writeFileSync(join(receiptsDir, "20260101T000000Z", "packet.jsonl"), "not json", "utf8");

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BLOCKED");
      expect(el.lines[0]).toContain("BLOCKED");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// Element 4 -- closed summary schema (re-review, PR #1027 round-2 defect fix).
// The prior fix accepted ANY object carrying record==="launch-packet-summary" as
// valid without checking its fields; a malformed-but-tagged newest receipt was
// assigned and stopped the walk instead of being skipped like an unreadable one.
// Production-shaped: real directories/files on a real temp filesystem.
// ---------------------------------------------------------------------------

describe("assembleLaunchPacketElement (element 4) -- closed summary schema, real filesystem", () => {
  function writeValidReceipt(dir: string, overallReady: boolean): void {
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "packet.jsonl"),
      JSON.stringify({
        record: "launch-packet-summary",
        overall_ready: overallReady,
        implemented_all_pass: overallReady,
        any_deferred: false,
        named_ember02_command: overallReady ? { command: "python run_vertical_slice.py --semantic" } : null,
      }) + "\n",
      "utf8",
    );
  }

  function writeRawSummary(dir: string, summary: Record<string, unknown>): void {
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "packet.jsonl"), JSON.stringify(summary) + "\n", "utf8");
  }

  it("BOUND: newest packet's summary is missing overall_ready -- skipped, falls back to the older VALID receipt (never a false-default BOUND from the malformed newest)", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeValidReceipt(join(receiptsDir, "20260101T000000Z"), true);
      // Newest by name, tagged correctly, but missing overall_ready entirely.
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        implemented_all_pass: true,
        any_deferred: false,
        named_ember02_command: null,
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).not.toContain("20260201T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: true");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: newest packet's overall_ready is wrong-typed (string, not boolean) -- skipped, falls back to the older VALID receipt", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeValidReceipt(join(receiptsDir, "20260101T000000Z"), false);
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        overall_ready: "yes",
        implemented_all_pass: true,
        any_deferred: false,
        named_ember02_command: null,
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: false");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: overall_ready===true with an empty named command is INVALID (the named conditional invariant) -- skipped, falls back to the older VALID receipt", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeValidReceipt(join(receiptsDir, "20260101T000000Z"), false);
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        overall_ready: true,
        implemented_all_pass: true,
        any_deferred: false,
        named_ember02_command: null,
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: false");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: overall_ready===true with a missing named_ember02_command.command is INVALID -- skipped, falls back to the older VALID receipt", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeValidReceipt(join(receiptsDir, "20260101T000000Z"), false);
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        overall_ready: true,
        implemented_all_pass: true,
        any_deferred: false,
        named_ember02_command: {},
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: false");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: overall_ready===false with a non-null command object missing command is INVALID -- skipped, falls back to the older VALID receipt", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeValidReceipt(join(receiptsDir, "20260101T000000Z"), true);
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        overall_ready: false,
        implemented_all_pass: false,
        any_deferred: false,
        named_ember02_command: {},
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).not.toContain("20260201T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: true");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: overall_ready===true with a whitespace-only command is INVALID -- skipped, falls back to the older VALID receipt", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeValidReceipt(join(receiptsDir, "20260101T000000Z"), false);
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        overall_ready: true,
        implemented_all_pass: true,
        any_deferred: false,
        named_ember02_command: { command: " \t " },
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("20260101T000000Z");
      expect(el.lines.join("\n")).not.toContain("20260201T000000Z");
      expect(el.lines.join("\n")).toContain("overall_ready: false");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BLOCKED: ALL candidate receipts have malformed summaries -- honest blocked reason, never a false-default BOUND", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-schema-"));
    try {
      const receiptsDir = join(repoRoot, "receipts", "ember-01-launch-packet");
      writeRawSummary(join(receiptsDir, "20260101T000000Z"), {
        record: "launch-packet-summary",
        overall_ready: true,
        implemented_all_pass: true,
        any_deferred: false,
        // wrong-typed command field
        named_ember02_command: { command: 42 },
      });
      writeRawSummary(join(receiptsDir, "20260201T000000Z"), {
        record: "launch-packet-summary",
        // missing any_deferred
        overall_ready: false,
        implemented_all_pass: false,
      });

      const el = assembleLaunchPacketElement(repoRoot);
      expect(el.status).toBe("BLOCKED");
      expect(el.lines[0]).toContain("BLOCKED");
      expect(el.lines.join("\n")).not.toContain("overall_ready:");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// Element 5 -- benchmark registry + exact non-execution/execution state
// ---------------------------------------------------------------------------

describe("assembleBenchmarkElement (element 5)", () => {
  it("BOUND: executed/total counts come from the real per-row execution_status", () => {
    let calls = 0;
    const el = assembleBenchmarkElement("/repo", {
      readBenchmarkRegistryFile: () => {
        calls += 1;
        return makeBenchmarkRegistryJson({ totalRows: 4, executedCount: 1 });
      },
    });
    expect(calls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("4 benchmark(s)");
    expect(el.lines.join("\n")).toContain("executed: 1 / 4");
  });

  it("mutating execution_status changes the executed count (proves binding, not a literal)", () => {
    const elZero = assembleBenchmarkElement("/repo", {
      readBenchmarkRegistryFile: () => makeBenchmarkRegistryJson({ totalRows: 3, executedCount: 0 }),
    });
    const elTwo = assembleBenchmarkElement("/repo", {
      readBenchmarkRegistryFile: () => makeBenchmarkRegistryJson({ totalRows: 3, executedCount: 2 }),
    });
    expect(elZero.lines.join("\n")).toContain("executed: 0 / 3");
    expect(elTwo.lines.join("\n")).toContain("executed: 2 / 3");
    expect(elZero.lines.join("\n")).not.toEqual(elTwo.lines.join("\n"));
  });

  it("BLOCKED: a malformed registry shows the honest blocked reason, never an empty table", () => {
    const el = assembleBenchmarkElement("/repo", { readBenchmarkRegistryFile: () => "not json" });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED");
  });
});

// ---------------------------------------------------------------------------
// Element 5 -- fail-CLOSED execution_status vocabulary (PR #1027 defect fix)
// production-shaped: opens a real registry fixture on disk through the real
// readFileSync default path (no injected readBenchmarkRegistryFile).
// ---------------------------------------------------------------------------

describe("assembleBenchmarkElement (element 5) -- out-of-vocabulary execution_status fail-closed", () => {
  function fixtureRoot(benchmarks: unknown[]): string {
    const repoRoot = mkdtempSync(join(tmpdir(), "spine-panel-bench-"));
    const dir = join(repoRoot, "manifests", "ember-01-custody");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "benchmark-registry.json"),
      JSON.stringify({
        authority: { goal_id: "EMBER-01", workstream_id: "EMBER-01B", next_executed_outcome: "x" },
        schema: "ember-01-benchmark-registry-v1",
        direct_recovered_minimum: 1,
        operator_recollection_minimum: 1,
        completion_rule: "test",
        benchmarks,
      }),
      "utf8",
    );
    return repoRoot;
  }

  const baseRow = {
    benchmark_id: "bench-bad",
    display_name: "Bench Bad",
    version: "v1",
    provenance_class: "direct_mandate",
    subject_requirement: "owned_admissible_ember_checkpoint",
    harness_status: "research_stub",
    data_status: "unresolved",
    license_status: "unresolved",
    subject_class: "none",
    completion: false,
    evidence: ["repo:docs/domains/governance/authority/GOAL.md"],
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
  };

  it("BLOCKED: an out-of-vocabulary execution_status (e.g. a stray 'failed' or 'unsupported') never counts as executed", () => {
    const repoRoot = fixtureRoot([{ ...baseRow, execution_status: "failed" }]);
    try {
      const el = assembleBenchmarkElement(repoRoot);
      expect(el.status).toBe("BLOCKED");
      expect(el.lines[0]).toContain("bench-bad");
      expect(el.lines[0]).toContain("failed");
      expect(el.lines.join("\n")).not.toContain("executed: 1 / 1");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BLOCKED: a row missing execution_status entirely never silently counts as executed", () => {
    const { execution_status: _drop, ...rowWithoutStatus } = { ...baseRow, execution_status: "not_executed" };
    const repoRoot = fixtureRoot([rowWithoutStatus]);
    try {
      const el = assembleBenchmarkElement(repoRoot);
      expect(el.status).toBe("BLOCKED");
      expect(el.lines[0]).toContain("bench-bad");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });

  it("BOUND: only exact 'executed' rows count, real fixture through the real readFileSync path", () => {
    const repoRoot = fixtureRoot([
      { ...baseRow, benchmark_id: "b0", execution_status: "executed" },
      { ...baseRow, benchmark_id: "b1", execution_status: "not_executed" },
      { ...baseRow, benchmark_id: "b2", execution_status: "not_executed" },
    ]);
    try {
      const el = assembleBenchmarkElement(repoRoot);
      expect(el.status).toBe("BOUND");
      expect(el.lines.join("\n")).toContain("executed: 1 / 3");
    } finally {
      rmSync(repoRoot, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// Element 6 -- failure-class state (C0 ledger, T2.2 dependency)
// ---------------------------------------------------------------------------

describe("assembleFailureClassElement (element 6)", () => {
  it("BLOCKED: ledger absent is the exact honest phrase required by the spec (real repo state today)", () => {
    const el = assembleFailureClassElement("/repo", { existsC0Ledger: () => false });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toBe("BLOCKED: ledger absent");
  });

  it("BOUND once the ledger lands: renders real failure-class rows, call-count 1 each", () => {
    let existsCalls = 0;
    let readCalls = 0;
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => {
        existsCalls += 1;
        return true;
      },
      readC0Ledger: () => {
        readCalls += 1;
        return JSON.stringify({
          classes: [
            { class_id: "cls-training-start", state: "past-dead" },
            { class_id: "cls-worktree-ceiling", state: "past-dead" },
          ],
        });
      },
    });
    expect(existsCalls).toBe(1);
    expect(readCalls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("2 failure class(es)");
    expect(el.lines.join("\n")).toContain("cls-training-start");
  });

  it("mutating the class count changes the rendered value (proves binding, not a literal)", () => {
    const elOne = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ classes: [{ class_id: "a", state: "x" }] }),
    });
    const elTwo = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ classes: [{ class_id: "a", state: "x" }, { class_id: "b", state: "y" }] }),
    });
    expect(elOne.lines.join("\n")).toContain("1 failure class(es)");
    expect(elTwo.lines.join("\n")).toContain("2 failure class(es)");
    expect(elOne.lines.join("\n")).not.toEqual(elTwo.lines.join("\n"));
  });

  // PR #1027 defect fix: `Array.isArray(...) ? ... : []` + `?? "(unnamed)"/"unknown"`
  // rendered a missing/non-array/empty classes array, or rows missing class_id/state,
  // as a fake BOUND "0 failure class(es)" / "(unnamed): unknown" line instead of
  // blocking on the structural violation.
  it("BLOCKED: classes is missing entirely -- never a fake '0 failure class(es)' BOUND line", () => {
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ schema: "x" }),
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("classes");
    expect(el.lines.join("\n")).not.toContain("0 failure class(es)");
  });

  it("BLOCKED: classes is a non-array value -- never a fake '0 failure class(es)' BOUND line", () => {
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ classes: "not-an-array" }),
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("classes");
  });

  it("BLOCKED: classes is an empty array -- never a fake '0 failure class(es)' BOUND line", () => {
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ classes: [] }),
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("classes");
  });

  it("BLOCKED: a row missing class_id never renders as '(unnamed): unknown'", () => {
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ classes: [{ state: "past-dead" }] }),
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("classes[0]");
    expect(el.lines.join("\n")).not.toContain("(unnamed)");
  });

  it("BLOCKED: a row missing state never renders as ': unknown'", () => {
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () => JSON.stringify({ classes: [{ class_id: "cls-x" }] }),
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("classes[0]");
    expect(el.lines.join("\n")).not.toContain(": unknown");
  });

  it("BLOCKED: a second/later row missing class_id/state is named by its own index", () => {
    const el = assembleFailureClassElement("/repo", {
      existsC0Ledger: () => true,
      readC0Ledger: () =>
        JSON.stringify({ classes: [{ class_id: "cls-ok", state: "past-dead" }, { class_id: "", state: "x" }] }),
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("classes[1]");
  });
});

// ---------------------------------------------------------------------------
// Element 6 -- production-shaped, real committed ledger (T2.2 landed;
// defect fix 2026-07-23: T2.1 acceptance leg found the reader keyed on
// failure_classes/status, but the landed ledger (T2.2) uses classes/state.
// This test opens the REAL checked-in manifests/ember-01-custody/
// c0-failure-class-ledger.json bytes and runs them through the real
// production reader (assembleFailureClassElement, no injected deps) -- never
// an in-test-rebuilt fixture -- and asserts on the ledger's real row count.
// ---------------------------------------------------------------------------

describe("assembleFailureClassElement (element 6) -- real committed ledger (T2.2)", () => {
  it("BOUND: reads the real committed ledger through the production path and renders its real row count, never 0", () => {
    const repoRoot = resolveEmberRepoRoot({ startDir: import.meta.dir });
    const ledgerPath = join(repoRoot, "manifests/ember-01-custody/c0-failure-class-ledger.json");
    const real = JSON.parse(readFileSync(ledgerPath, "utf8")) as { classes: Array<{ class_id: string }> };
    const expectedCount = real.classes.length;
    // Guards the test itself against a future empty/absent ledger silently
    // passing a 0-vs-0 comparison -- the committed ledger must have real rows.
    expect(expectedCount).toBeGreaterThan(0);

    const el = assembleFailureClassElement(repoRoot);
    expect(el.status).toBe("BOUND");
    expect(el.lines[0]).toBe(`${expectedCount} failure class(es) recorded`);
    expect(el.lines[0]).not.toBe("0 failure class(es) recorded");
    expect(el.lines.join("\n")).toContain(real.classes[0]!.class_id);
  });
});

// ---------------------------------------------------------------------------
// Element 7 -- claim scope + blocked reasons
// ---------------------------------------------------------------------------

function makeWorldState(overrides: Partial<{ monitorCount: number; understandCount: number }> = {}): EmberWorldState {
  const monitorCount = overrides.monitorCount ?? 2;
  const understandCount = overrides.understandCount ?? 1;
  const evidence = { path: "docs/domains/governance/authority/GOAL.md", sha256: "x".repeat(64) };
  return {
    ts: "2026-01-01T00:00:00.000Z",
    monitor: {
      boardTs: "2026-01-01T00:00:00.000Z",
      total: monitorCount,
      green: monitorCount,
      red: 0,
      pctComplete: 100,
      conditions: Array.from({ length: monitorCount }, (_, i) => ({
        id: `board.c${i}`,
        label: `[${i}] c${i}`,
        detail: "GREEN: ok",
        evidence,
      })),
    },
    understand: {
      goalTitle: "test goal",
      topology: Array.from({ length: understandCount }, (_, i) => ({
        id: `goal.topology.${i}`,
        label: `[${i}] h${i}`,
        detail: `h${i}`,
        evidence,
      })),
    },
    interact: { ledgerRows: [] },
    sources: { goal: evidence, ledger: evidence, board: evidence },
  };
}

describe("assembleClaimScopeElement (element 7)", () => {
  it("BOUND: claim counts come from the real world-state adapter, call-count 1", async () => {
    let calls = 0;
    const el = await assembleClaimScopeElement({
      goalforgeRoot: "/goalforge",
      buildWorldState: async (opts) => {
        calls += 1;
        expect(opts.goalforgeRoot).toBe("/goalforge");
        return makeWorldState({ monitorCount: 3 });
      },
    });
    expect(calls).toBe(1);
    expect(el.status).toBe("BOUND");
    expect(el.lines.join("\n")).toContain("monitor claims: 3");
  });

  it("mutating claim counts changes the rendered value (proves binding, not a literal)", async () => {
    const elA = await assembleClaimScopeElement({
      goalforgeRoot: "/goalforge",
      buildWorldState: async () => makeWorldState({ monitorCount: 1 }),
    });
    const elB = await assembleClaimScopeElement({
      goalforgeRoot: "/goalforge",
      buildWorldState: async () => makeWorldState({ monitorCount: 5 }),
    });
    expect(elA.lines.join("\n")).toContain("monitor claims: 1");
    expect(elB.lines.join("\n")).toContain("monitor claims: 5");
    expect(elA.lines.join("\n")).not.toEqual(elB.lines.join("\n"));
  });

  it("BLOCKED: unconfigured EMBER_GOALFORGE_ROOT shows the honest blocked reason (real default state)", async () => {
    const el = await assembleClaimScopeElement({ goalforgeRoot: "" });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED: world-state source not configured");
  });

  it("BLOCKED: a real adapter failure (missing board receipt) shows the honest blocked reason", async () => {
    const el = await assembleClaimScopeElement({
      goalforgeRoot: "/goalforge",
      buildWorldState: async () => {
        throw new Error("ember-world-state adapter: no board receipt found under /goalforge/scripts/ember_totality/receipts-totality");
      },
    });
    expect(el.status).toBe("BLOCKED");
    expect(el.lines[0]).toContain("BLOCKED");
  });
});

// ---------------------------------------------------------------------------
// Full panel assembly + rendering
// ---------------------------------------------------------------------------

describe("assembleSpinePanelState + renderSpinePanel", () => {
  function fullDeps() {
    return {
      resolveRepoRoot: () => "/repo",
      readAuthorityFile: () => makeBenchmarkRegistryJson({}),
      getModelSeatDecision: () => OFFLINE_DECISION,
      readRootSpecFile: () => makeRootSpecJson(["root-a"]),
      readRootBindingsStoreFn: () => ({ roots: {} }),
      listLaunchPacketReceipts: () => [],
      readBenchmarkRegistryFile: () => makeBenchmarkRegistryJson({}),
      existsC0Ledger: () => false,
      goalforgeRoot: "",
    };
  }

  it("assembles all 7 elements, numbered 1-7 in order", async () => {
    const state = await assembleSpinePanelState("/cwd", fullDeps());
    expect(state.elements.map((e) => e.n)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(state.repoRoot).toBe("/repo");
  });

  it("renderSpinePanel includes every element's label and status", async () => {
    const state = await assembleSpinePanelState("/cwd", fullDeps());
    const rendered = renderSpinePanel(state);
    for (const el of state.elements) {
      expect(rendered).toContain(`[${el.n}] ${el.label}`);
      expect(rendered).toContain(el.status);
    }
  });

  it("renderSpineElement renders a single requested element", async () => {
    const state = await assembleSpinePanelState("/cwd", fullDeps());
    const rendered = renderSpineElement(state, 6);
    expect(rendered).toContain("[6] failure-class state");
    expect(rendered).toContain("BLOCKED: ledger absent");
  });

  it("renderSpineElement reports an out-of-range element honestly", async () => {
    const state = await assembleSpinePanelState("/cwd", fullDeps());
    expect(renderSpineElement(state, 99)).toContain("no such spine element");
  });
});

// ---------------------------------------------------------------------------
// Drive routing -- routes to the EXISTING command (no separate console)
// ---------------------------------------------------------------------------

describe("driveSpineElement", () => {
  function fakeCommand(name: string): RegistryCommand & { calls: string[] } {
    const calls: string[] = [];
    return {
      name,
      description: "fake",
      isEnabled: () => true,
      calls,
      async execute(args: string) {
        calls.push(args);
        return { type: "message" as const, message: `${name} executed with "${args}"` };
      },
    };
  }

  it("routes 'custody' to the real custody command with the given args", async () => {
    const custodyCommand = fakeCommand("custody");
    const result = await driveSpineElement("custody", "status", mockCtx, { custodyCommand });
    expect(custodyCommand.calls).toEqual(["status"]);
    expect(result.type).toBe("message");
    expect((result as { message: string }).message).toContain("custody executed");
  });

  it("routes 'launch-packet' to the real train command", async () => {
    const trainCommand = fakeCommand("train");
    const result = await driveSpineElement("launch-packet", "", mockCtx, { trainCommand });
    expect(trainCommand.calls).toEqual([""]);
    expect((result as { message: string }).message).toContain("train executed");
  });

  it("routes 'benchmark' to the real benchmark command", async () => {
    const benchmarkCommand = fakeCommand("benchmark");
    await driveSpineElement("benchmark", "run bench-0", mockCtx, { benchmarkCommand });
    expect(benchmarkCommand.calls).toEqual(["run bench-0"]);
  });

  it("routes 'cockpit' to the real world-state command", async () => {
    const worldStateCommand = fakeCommand("cockpit");
    await driveSpineElement("cockpit", "monitor", mockCtx, { worldStateCommand });
    expect(worldStateCommand.calls).toEqual(["monitor"]);
  });

  it("an unknown drive target fails closed with a named list of what IS drivable", async () => {
    const result = await driveSpineElement("nonsense", "", mockCtx, {});
    expect(result.exitCode).toBe(1);
    expect((result as { message: string }).message).toContain("no drivable spine element");
  });
});

// ---------------------------------------------------------------------------
// Command factory -- reachable in the running binary via command-registry.ts
// ---------------------------------------------------------------------------

describe("createSpinePanelCommand", () => {
  it("is named 'spine' with alias 'b55', enabled", () => {
    const cmd = createSpinePanelCommand();
    expect(cmd.name).toBe("spine");
    expect(cmd.aliases).toEqual(["b55"]);
    expect(cmd.isEnabled()).toBe(true);
  });

  it("bare execute renders the full panel", async () => {
    const cmd = createSpinePanelCommand({
      resolveRepoRoot: () => "/repo",
      readAuthorityFile: () => makeBenchmarkRegistryJson({}),
      getModelSeatDecision: () => OFFLINE_DECISION,
      readRootSpecFile: () => makeRootSpecJson([]),
      readRootBindingsStoreFn: () => ({ roots: {} }),
      listLaunchPacketReceipts: () => [],
      readBenchmarkRegistryFile: () => makeBenchmarkRegistryJson({}),
      existsC0Ledger: () => false,
      goalforgeRoot: "",
    });
    const result = await cmd.execute("", mockCtx);
    expect(result?.type).toBe("message");
    expect((result as { message: string }).message).toContain("B5.5 Operator Spine");
  });

  it("execute with 'drive <target>' routes instead of rendering the panel", async () => {
    const custodyCommand: RegistryCommand = {
      name: "custody",
      description: "fake",
      isEnabled: () => true,
      execute: async (args) => ({ type: "message" as const, message: `routed:${args}` }),
    };
    const cmd = createSpinePanelCommand({ custodyCommand });
    const result = await cmd.execute("drive custody status", mockCtx);
    expect((result as { message: string }).message).toBe("routed:status");
  });
});
