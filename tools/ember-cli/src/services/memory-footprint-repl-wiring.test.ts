import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

test("the live REPL owns one capture-safe external memory supervisor lifecycle", () => {
  const repoRoot = process.env["EMBER_ISSUE1282_REPO_ROOT"]
    ?? resolve(import.meta.dir, "../../../..");
  const source = readFileSync(
    join(repoRoot, "tools", "ember-cli", "src", "screens", "repl.ts"),
    "utf8",
  );
  expect(source).toContain(
    'import { createCockpitMemoryFootprintSupervisor } from "../services/memory-footprint-cockpit.ts";',
  );
  expect(source).toContain("if (isHeadlessCapture()) return;");
  expect(source).toContain("const repoRoot = resolveEmberRepoRoot({});");
  expect(source).toContain('receiptPath: emberStatePath(repoRoot, "memory-footprint-trips.jsonl")');
  expect(source).toContain("supervisor.start();");
  expect(source).toContain("return () => supervisor?.stop();");
});

test("the CURRENT spec binds every added production consumer", () => {
  const repoRoot = process.env["EMBER_ISSUE1282_REPO_ROOT"]
    ?? resolve(import.meta.dir, "../../../..");
  const spec = readFileSync(
    join(repoRoot, "tools", "ember-cli", "specs", "memory-footprint-governor.md"),
    "utf8",
  );
  expect(spec).toContain("Status: CURRENT");
  for (const path of [
    "src/ember/infrastructure/tools/ember-cli/src/services/memory-footprint-governor.ts",
    "src/ember/infrastructure/tools/ember-cli/src/services/process-memory-census.ts",
    "src/ember/infrastructure/tools/ember-cli/src/services/memory-footprint-service.ts",
    "src/ember/infrastructure/tools/ember-cli/src/services/memory-footprint-live.ts",
    "src/ember/infrastructure/tools/ember-cli/src/services/memory-footprint-cockpit.ts",
  ]) {
    expect(spec).toContain(`Consumer: \`${path}\``);
  }
});
