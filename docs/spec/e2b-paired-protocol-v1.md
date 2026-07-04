# C-E2B paired-legs protocol v1 (FROZEN)

Freeze ts: 20260703T224100Z (this file's commit is the freeze receipt; per test_c_e2b.py the
protocol_frozen_ref must resolve in-tree with freeze ts strictly BEFORE any verdict receipt ts).

Purpose: the exact, fair, matched-budget procedure for the C-E2B comparison — the from-scratch
owned core vs Gemma-E2B swapped into Ember's OWN seat, both legs, per conditions-v1.md §4.2.
This document is procedure only; it pre-registers no expected outcome. Past the 2026-06-22
forcing date, a shortfall is recorded as a measured-distance receipt (protocol-compliant,
condition stays RED) — distance is a valid, publishable result of this protocol.

## Common frame (both legs)

- **Seat:** Ember's resident harness exactly as the C14 owned-run uses it — same worlds, same
  battery construction (corpus-v2 k=3 exemplars), same governor. The E2B arm replaces ONLY the
  core model behind the seat; every other component is byte-identical.
- **Owned-core identity:** the grown 1.222B substrate at the fire-4 seed checkpoint
  (models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/step-00000766,
  sha256 58e8e989…). no_borrowed_weights=true, quantized=false — both re-derivable from the
  checkpoint provenance receipts.
- **E2B identity:** Gemma-E2B exactly as reachable via the existing seat-swap plumbing
  (fp33-e3 / sp6c shakedown receipt lineage). Record its param count and quantization state
  honestly in the receipt (the E2B arm MAY be quantized; only the owned arm is barred from it).
- **Matched budget:** per-arm budgets EQUAL and recorded as numbers: identical wall-clock cap
  per leg, identical train-step budget where a leg trains (1024 steps, the fire-4 schedule),
  identical eval task sets. One GPU job at a time; arms run sequentially, owned arm first.
- **Receipt:** one JSON under receipts/ matching *e2b*, with legs.ember_work +
  legs.founder_likeness (numeric owned_core_score and e2b_score each), matched_budget block
  (per-arm budgets, equal), owned_core_identity block, protocol_frozen_ref = this file's
  in-tree path, api_spend_usd, paid_api_surface_used.

## Leg 1 — ember_work

Both arms run the fire-4 C14 battery shape end-to-end at the matched budget: train on the same
5 train tasks, eval on the same 3 heldout tasks, 16 checkpoint evals every 64 steps.

- **Score (numeric, identical formula both arms):**
  score = final_heldout_pass_count + 0.2 * max_train_pass_count.
  Heldout transfer dominates by construction; train fitting is a minor tiebreak. The 0.2
  weighting is frozen here, before any arm runs.
- Deletion sensitivity is recorded per arm (deleted-arm heldout delta) as evidence, not score.

## Leg 2 — founder_likeness

Both arms are addressed through the SAME resident-harness action channel with the same 3-part
scripted session (frozen order): (1) an addressable-while-running probe (a direct question
whose answer requires reading current harness state), (2) a work item (initiate + complete a
bounded task with an in-tree receipt), (3) an unprompted-continuation window (fixed duration;
does the arm continue its event stream without input).

- **Score (numeric, 0–3, identical rubric both arms):** one point per element, awarded by the
  element's own artifact — (1) answer references true current state (checkable against the
  harness log), (2) receipt exists and validates, (3) event stream shows autonomous entries in
  the window. No style judging; artifacts only.

## Falsifiers / does-not-count (from the probe, restated)

- One leg only → invalid_single_leg_surpass.
- Any component other than the core differing between arms → invalid_e2b_unpaired.
- A borrowed or quantized core on the OWNED side → does not count.
- Scores must be re-derivable numerically from the receipt's own rows — never a bare boolean.

## Sequencing rails

- CPU recon + dry-run of the seat-swap plumbing FIRST (no GPU); GPU execution only after the
  maintainer gates the dry-run against this protocol.
