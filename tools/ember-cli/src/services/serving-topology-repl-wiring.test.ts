import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

test("the live REPL owns one headless-safe topology poller and surfaces its durable alarm", () => {
  const repoRoot = process.env["EMBER_ISSUE1282_REPO_ROOT"]
    ?? resolve(import.meta.dir, "../../../..");
  const source = readFileSync(
    join(repoRoot, "tools", "ember-cli", "src", "screens", "repl.ts"),
    "utf8",
  );
  expect(source).toContain(
    'import { createLiveServingTopologyService } from "../services/serving-topology-live.ts";',
  );
  expect(source).toContain("// #1282 C2: the native cockpit owns the serving-topology cadence.");
  expect(source).toContain('alarmPath: emberStatePath(repoRoot, "serving-alarms.jsonl")');
  expect(source).toContain("topologyService.start();");
  expect(source).toContain("return () => topologyService?.stop();");
  expect(source).toContain("notifyOperator: (alarm) => {");
  expect(source).toContain("[serving-topology] unregistered=");
});

test("the CURRENT topology spec binds every added production consumer", () => {
  const repoRoot = process.env["EMBER_ISSUE1282_REPO_ROOT"]
    ?? resolve(import.meta.dir, "../../../..");
  const spec = readFileSync(
    join(repoRoot, "tools", "ember-cli", "specs", "serving-topology-drift.md"),
    "utf8",
  );
  expect(spec).toContain("Status: CURRENT");
  for (const path of [
    "src/ember/infrastructure/tools/ember-cli/src/services/serving-topology-drift.ts",
    "src/ember/infrastructure/tools/ember-cli/src/services/serving-topology-census.ts",
    "src/ember/infrastructure/tools/ember-cli/src/services/serving-topology-live.ts",
  ]) {
    expect(spec).toContain(`Consumer: \`${path}\``);
  }
});
