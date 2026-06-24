# Registered deviations — frozen-prereg changes (fp-30b deviation protocol)

Frozen preregs may only change via a deviation note filed **BEFORE** the changed
run, never after. One entry per deviation, newest first. Each names: the frozen
artifact + its freeze SHA/date, what changes, why, and who owns the call.

---

## DEV-001 — fp-33 surpass contract: add A4 (multimodal paired bar)

**Date filed:** 2026-06-14 (the lead). **Filed pre-run** (no surpass run has executed;
the multimodal v0 is pre-launch). **Frozen artifact:** `docs/fp33-surpass-prereg-v1.md`
(FROZEN 2026-06-12).

**What changes:** add a binding **A4 — multimodal paired bar** to Leg A, and
update the verdict to `SURPASS = A1 ∧ A2 ∧ A3 ∧ A4 ∧ B1 ∧ B2 ∧ B3 ∧ B4`.

**Why (the gap):** the v1 contract was frozen 2026-06-12, BEFORE the maintainer's 2026-06-14
reactivation set the active goal to a **multimodal-unified** v0. Every v1 bar
(A1 floor-world, A2 accumulation-loop, A3 MBPP/GSM8K, B1–B4 founder-likeness) tests
**text/code/duty only**. The opponent — Gemma E2B — is **multimodal-capable**.
So as frozen, "surpass E2B" is claimable while neither side's multimodal capability
is ever tested: a multimodal v0 could win the contest on text bars alone against a
multimodal opponent. That is an incomplete-measurement honesty hole, not a real
surpass. The goal centers the modality the contract does not test.

This is a TIGHTENING (surpass becomes harder, one more binding bar), not a scope
reduction — it aligns the success criterion with the goal the maintainer already set.

**A4 spec (drafted, same rigor as A1–A3):**
- **Paired, seat-swapped:** ember-multimodal vs E2B-multimodal, both seated in
  ember's own harness/worlds, same harness commit, prompt-template adaptation only
  (template in receipt). Identical to the common protocol's seat-swap rule.
- **Task distribution:** a **held-out image-text** split — the B-MULTI-1 corpus's
  frozen heldout bucket (image-text pairs in the 48×48 patch format), split by
  index BEFORE any training use (same split discipline as world-choice K3). Public
  VL slices admitted only if they clear the local-rights bar (the LiveCodeBench
  no-LICENSE rejection precedent applies — no license at repo root → not admitted
  without sign-off).
- **Metric:** per-task correctness on the VL task (exact-match / graded per the
  task's own ground truth, never a model judge). **Statistics:** the common block —
  paired bootstrap, 10,000 resamples, 95% CI on per-task delta (ember − E2B). Bar:
  **CI excludes 0 in ember's favor** (same as A1). E2B failing the VL floor while
  ember clears it also satisfies A4 (mirrors A2's asymmetry clause).
- **Matched compute** + governor/headroom rails, identical to every other bar.

**Named successor (eng, → the engineer):** the A4 VL eval harness leg + the B-MULTI-1
heldout-split manifest (rides the engineer's B-MULTI corpus build #27; the eval harness is
its A4 counterpart, analogous to the GSM8K-200 harness minted for A3-ii).

**Who owns the call:** the A4 *spec* is the lead's (drafted + adopted into the contract
here, per the deviation mechanism — not bounced). The surpass *verdict definition*
(whether SURPASS formally includes A4) is **goal-level = the maintainer's** — adopted by
default on this honesty argument; the maintainer confirms or scopes-out A4 on return. Until he
moves it, A4 is in the contract.

**Revision criterion:** if the maintainer rules that v0's multimodal capability is proven
separately by the verify-floor (the pilot's own kill-criteria forgetting-watch +
floor-probe) and the surpass *contest* stays text/code/duty, A4 is retired from the
verdict and recorded as proven-elsewhere — not silently dropped.

Per user direction.