- The v2.2-shape GPU ban (#37 8l) does not bar this protocol: these are evaluation arms of a
  pre-existing battery, not a new v2.2 mechanism fire. The owned arm's training leg REUSES the
  fire-4 result where the budget matches exactly (1024 steps, same battery, same checkpoint) —
  re-running an identical arm to reproduce a receipt that already exists is waste; the receipt
  may cite fire-4's run as the owned ember_work arm, with the citation recorded explicitly.

## v1.1 addendum (freeze ts 20260703T223500Z — before any v1-verdict receipt; fixes the two
## numbers v1 left unspecified and settles one reading dispute from the CPU recon)

1. **E2B's ember_work arm TRAINS.** "Both arms run the fire-4 C14 battery shape end-to-end"
   means exactly that: the E2B arm receives the SAME iGRPO/LoRA training procedure in the seat
   (1024 steps, same schedule, LoRA at the head linear of ITS architecture), then the same
   16-checkpoint eval battery. An inference-only E2B leg is NOT budget-matched (0 vs 1024 train
   steps) and would invalidate matched_budget. Named prerequisite before GPU: a CPU attach recon
   proving ember_resident_igrpo's LoRA attach + one zero-lr backward works on the E2B module
   graph. If that attach hits a genuine architecture wall, the wall is broken (adapt the attach),
   never resolved by silently downgrading to inference-only.
2. **founder_likeness continuation window = 300 seconds**, identical wall-clock for both arms,
   measured by the harness's own event-stream timestamps.
3. **Merge-then-cite integrity check.** Citing fire-4 as the owned ember_work arm requires the
   CPU LoRA-delta merge to prove it reproduces fire-4's trained terminal state: the merged
   directory must load via the unchanged owned-core factory AND reproduce fire-4's final-battery
   action rows exactly on at least 3 spot tasks (the receipt records rows side-by-side). A merge
   that fails reproduction does not cite; the discrepancy is receipted and escalated.
4. **E2B provenance pin.** The E2B arm's receipt records a weights revision/commit pin (June's
   receipts had one; the local-copy path alone is not provenance).

## v1.2 addendum (freeze ts 20260703T224800Z — mechanism correction from the CPU wall report,
## before any verdict receipt; the clause-3 REQUIREMENT stands, its named mechanism was unsafe)

1. **Merged-directory citation is BANNED for this architecture; the safe adapter-load path
   replaces it.** The owned core weight-ties head.weight to the embedding table (literal
   same-tensor aliasing, cbase_grow_dryrun.py:72), and the seed state_dict deliberately omits
   head.weight — a merged, untied head either no-ops on reload (phantom checkpoint scoring the
   UNTRAINED seed as if trained: the exact self-deception _persist_resident_adapter's docstring
   warns about) or overwrites the shared embedding tensor. Wall report:
   scratch/c-e2b-merge/fire4-merge-wall-report.json. Citation integrity is instead proven by the
   existing fail-closed path (ember_e2b_surpass_run.py::load_owned_core_from_c14_checkpoint +
   _load_and_verify_adapter_file: adapter sha256 match, param-hash-changed assert, lora_B
   non-zero assert) wired into the paired-run loader, THEN the unchanged clause-3 spot-check:
   reproduce fire-4's final-battery action rows on >=3 tasks (train_s02/train_s07/held_s01
   expect actions 3/0/3), rows side-by-side in the receipt.
2. **Clause-1 attach point clarified: the E2B adapter attaches at ITS head linear via the same
   non-mutating wrapper mechanism the owned core uses** (the correction lives in a separate LoRA
   submodule; forward = head(x) + x@A@B*scaling; the tied tensor is never written). The tying
   hazard in (1) is merge/persist-specific and does not bar a wrapper adapter. The o_proj attach
   recon (attach-recon-20260703T224158Z.json) stands as auxiliary evidence the E2B graph accepts
   adapters with clean gradient isolation; the paired arm itself must be head-attached for
   structural parity with fire-4's head-LoRA owned arm.
