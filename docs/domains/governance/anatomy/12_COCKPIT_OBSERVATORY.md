# 12 — Cockpit and Observatory

## What C-OBS requires

Condition `C-OBS` (`docs/domains/governance/spec/conditions-v1.md` §4.2, first-class & early)
requires: (a) real adapters binding GOAL/ledger/receipts to an
`EmberWorldState`, (b) click-to-evidence (a rendered claim resolves to its
real source path + sha256), (c) a confirm-only encounter membrane (never
silent steering), and (d) a user-facing CLI/observatory surface proving
MONITOR / UNDERSTAND / INTERACT via a proof-pack the operator runs himself.

## Real code that exists

`tools/ember-cli/src/core/ember-world-state.ts` defines `buildEmberWorldState()`,
called fresh at boot by `tools/ember-cli/src/commands/world-state.ts`
(`cachedState = await buildEmberWorldState()`), not a hand-maintained mirror.
`tools/ember-cli/src/core/encounter-membrane.ts` implements the confirm-only
membrane referenced by requirement (c). `tools/ember-cli/src/core/
monitor-render.ts` implements the render side of MONITOR.

`scripts/ember_cobs_capture.py` is the proof-pack CAPTURE harness (gh issue
#10): it runs the real observatory —
`tools/ember-cli/src/core/ember-world-state-repl.ts` — in a visible ConPTY
(never headless, per operator rule), scripts a
MONITOR/UNDERSTAND/INTERACT/evidence/act/confirm/decline session against it,
and assembles a receipt proving all four C-OBS sub-requirements, including
exercising both a `decline` and a bogus `confirm` live to prove the
no-silent-steer path holds. It explicitly does not touch training/GPU.

## Probe hardening (test_c_obs.py, issue #749 cure)

The probe (`src/ember/governance/scripts/ember_totality/test_c_obs.py`) was hardened after a
disclosed weakness: pre-cure, its (a) worldstate-binding and (d) proof-pack
checks were pure keyword/prose scans over any evidence-subdir file — a
hand-authored `.md`/`.json` containing the right words satisfied the CHK
with zero recompute. Post-cure, both are decisive structured-receipt checks:
(a) requires an `emberworldstate_adapter` block naming GOAL/ledger/receipt
sources that actually RESOLVE in-tree (spanning >=2 of the three
categories) and sha-pins its own adapter source file; (d) requires an
`observatory_proof_pack` block whose MONITOR/UNDERSTAND/INTERACT commands
each carry an EXPLICIT `exit_code == 0` (a missing exit_code REJECTS, never
defaults to a pass) and sha-pins its own runner script the same way. (b)
click-to-evidence and (c) confirm-only-membrane remain lighter keyword
checks but are ANDed with, never a substitute for, (a)/(d).

## Current gaps — honestly stated

The last board render reported `C-OBS` RED: "satisfying artifact ABSENT
under the state root: missing real GOAL/ledger/receipts->EmberWorldState
adapter binding; user-runnable observatory proof-pack (MONITOR/UNDERSTAND/
INTERACT)." Read precisely: this means the WORLD-STATE ADAPTER CODE and the
CAPTURE HARNESS both exist on disk (above), but as of the last board render
no structured receipt satisfying the hardened (a)/(d) checks was found under
the audited state root — a receipt-visibility gap, not necessarily a
code-absence gap. `C-IND` (operator-independence) was also RED, citing
`IND-1 INTERACT (IND-1 absent)` and the same `C-OBS` non-GREEN dependency.
