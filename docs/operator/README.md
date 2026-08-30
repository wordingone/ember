# Ember Operator Docs — Entry Point

This is the entry point for anyone operating Ember without the maintainer or
any LLM assistant in the loop (the C-IND operator-independence contract).
Two documents cover the CLI's actual operator-facing surface:

- [commands.md](../domains/governance/operator/commands.md) — every slash command the cockpit registers,
  with its aliases and what it does.
- [operate.md](operate.md) — how to launch a real ember-cli operator
  process, stop it cleanly, and recover it after an unplanned interruption.

## What Ember is, briefly

Ember is a self-improving research system. The **cockpit** (`tools/ember-cli`)
is the operator's window into it: a terminal CLI exposing a small set of
slash commands over the live goal/ledger/receipts state. Everything an
operator needs to interact with, observe, activate, deactivate, customize,
study, or comprehend the system is reachable through that command surface —
see [commands.md](../domains/governance/operator/commands.md) for the full list.

## Where things live

- `tools/ember-cli/src/command-registry.ts` — the actual live command
  registry (source of truth; this doc is a description of it, not a
  substitute for it).
- `receipts/` — every executed operator/experiment run leaves a JSON receipt
  here; `scripts/ember_totality/` holds the status probes that read them.
- `state/` (inside `tools/ember-cli/`) — runtime state: heartbeats, watchdog
  logs, planned-outage markers.
