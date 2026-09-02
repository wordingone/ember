# Command Reference

The live command registry (`tools/ember-cli/src/command-registry.ts`,
`getCommands()`) currently exposes six commands. This list is generated
from, and machine-checked against, that same registry (see
`src/ember/governance/scripts/ember_totality/ind5_comprehend_producer.py`'s completeness and
freshness legs) — if the live registry changes, this file is stale until
updated.

## `/observatory` (alias `/obs`)

Shows the loop's recent cognitive-mode timeline and its current state. Read
this to answer "what has the loop been doing, and what mode is it in right
now?" without needing to read raw logs.

## `/watch`

Toggles the live telemetry view on/off. While on, it tail-polls the shared
telemetry channel and surfaces the current governor snapshot (VRAM
usage/fraction) and any active training run (step, loss, elapsed) — the
`/watch` command's underlying mechanism is
`tools/ember-cli/src/services/telemetry-watch.ts`'s `startTelemetryWatch()`.

## `/finetune` (alias `/ft`)

Controls the governed finetune: `start`, `stop`, `pause`, `resume`, `adjust`.
This is the operator's ACTIVATE/DEACTIVATE surface over the training loop.

## `/model`

Controls the local model lifecycle: `load`, `unload`, `status`. Lets an
operator free GPU VRAM by unloading the model without closing the cockpit.

## `/goal`

Sets, views, or clears the goal objective: `/goal <objective>` sets or edits
it, plain `/goal` views it, `/goal clear` clears it. Mid-flight edits inject
a steering prompt so the running loop re-anchors on the new objective.

## `/cockpit` (aliases `/world`, `/cobs`, `/board`)

The C-OBS observatory: MONITOR / UNDERSTAND / INTERACT over the real
GOAL/ledger/receipts world-state adapter, with click-to-evidence and a
confirm-only encounter membrane (offers are surfaced, never auto-executed —
an operator explicitly confirms or declines each one).
