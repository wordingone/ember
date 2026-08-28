# 11 — Totality Board and Conditions

## What a "condition" is

`docs/spec/conditions-v1.md` is "the canonical registry of machine-checkable
goal conditions" — 41 total entries: 39 primary conditions (`C(-1)`, `C0`
through `C15`, and the named conditions `C-EFF`, `C-BASE`, `C-PORT`,
`C-FED`, `C-GROW`, `C-ORGANISM`, `C-OBS`, `C-ANAT`, `C-SCALE`, `C-E2B`,
`C-IND`, `C-PROC`, `C-LEGIB`, `C-SURFACE2`, `C-ENF`, `C-MILE`, `C-DISC`,
`C-LADM`, `C-AUTO`, `C-CUSTODY`, `C-AUTHORITY`) plus 2 roll-ups
(`C-MANIFEST`, `C-TALLY`). Each condition specifies an `R:` (requirement
text), a `Does NOT count:` clause (behaviors that look like progress but
aren't), an invalid-token (a machine-checkable ✗ marker), and a `CHK:`
(the exact executable check).

## What a "probe" is

Each condition (except the 2 roll-ups and 3 standing process-invariants) has
a corresponding `scripts/ember_totality/test_<id>.py` STATUS PROBE. Per
`ember_totality_spec.py`'s own contract: a probe prints exactly ONE line
beginning with a recognized status token and ALWAYS exits 0 (so the board
can aggregate even a failing condition), and determines its verdict by
really inspecting state under its resolved root — never hardcoded.

## The runner: scripts/ember_totality/ember_totality_spec.py

Executes every `test_*.py` probe in its own directory as a subprocess,
parses each probe's status line, aggregates all rows into one board, prints
it, and writes a receipt under `scripts/ember_totality/receipts-totality/
ember-totality-<UTC-ts>.json`. Registry sync is self-enforcing: the runner's
own condition-id set must byte-compare equal to `conditions-v1.md`'s
registry, or the WHOLE RUN aborts with `REGISTRY_DRIFT` before any probe
executes. A registry id with no matching probe file still gets a board row,
synthesized as `UNEVALUABLE` ("no probe implemented") rather than silently
vanishing.

## Outcome values

STATE-conditions (every id except the 3 process invariants) are three-valued:
- **GREEN** — a real receipt/artifact was found and satisfies the CHK.
- **RED** — inputs were found and opened; the CHK evaluated false (a genuine unmet condition).
- **UNEVALUABLE** — the probe's input could not be located or opened; counts as RED for completion math but is never reported as an evaluated failure (this is deliberately distinct from "found and failed").

The 3 standing process-invariant rows (`C0`, `C9`, `C15` — GOAL.md §4.0(9))
are never GREEN/RED/UNEVALUABLE; they render `AUDIT-OK`, `AUDIT-INCIDENT`, or
`AUDIT-PENDING-EPOCH` from a cadence audit against an operator-acceptance
epoch marker.

## Completion math

Per `conditions-v1.md` §4.4: complete iff every STATE-condition is GREEN AND
zero unresolved post-epoch `AUDIT-INCIDENT` rows exist, AND (per §4.3) the
roll-up `C-TALLY` itself reads `pct=100` — a self-referential meta-condition
that recomputes live from the board's own rows (see `scripts/ember_totality/
test_c_tally.py`) rather than trusting any hand-written completion claim.

## Current gaps — honestly stated

The last board render (`ember-totality-20260801T052815Z.json`, 41 conditions)
reported 14 GREEN / 23 RED / 1 UNEVALUABLE / 3 AUDIT-OK, `pct_complete: 36.8`.
The full row-by-row detail lives in that receipt, not reproduced here — see
15_TECHNICAL_REPORT.md for how to read a fresh render.
