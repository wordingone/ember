// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compaction-wiring.test.ts -- #2372: the production entrypoints feed compaction the
// server's n_ctx and reach the engine for /compact. Pins the seams, not the math.

import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { microcompactBudgetForContext } from "./compaction.ts";

const SRC = resolve(import.meta.dir, "..");
const read = (rel: string): string => readFileSync(join(SRC, rel), "utf8");

describe("compaction wiring (#2372)", () => {
  it("session-init publishes the probed n_ctx and sizes microcompact from it", () => {
    const src = read("entrypoints/session-init.ts");
    expect(src).toContain("setContextWindowTokens(nCtx);");
    expect(src).toContain("buildProductionMicrocompact(nCtx)");
    expect(src).toContain("microcompactBudgetForContext(nCtx)");
    expect(src).toContain("setContextWindowTokens(null);"); // test reset
  });

  it("the engine reads the published n_ctx when no explicit one is configured", () => {
    const src = read("core/query-engine.ts");
    expect(src).toContain("n ?? getContextWindowTokens()");
  });

  it("the REPL registers the session control /compact uses and supplies standing instructions", () => {
    const src = read("screens/repl.ts");
    expect(src).toContain("setSessionControl({");
    expect(src).toContain("return engine.compact(instructions);");
    expect(src).toContain("compactInstructions: () => loadStandingCompactInstructions({ cwd })");
    expect(src).toContain("consumePostCompactionDetail()");
  });

  it("models.json autoCompactFraction reaches the environment", () => {
    const src = read("entrypoints/process-entry.ts");
    expect(src).toContain('process.env["EMBER_AUTO_COMPACT_FRACTION"] ??= String(cfg.autoCompactFraction)');
  });

  it("microcompact stays out of the way on a large window: 90% of n_ctx, never below 24,000", () => {
    expect(microcompactBudgetForContext(262144)).toBe(Math.floor(262144 * 0.9));
    expect(microcompactBudgetForContext(8192)).toBe(24000);
  });
});
