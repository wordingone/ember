# Persistence gates — deletion test (D-gate) + cross-session persistence (P-gate)

Spec frozen 2026-06-11 (task #36). Terminal-condition components 6 and 7
of the goal's persistence clause. Today both exist only ad-hoc (deletion
= "adapter-unload, base floors receipted" noted inside the G1 gate);
this spec makes them STANDING, receipts-grade, and round-cadenced.
Harness implementation = eng-32. First receipts ride the round-2 gate.

## D-gate — gain disappears when the artifact is deleted

**Claim shape:** "gain G on surface S is carried by artifact A." If G
survives A's deletion, G was never A's — contamination, env drift, or
harness leak. The gate is the goal's own falsifier, run every round.

**Protocol (per artifact class):**

| Class | Delete operation | Cost | Cadence |
|---|---|---|---|
| adapter | unload AND move file to `quarantine/` (restore after) — proves the DISK artifact is the carrier, not residual process state | one eval leg | every round gate + every promotion (BINDING) |
| episode slice | retrain without the slice (matched steps) | one train run | round granularity only, when a slice's contribution is the claim under test |
| context library | empty-context arm | one eval leg | rides existing t4 arm structure |

**Receipt fields (d-gate-<artifact>-<ts>.json):** artifact path + sha256
(+ convention line), surface + seed protocol, `gain_with` (arm − base),
`gain_without` (post-delete rerun − base), paired delta CI — exact
methods BINDING for zero-inflated counts (stats_exact, #110) with
bootstrap alongside, `verdict`: PASS iff gain_without's CI excludes the
gain_with point (gain collapsed) AND gain_with reproduces pre-delete
within CI (the artifact restored = gain restored).

**Harness (eng-32):** `d_gate.py` wrapping w4_eval arms
{base, adapter, adapter-quarantined-rerun, adapter-restored}; governed;
seed-matched across legs; quarantine dir under `state/quarantine/`
(never deletes bytes — move + restore; receipts-only-truth applies to
the gate, not destructive disk ops).

## P-gate — what was learned yesterday is load-bearing tomorrow

**Claim shape:** the gain persists across a SESSION boundary: fresh
daemon process, fresh model load from disk, zero in-memory carryover.

**Protocol:** receipt PAIR on the same surface + seed protocol:
- `pre`: the round's G1/w4 gate receipt (already exists per round).
- `post`: after daemon restart (self-refusing /shutdown +
  train_daemon_start) + model/adapter reload from disk: one eval leg,
  same arms, same seeds.
- Continuity stamps in both: ledger sha256, adapter sha256, daemon PID
  (must differ pre/post — proves the boundary was real).

**PASS:** post gain within the pre gain's CI (exact + bootstrap quoted);
ledger/adapter shas unchanged across the boundary; PIDs differ.

**Cadence:** once per round, riding the round gate (one extra eval leg).
**First receipt:** r1w-q3-mtp on validation-43 vs its G1 numbers
(+5.23pp vs base) — runnable immediately after the #105 daemon work
lands (its restart IS the session boundary; the verification receipt
doubles as the boundary event). Schedule: directly behind the fp-19
bench in the post-RELEASED daemon queue.

## Binding consequences

1. Round-2 prereg (#35) includes BOTH gates as named legs — a round
   verdict without D-gate + P-gate receipts is incomplete (gate
   discipline: the persistence clause's conditions 6/7 stop being
   prose).
2. June-22 terminal audit (critical-path map §1) flips rows 6 and 7 to
   ✓ only on these receipts, never on the ad-hoc notes.
3. Tolerances are pre-registered HERE: PASS/FAIL by CI containment as
   stated above; no post-hoc tolerance widening (freeze-target rule).

*Owner: Leo (spec; task #36). Harness: eng-32 (Eli). First receipts:
round-2 gate + the immediate r1w-q3-mtp P-gate probe.*

## Addendum 2026-06-11 — first-instance retarget on round-2 reality

Round-2 G1 advanced nothing (advancing_arms=[], g1-r2w verdict), so the
original "D-gate rides the round gate's promoted artifact" has no round-2
target. Retarget, no protocol change:

- **First D-gate instance:** the Surface-A RECIPE-LEARNS claim — sft
  adapter (`adapters/r2-q3-sft`) on the 28-task recall view, seed
  protocol of `fp25-indist-20260611T060416Z`. Claim under test: the
  +75.9pp recall gain is carried by the adapter FILE. Legs {base, sft,
  sft-quarantined-rerun, sft-restored} per the protocol table; runs when
  eng-32's `d_gate.py` lands (quarantine semantics need the harness —
  not hand-rolled with raw w4_eval, which would hard-crash on a missing
  adapter path instead of producing the rerun leg).
- **First P-gate receipt:** unchanged target (#114: g1_r1w_mtp re-run,
  same args/seed 16) — claimed-then-retracted by the engineer 2026-06-11
  (mails 14503/14505, round-2 arms held the GPU). Still pending; queue
  position = directly after the fp-25 Surface-B legs terminalize. The
  2026-06-10 post-crash daemon restarts satisfy the session boundary vs
  the r1 G1 receipt; PID stamps prove it.
