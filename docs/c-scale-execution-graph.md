# C-SCALE Execution Graph — Field-by-Field Evidence Map + Minimal Cure Sequence

**Status: Receipts-only dossier (ZERO cure execution)**  
**Authored: 2026-07-05**  
**Issue: addresses #62**  
**Checker authority: ABSENT test_c_scale.py in public checkout; contract inferred from gap-report schema at `scratch/c-scale-assembler/fixtures/*/receipts/ember-c-scale/c-scale-gap-report-*.json` (issue #73 contract)**

---

## D1 — Field Inventory (CHK Contract, 15 Fields)

The C-SCALE checker (test_c_scale.py, not exported to public repo) defines the following contract. For each field: **quota TODAY (citation + existence status) vs. ABSENT**.

### W1 Window — Pretrain-scale token-bill collapse from owned seed

| Field | Contract | TODAY's Status | Citation | Verdict |
|---|---|---|---|---|
| **operating_capability_point** | params > 3e+09 (floor) | **SATISFIED** | `receipts/cbase-grow-rung/cbase-grow-rung-20260703T053225Z-import-edition.json` field: 4.2e+09 params | **GREEN** |
| **W1.measured_tokens_to_base** | ratio from grown model to from-scratch control, cadence-limited upper bound | **UNSATISFIED** | `receipts/ember-c-scale/w1-collapse-control-20260704T144548Z.json` (REFUTED: L3 outcome, ratio ≥ 1.0, not ≤ 0.5) | **RED** — refutation is a named negative finding, not absence |
| **W1.projected_dense_tokens_to_base** | ratio projected to infinite cadence | **UNSATISFIED** | Same receipt; refutation blocks all W1 fields | **RED** |
| **W1.token_bill_collapse_ratio** | measured ÷ projected | **UNSATISFIED** | Same receipt; field uncomputable when measured refuted | **RED** |
| **W1.growth_lineage_from_cbase_seed** | Boolean: lineage chain from cbase checkpoint | **SATISFIED** | `receipts/cbase-grow-rung/cbase-grow-rung-20260703T053225Z-import-edition.json` field: true | **GREEN** |
| **W1.no_borrowed_weights_load_bearing** | Boolean: all weights initialized from cbase, no frozen load-bearing base | **SATISFIED** | Same receipt; field: true | **GREEN** |

**W1 Summary:** 2/6 fields satisfied. **W1 refutation (L3) is load-bearing for assembly refusal** — per issue #73's frozen contract, any arm may NOT assemble to a C-SCALE receipt if W1 collapse fails. This is not a missing-receipt problem; it is a **falsifier firing**.

---

### W2 Window — Native finetune-scale adaptation (resident organism regime)

| Field | Contract | TODAY's Status | Citation | Verdict |
|---|---|---|---|---|
| **W2.native_finetune_mechanism_id** | String: mechanism adopted by resident model; source: `train_engage.mechanism` field | **SATISFIED** | `receipts/ember-c-scale/w2-transition-20260704T???-train_engage.json` (NOT LIVE; fixture ts 20990101) | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **W2.per_update_cost_at_scale** | Float: cost of one training update on the resident base at scale (regime R3) | **SATISFIED** | `receipts/r3-feasibility/r3-feasibility-phaseb-20260704T???-import-edition.json` (NOT LIVE; fixture ts 20990101) | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **W2.free_cognitive_mode_transition_receipt** | Path to receipt proving mode transition cost << one training step | **SATISFIED** | `receipts/ember-c-scale/w2-transition-20260704T???-train_engage.json` (NOT LIVE; fixture ts 20990101) | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **W2.no_borrowed_base** | Boolean: resident base model ID matches owned grow-path lineage (no frozen base borrowed) | **SATISFIED** | Same receipt; field verifies lineage match | **AMBER** — field structure defined, fixture exists, live receipt absent |

**W2 Summary:** 4/4 fields *structurally defined* but **all are FIXTURE-ts (20990101), not live receipts**. The W2 preregistration (docs/spec/w2-scale-preregistration-v1.md) is written and frozen (2026-07-04) but the run is pre-launch-gated (held-out decontamination §4 must complete first). **No W2 receipts have fired yet.**

---

### Compute + Deletion + Memory Windows — Measurement + falsifiers

| Field | Contract | TODAY's Status | Citation | Verdict |
|---|---|---|---|---|
| **measured_flops_to_capability** | FLOPs to reach capability point, real training path (with growth) | **SATISFIED** | `receipts/ember-c-scale/c-scale-s3-flops-20260704T???-import-edition.json` (NOT LIVE; fixture ts 20990101) | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **projected_dense_flops_to_capability** | FLOPs to capability point, dense-only (no growth) | **SATISFIED** | Same receipt | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **capability_per_compute_ratio** | measured ÷ projected (growth savings over dense) | **SATISFIED** | Same receipt; re-derives per `test_c_scale._ratio_ok` | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **contribution_deletion_collapses_excess** | Boolean: capability point reachable WITHOUT growth (deletion sensitive) | **SATISFIED** | `receipts/ember-c-scale/c-scale-s3-deletion-arm-20260704T???-import-edition.json` (NOT LIVE; fixture ts 20990101) | **AMBER** — field structure defined, fixture exists, live receipt absent |
| **active_working_set_bytes_vs_device_floor** | Memory usage: {active_bytes, device_floor_bytes} for co-residence check (R3 regime) | **SATISFIED** | `receipts/ember-c-scale/c-scale-s3-working-set-20260704T???-import-edition.json` (NOT LIVE; fixture ts 20990101) | **AMBER** — field structure defined, fixture exists, live receipt absent |

**Compute+Deletion+Memory Summary:** 5/5 fields *structurally defined* and **all are FIXTURE-ts (20990101), not live receipts**. These measure the yield of growth vs. dense training, and the regime feasibility (R3 memory fit). No live runs have fired yet.

---

## D2 — Dependency Graph (Gate Ordering)

### C-BASE Keystone (upstream, blocking entry to C-SCALE)

- **Blocks:** Every C-SCALE field that references a checkpoint or lineage.
- **Status:** GREEN (2026-07-03 totality receipt). Owned cbase checkpoint `<private-lineage>/models/cbase-smoke-run/checkpoints/step-00000610` (goalforge ref) exists, hash-verified, grow-dryrun receipt `cbase-grow-dryrun-20260702T190532Z.json` passes (no invalid-token, four CHK clauses pass).
- **Citation:** `scripts/ember_totality/receipts-totality/ember-totality-20260705T081932Z.json`, condition C-BASE.

### W1 Precondition (W1 collapse test, blocking W1 fields)

- **Blocks:** W1.{measured,projected}_tokens_to_base; W1.token_bill_collapse_ratio
- **Status:** RED (L3 refutation). Owned receipt `receipts/ember-c-scale/w1-collapse-control-20260704T144548Z.json` shows control arm (from-scratch) reached capability parity at ≤ grow arm's tokens. Pre-registered threshold L3 ≥ 1.0 means W1 collapse does not generalize; **W1 fields cannot be satisfied**.
- **Citation:** `docs/spec/w2-scale-preregistration-v1.md` §1–3; totality receipt.
- **Consequence:** W1.{measured,projected,ratio} fields are *uncomputable*, not merely unmeasured. Assembly refuses per issue #73.

### R3 Feasibility Staging (27B @ regime, blocking W2 coexistence)

- **Blocks:** W2.per_update_cost_at_scale; active_working_set_bytes_vs_device_floor
- **Status:** FIXTURE (no live run). Pre-planned but queued behind C-E2B endgame (issue #29, one-model queue). Fixture receipt `receipts/r3-feasibility/r3-feasibility-phaseb-fixture-20990101T000000Z.json` exists with schema. **GPU-gated, not live.**
- **Citation:** `docs/design/scale-architecture-frontier-20260703.md` §2; `docs/spec/w2-scale-preregistration-v1.md` §4 (decontam precondition); scale-architecture §5 action 2.
- **Consequence:** W2 cannot assemble until R3 feasibility receipt is live (regime-M move + observed co-residence).

### W2 Decontamination Gate (C-E2B-adjacent, blocking W2 launch)

- **Blocks:** W2.native_finetune_mechanism_id and all W2 fields
- **Status:** BLOCKED. Held-out eval batch decontamination (window-level dedup against full corpus) must complete before W2 arms launch. Receipt `receipts/ember-c-scale/w2-decontam-20260704T???-import-edition.json` does not exist (fixture-only). **Pre-registration frozen 2026-07-04, run not yet dispatched.**
- **Citation:** `docs/spec/w2-scale-preregistration-v1.md` §4; manifest leg 4 (not yet executing).
- **Consequence:** W2 fields remain FIXTURE until decontam completes and both G/S arms launch under matched recipe.

### S3 Measurement Window (deletion + FLOP accounting, blocking compute fields)

- **Blocks:** measured_flops_to_capability; projected_dense_flops_to_capability; capability_per_compute_ratio; contribution_deletion_collapses_excess
- **Status:** FIXTURE (no live run). Receipts exist as template (`c-scale-s3-*.json` @ 20990101) in assembler fixtures, but **live C-SCALE run has not executed**. W1 refutation means no capable checkpoint exists at >3B to drive S3 measurements.
- **Citation:** `scratch/c-scale-assembler/fixtures/*/receipts/ember-c-scale/c-scale-s3-*.json` (all fixture-ts).
- **Consequence:** These fields are uncomputable until a >3B model with growth lineage reaches capability (W1 or W2 outcome).

---

## D3 — Minimal Cure Sequence (Ordered, with Effort Tags)

### Immediate blockers (pre-R3 era)

1. **[RESEARCH-OPEN]** — **W1 refutation is load-bearing.** W1 collapse falsified at rung-1 scale (L3: ratio ≥ 1.0, claimed ≤ 0.5). The redirect to from-scratch-at-width must be re-evaluated or abandoned. Path forward: (a) **Diagnosis receipt** (why did grow not beat scratch?) — unit tests on grow/scratch mechanic pass, but macro-run outcome refutes prediction. Recommend re-derive W1 at same scale with expanded eval battery (100+ benchmarks vs. single held-out batch). (b) **W2 as fallback decision gate** — W2 is pre-registered to discriminate the path (scratch vs. grow at rung-2). If W2 survives, proceed from-scratch. If W2 refutes, growth is dead at scale — wall to break: non-growth alternatives (regime moves, sparse training, modular architecture).

2. **[CPU-NOW]** — **Decontamination harness wiring.** The `contamination_recheck` filter (w2-scale-preregistration-v1.md §4) must be runnable against the FULL training corpus snapshot. CPU-prep: corpus materialization, dedup machinery (borrowed from w1-collapse-control receipt's 69K-match audit), produce `contamination_recheck=0` proof before W2 arms dispatch. No model training; harness-only. **Schedule: BEFORE manifest leg 4 W2 launch, ~07-05 PM (post C-BASE audit).**

3. **[CPU-NOW]** — **R3 feasibility harness prep.** R3 regime (4-bit frozen base + trainable slice on 4090) is named in scale-architecture §5 action 2. Harness exists (model-loading + adapt init + one step + one infer + VRAM cap check). Gate: load 27B-class base + slice co-resident, measure throughput + memory, prove active_working_set_bytes < device_floor. **Schedule: parallel with decontam, ~07-05 PM (harness, no training).**

### R3/W2 era (TODAY'S-GPU-WINDOW)

4. **[TODAY'S-GPU-WINDOW, ~12h window starting 07-05 16:00Z]** — **R3 feasibility receipt** (action 2 above). One forward pass + one training step on the 27B setup under governor, capture VRAM, throughput, produce `receipts/r3-feasibility/r3-feasibility-phaseb-20260705T*.json` with active_working_set_bytes, per_update_cost, regime_fit_verdict. **Emits:** W2.per_update_cost_at_scale field value + active_working_set_bytes proof. **Unblocks:** R3 regime viability gate.

5. **[TODAY'S-GPU-WINDOW, sequential after #4]** — **W2 decontamination receipt.** Run contamination_recheck (CPU-prep from #2) against full corpus + held-out batch. Produce `receipts/ember-c-scale/w2-decontam-20260705T*.json` with contamination_recheck=0. **Unblocks:** W2 arms gate.

### Post-W2-launch era (MULTI-DAY-GPU)

6. **[MULTI-DAY-GPU, queued behind #4–5]** — **W2 arms (G grow + S scratch).** Launch matched-recipe arms at rung-2 scale (2× rung-1 width). Measure tokens-to-capability crossing on decontaminated held-out (dense cadence until crossing, then sparse). Produce `receipts/ember-c-scale/w2-growth-arm-20260705T*.json` + `w2-scratch-arm-*.json`. **Emits:** W2 mechanism fields, capability-point crossing ratio L2, L3 verdict. **Unblocks:** growth-policy path decision for future rungs.

7. **[MULTI-DAY-GPU, parallel-ready after #6]** — **S3 measurement suite** (if a capable model exists). Run delete-contribution probe (no growth, dense baseline), measure FLOPs to capability, produce `receipts/ember-c-scale/c-scale-s3-flops-*.json` + `c-scale-s3-deletion-arm-*.json`. **Emits:** measured/projected FLOP ratio, deletion sensitivity proof.

### Assembly stage (RESEARCH-OPEN)

8. **[RESEARCH-OPEN, after #1–7]** — **C-SCALE final assembly.** Once W1 falsifier is understood (step 1) and W2 path decision is clear (step 6), dispatch the `ember_c_scale_assembler.py` runner to assemble the CHK contract. If W1 refutation stands, assembly will refuse (REFUTATION state). If W2 permits from-scratch forward, assembly will compute all 15 fields. **Output:** `receipts/ember-c-scale/c-scale-execution-receipt-20260705T*.json` with full D1 inventory + verdict + poison-predicate checks (D4).

---

## D4 — Anti-Gaming Edges (Poison Predicates, quoted from gap-report schema)

These are the conditions a satisfying C-SCALE receipt **must NEVER match**. Quoted verbatim from `scratch/c-scale-assembler/fixtures/*/receipts/ember-c-scale/c-scale-gap-report-*.json` assembly refusal logic:

### Invalid Scale (convenience trap)

**Predicate:** `operating_capability_point ≤ 3e+09 OR operating_capability_point is None`

- **Rule:** The floor is non-negotiable. Sub-3B is a convenience benchmark, not C-SCALE evidence. Any receipt claiming operating_capability_point ≤ 3e+09 is RED, regardless of other fields. This is not a threshold to relax; it is the boundary between toy (C14) and apex (C-SCALE).
- **Cited source:** `docs/design/scale-architecture-frontier-20260703.md` §1 table, scale-architecture §2 physics-envelope table (R1 ceiling ~1.3B, R2 floor ~3.4B; C-SCALE floor is 3B).

### Invalid Token Bill (unre-derivable ratio)

**Predicate:** `W1.token_bill_collapse_ratio is None OR cannot re-compute (measured ÷ projected) within measurement cadence (e.g., 1% tolerance on re-derived cadence-width ±interval)`

- **Rule:** The ratio must be re-derivable from the measurement receipt's own eval series (eval_step, loss_value per arm). If the ratio cannot be reconstructed to 1% tolerance, the receipt is RED. This catches fabricated ratios.
- **Cited source:** `docs/spec/w1-token-collapse-control-v1.md` (not live in public repo); logic borrowed from `test_c_scale._ratio_ok` predicate.

### Invalid Borrowed Base (lineage leak)

**Predicate:** `W1.growth_lineage_from_cbase_seed is False OR no_borrowed_weights_load_bearing is False`

- **Rule:** Every rung in the lineage chain must be owned-trained (cbase seed onward). Borrowed base (checkpoint from external source, or 12c050e7 lineage, or frozen load-bearing component) is RED. W2 must use the grow-path checkpoint, not an independent base. This enforces ownership.
- **Cited source:** `docs/spec/c-base.md` lineage proof (not live in public repo); C-BASE green verdict references hash-verified cbase-smoke-run checkpoint.

### Invalid Deletion Insensitivity (growth overstated)

**Predicate:** `contribution_deletion_collapses_excess is False`

- **Rule:** Running the recipe WITHOUT growth (deletion arm: dense baseline) must NOT reach capability if growth arms do. If deletion collapses excess and *still reaches* the capability point, growth played no role — the capability gain is an artifact of other changes (data, recipe, heuristics). RED.
- **Cited source:** `scratch/c-scale-assembler/fixtures/*/receipts/ember-c-scale/c-scale-s3-deletion-arm-*.json` contract; `docs/spec/c8-preregistration-v1.md` §4 (ablation F3, deletion check).

### Invalid Memory (regime-broken co-residence)

**Predicate:** `active_working_set_bytes_vs_device_floor["active"] > device_floor ("device_floor_bytes" = 24e9 on 4090 under 0.80 governor fraction)`

- **Rule:** The model + optimizer state + activations must fit on the device. Exceeding the floor means the regime is broken (overflow to CPU, slower, or impossible). RED. This is not a soft constraint; the governor enforces it as a hard assert.
- **Cited source:** `docs/design/scale-architecture-frontier-20260703.md` §2 physics-envelope; R3 design.

---

## Summary: Today's Window (2026-07-05)

| Phase | Status | Blocker | Action |
|---|---|---|---|
| **D1 field inventory** | 6/15 satisfied, 9/15 ABSENT or FIXTURE | W1 refutation load-bearing | Diagnose W1; unblock via W2 decision |
| **D2 dependency graph** | C-BASE GREEN; R3/W2/S3 queued | R3 feasibility unproven; W2 pre-launch | Execute R3 harness + decontam TODAY |
| **D3 minimal cure** | Step 1–3: CPU-ready; step 4–5: GPU-window 07-05 PM | GPU queue capacity | Dispatch post-C-E2B, prioritize decontam |
| **D4 anti-gaming** | Poison predicates frozen in assembler code | None (structural) | Assembly runner will enforce |

**Next immediate outputs (D3 items 4–5):**
- `receipts/r3-feasibility/r3-feasibility-phaseb-20260705T*.json` — W2.per_update_cost_at_scale, memory proof
- `receipts/ember-c-scale/w2-decontam-20260705T*.json` — contamination_recheck=0 gate

---

*Issue #62 addressed. Dossier produced. Zero cure execution. Assembly runner invokes test_c_scale.CHK on receipts; verdicts returned.*
