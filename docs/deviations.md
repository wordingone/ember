# Registered deviations — frozen-prereg changes (fp-30b deviation protocol)

Frozen preregs may only change via a deviation note filed **BEFORE** the changed
run, never after. One entry per deviation, newest first. Each names: the frozen
artifact + its freeze SHA/date, what changes, why, and who owns the call.

---

## DEV-002 — rung2-grow-spec-v1 production stabilization: VRAM-resident-AdamW config infeasible on L1

**Date filed:** 2026-07-08 (the lead). **Filed pre-run** (no full-param production training
run has executed under this config; only the #402 dry-run estimate has run, receipted).
**Frozen artifact:** `docs/spec/rung2-grow-spec-v1.md` (FROZEN, decision gated 2026-07-04, #76 /
#113).

**What changes:** the production stabilization memory strategy. The frozen spec's config —
batch=16, seq=1024, full-param 2.2B, VRAM-resident AdamW — is replaced by a host-RAM-offloaded
optimizer-state strategy (candidate 3/4 below). Training semantics are UNCHANGED: same tokens,
same effective batch, same optimizer math. The deviation is a memory-strategy substitution,
not a change to the stabilization run itself.

### Deviation

docs/spec/rung2-grow-spec-v1.md specifies production stabilization at batch=16, seq=1024,
full-param 2.2B, VRAM-resident AdamW. The #402 honest dry-run receipts this config at an
estimated **30.903 GiB required vs 23.988 GiB total** on the L1 card — infeasible outright,
independent of co-residency. FLOPs are NOT the wall (6.571e15 vs 2.431e16 ceiling, 0.5%).

### Why (the gap) — what the wall teaches

The spec smuggled a strategy-class assumption: "production config" was written as if
VRAM-resident-everything is the only shape. The bill decomposes (first-principles, rank-2):
weights 2N (bf16 ~4.4GiB) + grads 2N (~4.4GiB) + AdamW states 8N (~17.6GiB) + activations
(batch-dependent) + fragmentation. The 8N optimizer term dominates — the wall binds the
VRAM-resident-AdamW strategy class only, not the training semantics.

### Candidate cures priced against the receipt (MEASURE slots REGISTERED-PENDING)

1. **Gradient checkpointing** — trades activation memory for ~30–35% step-time. Does NOT
   touch the 8N term. Insufficient ALONE (saves only the activation slice); composable term.
   MEASURE: activation slice at batch=16/seq=1024 — REGISTERED-PENDING (cure PR).
2. **Batch reduction + grad accumulation** (e.g. micro-batch 2 × accum 8 = identical effective
   16) — shrinks activations ~8×; does NOT touch 8N. Composable, near-free in wall-clock at
   CPU-bound micro-batches. MEASURE: per-micro-batch activation footprint —
   REGISTERED-PENDING.
3. **CPU-offloaded optimizer states** (8N in host RAM, step on CPU or paged) — removes the
   dominant term from VRAM entirely: leaves ~2N+2N+activations ≈ 9–10GiB + margin — FITS even
   with margin floor 2GiB, possibly alongside a paused-server window only. Cost: step-time
   impact bounded by PCIe/host-RAM bandwidth; the box has 64GiB host RAM and the scan lane
   proved ~34GiB free is routine. Primary candidate.
4. **Combination 2+3** — micro-batch accumulation + host-RAM optimizer: the fit case with the
   largest margin; baseline recommendation pending MEASURE receipts — REGISTERED-PENDING.

The cure PR fills the REGISTERED-PENDING measurements under the kill/promote criteria below
(measuring activation footprints now would contend with the resident serving model for no
decision value — the 8N-term arithmetic already picks candidate 3/4).

### Residency ruling (acceptance #2 of #411)

Declared: the serving model (llama-server, ~18.3GiB resident) does NOT coexist with ANY
full-param training config on 24GiB — every cure above assumes a **serving-pause window**
(cockpit renders model-offline honestly; operator-visible line announces the window). The
alternative (residency budget carved out of VRAM) is arithmetic-infeasible for 2.2B full-param
under any candidate. This is a **dated acting-operator ruling**; reversible if a future config
change alters the arithmetic.

### Preflight change (acceptance #3)

The dry-run harness preflight asserts the CHOSEN config's estimate against nvidia-smi free
VRAM (authoritative under WDDM; torch.cuda.mem_get_info diverged twice, receipted) with the
2GiB margin floor, refusing to launch otherwise. No fix-forward on a failed assert.

**Named successor (→ cure PR):** fills the REGISTERED-PENDING MEASURE slots (1, 2, 4) and
executes the measured dry-run under the kill/promote criteria below.

**Who owns the call:** the wall diagnosis, candidate ranking, and residency ruling are the
lead's (drafted + adopted here, per the deviation mechanism). The cure PR's chosen config and
measured verdict are gated against the criteria below before promotion.

### Kill/promote criteria for the cure PR

Promote: a measured dry-run pass (same clause-d harness) showing the chosen config's REAL
peak (torch profiler or nvidia-smi sampling) fitting total-VRAM minus margin, with
function-preservation PASS unchanged. Kill: measured peak exceeds estimate by >15% (the
estimator is then the defect; fix estimator before config).

**Revision criterion:** if a future config change alters the 8N-term arithmetic (e.g. an
optimizer swap or parameter-count change), this ruling is revisited — not treated as
permanent.

**Receipts:** `receipts/grow-operator-dryrun-20260708T060841Z.json`,
`receipts/grow-op-verify-20260708T060841Z.json` (merged to public/master via PR #402, commit
e4a3e05). Relates to issues #411, #406.

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
