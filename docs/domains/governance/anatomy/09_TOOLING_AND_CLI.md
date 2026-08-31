# 09 — Tooling and CLI

## tools/ember-cli/

A TypeScript project implementing Ember's command-line/cockpit surface.
`tools/ember-cli/src/commands/` holds one file (+ matching `.test.ts`) per
command, including (non-exhaustive, real directory listing): `admit.ts`
(receipt admission), `advisor.ts`, `benchmark.ts`, `bridge-kick.ts`,
`checkpoint-load-command.ts`, `custody.ts`, `designate.ts`, `files.ts`,
`finetune.ts`, `goal.ts`, and `world-state.ts` (the C-OBS adapter command —
see 12_COCKPIT_OBSERVATORY.md). `tools/ember-cli/src/core/` holds the shared
runtime: `ember-world-state.ts`, `encounter-membrane.ts`,
`goal-continuation*.ts`, `monitor-render.ts`, `query-engine*.ts`,
`frontend-shell.ts`. Every command has a co-located `.test.ts`.

## scripts/ember_avir_cli_launch_entry.py

A deliberately small Python launch entrypoint, distinct from the TypeScript
CLI's own entry — its own docstring: "Clean-room Ember/[operator]-agent
resident launch entrypoint... deliberately small executable surface: resolve
the repo, verify the resident goal/command/UI/backend receipts that make the
harness usable, and emit a machine-readable handshake. It is not a copy of
[operator]-agent-cli's TypeScript entry." It checks four
`REQUIRED_RECEIPTS` under `receipts/ember-preloop-resident-gate/` (native
goal organ, function slash-commands, UI/UX REPL components, backend
coordinator agents) each against an `EXPECTED_VERDICTS` string, before
declaring the harness usable.

## Related CLI/tooling scripts (repo-root scripts/, non-exhaustive)

- `scripts/ember_avir_harness.py`, `scripts/ember_avir_observe.py`, `scripts/ember_avir_tasks.py` — the AVIR-side harness/observation/task surface
- `src/ember/governance/scripts/cockpit_watchdog.py` — a watchdog process for the cockpit (see 12_COCKPIT_OBSERVATORY.md)
- `scripts/worktree_lifecycle.py` — the worktree CLI (see 02_REPO_TOPOLOGY.md)
- `scripts/verify_authority_conservation.py`, `src/ember/governance/scripts/receipt_check.py`, `scripts/verify_nosource_operability.py` — CLI-invoked verifiers, run both standalone and inside repo-guard hooks

## Current gaps — honestly stated

No board condition tracks "CLI tooling" as a single row; individual commands
feed their own conditions (e.g. `world-state.ts` feeds `C-OBS`, `admit.ts`
feeds custody/`C0`-adjacent conditions). This doc is a map, not a
completeness claim for any individual command.
