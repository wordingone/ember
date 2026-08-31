#!/usr/bin/env bun
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// scripts/cobs-proof-pack-run.ts — user-runnable C-OBS observatory proof-pack (gh issue #10,
// condition C-OBS clause (d)).
//
// commands/world-state.ts's own header explains that the original standalone
// `node core/ember-world-state-repl.ts` proof-pack was split apart in a prior change and no
// longer exists; `runWorldStateTurn()` (exported from commands/world-state.ts) is "the only way
// to exercise the adapter today". This script is a thin, user-runnable wrapper around exactly
// that function -- it takes ONE verb (monitor / understand / interact) on argv, drives the real
// adapter + membrane through the same code path the compiled cockpit uses, prints the rendered
// turn, and exits 0 on success / 1 on any thrown error. Three separate invocations (one per verb)
// give three independently-recorded real exit codes, which is what test_c_obs.py's CHK (d)
// requires -- never a single bundled "everything worked" boolean.
//
// Run yourself:
//   cd tools/ember-cli/src
//   EMBER_GOALFORGE_ROOT=<repo-root> bun scripts/cobs-proof-pack-run.ts monitor
//   EMBER_GOALFORGE_ROOT=<repo-root> bun scripts/cobs-proof-pack-run.ts understand
//   EMBER_GOALFORGE_ROOT=<repo-root> bun scripts/cobs-proof-pack-run.ts interact
//
// Ember is a single-tree repo -- there is no
// separate goalforge contract tree anymore. EMBER_GOALFORGE_ROOT is still the adapter's real
// contract (core/ember-world-state.ts never hardcodes a tree), so this script's caller points it
// at THIS repo's own root; there is nothing else running_worldstate_turn needs.
//
// This script never touches a GPU or a training process (verified: no torch import, no CUDA
// call, no model load anywhere in its own source or in commands/world-state.ts's import chain --
// only fs reads of docs/domains/governance/authority/GOAL.md / docs/domains/governance/ledgers/ember-debt-ledger.md / the totality-board receipt directory).

import { runWorldStateTurn } from "../commands/world-state.ts";

const VERBS = ["monitor", "understand", "interact"] as const;
type Verb = (typeof VERBS)[number];

function isVerb(x: string | undefined): x is Verb {
  return typeof x === "string" && (VERBS as readonly string[]).includes(x);
}

async function main(): Promise<number> {
  const verb = process.argv[2];
  if (!isVerb(verb)) {
    console.error(`usage: bun scripts/cobs-proof-pack-run.ts <${VERBS.join("|")}>`);
    return 1;
  }
  if (!process.env.EMBER_GOALFORGE_ROOT) {
    console.error(
      "EMBER_GOALFORGE_ROOT is not set -- point it at this repo's own root (single-tree Ember).",
    );
    return 1;
  }
  try {
    const output = await runWorldStateTurn(verb);
    console.log(output);
    // runWorldStateTurn never throws for an unconfigured root -- it returns a plain status
    // string instead (see its own top-of-function guard). Treat that specific honest-status
    // string as a failure here too: a proof-pack command that "succeeds" by printing "not
    // configured" is not real live state and must not exit 0.
    if (output.startsWith("world-state source not configured")) {
      return 1;
    }
    return 0;
  } catch (error) {
    console.error(`FAIL: ${verb}:`, error instanceof Error ? error.message : String(error));
    return 1;
  }
}

main().then((code) => process.exit(code));
