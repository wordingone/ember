# C-SCALE S1 — Growth-Chain Execution Spec: Evidence Dossier

## Status

**AMENDED 2026-07-03: section 9 carries the binding pre-registration — this document is no longer decision-open.**

**DRAFT.** Assembled 2026-07-03, gathering the evidence base for issue #29's S1 clause ("S1 GROWTH
CHAIN 718M->3e9+") ahead of a pre-registration review session that will freeze the actual rung
count/sizes, the stabilization-segment sizing rule, and the remaining open decisions listed at the
end of this document (marked **PRE-REGISTRATION DECISION**). Follows the same pattern as
`docs/spec/c-scale-s2-token-bill-protocol.md` (S2, ratified 2026-07-03 on the pre-registration
lane — absent as of 2026-08-01 in this contract tree, not yet merged to master): gather receipts-first,
compute what can be computed live, flag what cannot be decided here, and never silently resolve an
open question. The `DRAFT` suffix keeps this document out of `src/ember/governance/scripts/check_goal_citations.py`'s
contract-force scope until ratified as `-v1.md`.

No git commits, no GPU runs, and no probe edits were made while assembling this document. One script
was *executed read-only* to obtain live G-budget verdicts for candidate rungs (§5) — disclosed there,
not asserted from memory. All parameter/VRAM/token arithmetic below is shown in full so a hostile
reviewer can re-derive every number from the cited receipt or config field.

---

## 1. Source requirements (verbatim)

### 1.1 Issue #29 — the S1 clause, quoted in full

> S1 GROWTH CHAIN 718M->3e9+: successive net2net width/depth steps from the receipted cbase lineage
> (466.7M->718.3M landed, fp_diff 2.4e-6 precedent), each step function-preservation receipted +
> post-grow train segment within pre-grow loss envelope; per-step token accounting banked (tokens
> spent at each width). Kill: function-preservation fp_diff >1e-3 or post-grow divergence.

The issue's frozen top-level contract (quoted in full, since S1 feeds its W1 sub-block):

> {operating_capability_point>3e9, W1:{measured_tokens_to_base, projected_dense_tokens_to_base,
> token_bill_collapse_ratio>1 RE-DERIVED, growth_lineage_from_cbase_seed,
> no_borrowed_weights_load_bearing}, W2:{...}, measured/projected flops-to-capability with
> capability_per_compute_ratio>1 RE-DERIVED, contribution_deletion_collapses_excess,
> active_working_set_bytes<=device floor}. Invalid tokens (quoted from the probe):
> invalid_fixed_scale_convenience, invalid_hardware_exit_ramp,
> invalid_memory_fit_as_scale_affordability, invalid_borrowed_base_as_owned_scale.

The issue's own dependency note, quoted since it bounds when S1 can dispatch: "S1/S2 are dispatchable
on the next free GPU window after the C-EFF composition A/B (which holds first claim)." The
composition A/B has since landed (§4 below) — its own next step (real-shard confirmation) is still
open, which is separately relevant to S1's throughput basis, not a blocker on S1 itself.

### 1.2 `docs/spec/conditions-v1.md` C-SCALE registry text — the W1 fields, verbatim

`docs/spec/conditions-v1.md` (§4.2, C-SCALE): the CHK a scale-credibility receipt must record —

> {operating_capability_point (>3B), W1:{measured_tokens_to_base, projected_dense_tokens_to_base,
> token_bill_collapse_ratio>1, growth_lineage_from_cbase_seed, no_borrowed_weights_load_bearing=true},
> W2:{...}, measured_flops_to_capability, projected_dense_flops_to_capability (6ND),
> capability_per_compute_ratio>1, contribution_deletion_collapses_excess=true,
> active_working_set_bytes ≤ device floor}

`scripts/ember_totality/test_c_scale.py`'s `INVALID_TOKENS` (lines 54-60, quoted in full):

```
INVALID_TOKENS = [
    "toy_scale_not_undismissable",
    "invalid_fixed_scale_convenience",
    "invalid_hardware_exit_ramp",
    "invalid_memory_fit_as_scale_affordability",
    "invalid_borrowed_base_as_owned_scale",
]
```

`SCALE_FLOOR_PARAMS = 3e9` (line 62). The probe's `check_candidate()` requires, in order (lines
89-140): `operating_capability_point` numeric and `> 3e9`; a `W1` dict whose
`token_bill_collapse_ratio` re-derives from `projected_dense_tokens_to_base /
measured_tokens_to_base` within 1% (`_ratio_ok`, lines 75-86) and is `> 1`;
`growth_lineage_from_cbase_seed` truthy; `no_borrowed_weights_load_bearing is True`. S1's own job is
producing the growth-chain lineage `W1.growth_lineage_from_cbase_seed` and
`W1.no_borrowed_weights_load_bearing` hinge on, plus the per-rung receipts S2's token-bill accounting
(already ratified, `docs/spec/c-scale-s2-token-bill-protocol.md`) consumes as its `measured_tokens_to_base`
numerator. **Scope note:** S1 does not itself compute `token_bill_collapse_ratio` or
`operating_capability_point` acceptance against the `>3e9` floor — that is S2's ratified job, feeding
off S1's lineage. S1's job is the chain of receipted grow-steps themselves.

---

## 2. Growth operator mechanics (net2net FF-widening — the only receipted, coded operator on this lineage)

### 2.1 What the operator actually widens

`src/ember/governance/scripts/cbase_grow_dryrun.py::widen_state_dict` (execution tree — **absent as of 2026-07-03 in this
contract tree**, same status `docs/spec/growth-v1.md` already flags; read cross-tree per the
established import-edition convention) is the entire surgery, quoted in full:

```python
def widen_state_dict(sd: dict, n_layers: int) -> dict:
    grown = dict(sd)
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        g, u, d = sd[p + "gate_proj.weight"], sd[p + "up_proj.weight"], sd[p + "down_proj.weight"]
        grown[p + "gate_proj.weight"] = torch.cat([g, g], dim=0)
        grown[p + "up_proj.weight"] = torch.cat([u, u], dim=0)
        grown[p + "down_proj.weight"] = torch.cat([d * 0.5, d * 0.5], dim=1)
    return grown
```

This touches **only the SwiGLU MLP's three matrices per layer** (`gate_proj`, `up_proj`,
`down_proj`) — it duplicates gate/up rows (doubling `intermediate_size`) and halves+duplicates
down_proj columns to sum back to the exact seed output. **It does not touch attention (`q/k/v/o_proj`),
hidden size, layer count, head count, or vocab** — every one of those stays fixed at the seed's
values (`hidden=1024, layers=20, heads=16, vocab=32000`, per `configs/v0-pretrain-config.json`)
through every application of this operator. `ff_grown = ff_seed * 2` is **hardcoded** in the caller
(`cbase_grow_live.py` line 252: `ff_grown = ff_seed * 2`) — the surgery is an exact doubling, not a
parameterized factor; there is no code path for a non-2x widening ratio.

**Direct answer to "can it widen depth as well as width?": no.** Depthwise growth (`G_stack`,
composing `g` copies of the trained base) is a *separate*, unreceipted operator class.
`docs/spec/growth-v1.md` §1 names `G_stack` the "PRIMARY CANDIDATE" architecturally, but its own
validation-hook section states the identity-preservation proof has only run "FP-exact on toy net;
**c03-scale outstanding**" (`receipts/proof-growth-identity-20260702T064211Z.json`, RUN 2026-07-02) —
i.e. depthwise stacking has never been proven, let alone receipted, at this lineage's actual
architecture. Issue #29's own phrasing ("successive net2net **width/depth** steps") names a
capability that does not exist in code today; only width (FF) steps are buildable from what's on
disk. This is flagged as **PRE-REGISTRATION DECISION 3** below, not resolved here.

**No integer head/dim constraint arises** from this operator, because it never touches `hidden` or
`heads` — `head_dim = hidden/heads = 64` is invariant across every FF-widening step. The only
"constraint" is the hardcoded exact-2x factor (§3 below works out what that means for reachable rung
sizes).

### 2.2 Function-preservation results (both receipted grow events, quoted in full)

| Event | Receipt | Mechanism check | `logit_max_abs_diff` | Tolerance | Verdict |
|---|---|---|---|---|---|
| Dry-run (CPU, fp32, no training) | `receipts/cbase-grow-dryrun-20260702T190532Z.json` | same fixed batch, pre-grow vs freshly-grown forward pass | `3.337860107421875e-06` | `1e-4` | `GROW_DRYRUN_PASS` |
| Live (GPU, real governed training) | `receipts/cbase-grow-live/cbase-grow-live-live-20260703T053225Z.json` | identical mechanism, applied mid-training | `2.384185791015625e-06` | `1e-4` | `GROW_LIVE_PASS` |

Both pass by roughly two orders of magnitude of margin — the issue's own "fp_diff 2.4e-6 precedent"
is the live-run figure, quoted exactly. Issue #29's kill criterion ("function-preservation fp_diff
>1e-3") has ~42x margin on the dry-run figure and ~42x on the live figure before either would trip.

### 2.3 The stabilization segment — precedent shape

The one grow event executed so far: `k_steps_pre_grow=60` (steps 610→670, ff=4096, loss
10.125→8.125) + `k_steps_post_grow=60` (steps 670→730, ff=8192, loss 9.9375→7.5625) = **120 steps**,
`batch=16, seq=1024` → **1,966,080 tokens** for the post-grow-window total (`120 * 16 * 1024`,
matching the exact figure `docs/spec/c-scale-s2-token-bill-protocol.md` §2 already cites). Loss
continuity: `grow_step_delta=1.8125` vs pre-grow step-to-step jump envelope (`max=2.8125,
mean=0.680085, stdev=0.644668` over 59 jumps) — `training_loss_continuity_within_pre_grow_variance_envelope:
true`. `optimizer_reset_on_resume: true` — per `docs/spec/growth-v1.md` §7's binding default, the
whole model's optimizer state (Muon momentum + AdamW state alike) resets at every grow event; no
accumulator is carried across the shape change.

**Per-width token banking — already present in the receipt, exactly what issue #29's S1 clause asks
for ("per-step token accounting banked, tokens spent at each width")**: tokens at `ff=4096` =
9,994,240 (original pretrain, `receipts/v0-live-20260623T105829Z.json`) + 983,040 (60-step pre-grow
continuation, `60*16*1024`) = **10,977,280 tokens at ff=4096**; tokens at `ff=8192` = 983,040 so far
(`60*16*1024`, steps 670→730) — **10,977,280 + 983,040 = 11,960,320 total lineage tokens**, matching
S2 §2's already-computed figure exactly. The receipt format already implements the per-width
accounting the issue asks for; no new field is needed, only continuation at the next grow event.

---

## 3. Per-rung parameter math

### 3.1 Deriving the exact formula from the two receipted points (not assumed)

`scripts/cbase_grow_live.py::_backbone_param_estimate` (execution tree — **absent as of 2026-07-03 in
this contract tree**, same status as §2.1's `cbase_grow_dryrun.py`) gives the general per-layer form
(hidden=1024, layers=20, vocab=32000 fixed): `per_layer = 4*hidden² + 3*hidden*ff + 2*hidden`.
Isolating the FF-dependent term: `FF_term(ff) = layers * 3 * hidden * ff = 20*3*1024*ff = 61,440 * ff`.
Subtracting this from the two **measured** (not estimated) receipted param counts:

- At `ff=4096` (seed, `param_count_before=466,658,304`): `466,658,304 − 61,440*4096 = 466,658,304 −
  251,658,240 = 215,000,064`
- At `ff=8192` (grown, `param_count_after=718,316,544`): `718,316,544 − 61,440*8192 = 718,316,544 −
  503,316,480 = 215,000,064`

**Both receipted points give the identical non-FF residual (215,000,064) — confirming the formula**

```
N(ff) = 215,000,064 + 61,440 * ff
```

**re-derives both measured points exactly**, not just the seed used to fit it. This is the load-bearing
formula for every rung below.

### 3.2 A freshly-derived discrepancy in the residual itself (flagged, not resolved)

Decomposing 215,000,064 against the actual architecture (hidden=1024, layers=20, vocab=32000,
`tied_embeddings: true`, `mtp_aux_heads.n_heads: 2`, all per `configs/v0-pretrain-config.json`):
attention (`4*hidden²*layers` = 83,886,080) + norms (`2*hidden*layers + hidden` = 41,984) leaves a
residual of `215,000,064 − 83,886,080 − 41,984 = 131,072,000`, which is **exactly 4 × (vocab*hidden)**
(`4 * 32,768,000 = 131,072,000`) — i.e. **four** separate `vocab×hidden`-sized matrices, not three.
Three would be the tied-embedding-correct count (1 shared embed/head matrix + 2 untied MTP heads).
Reading `scripts/timeshare_pretrain.py` lines 1138-1148 (the actual production model-builder,
execution tree): `LlamaConfig(..., tie_word_embeddings=False)` (HF-internal tying disabled) followed
by a manual `if m["tied_embeddings"]: self.head.weight = self.backbone_model.embed_tokens.weight` —
this **does** functionally tie `head.weight` to `embed_tokens.weight` (same Parameter object, one
set of gradients). But a plain `state_dict()` numel sum (which is what `sum(v.numel() for v in
sd.values())` in `cbase_grow_live.py`'s receipt-writing code computes) lists **both** module
attributes (`backbone_model.embed_tokens.weight` and `head.weight`) as separate dict entries even
though they alias the same tensor — a standard PyTorch/HF tied-weight quirk, not a training defect.
The arithmetic checks out exactly: `83,886,080 + 41,984 + 32,768,000(embed) + 32,768,000(head,
DUPLICATE alias) + 32,768,000(mtp_0) + 32,768,000(mtp_1) = 215,000,064`. **Every receipted
`param_count_before`/`param_count_after` field to date therefore over-counts the true number of
independently-stored parameters by exactly 32,768,000 (the tied matrix, counted twice)** — a constant
absolute amount regardless of `ff`, so its *relative* share shrinks as rungs grow (4.6% of the current
718.3M point; 0.77% of the 4.24B candidate target, §3.3). **PRE-REGISTRATION DECISION 4**: whether
`operating_capability_point` at future rungs uses the receipted state_dict-sum convention (as today,
consistent with S2's own ruling to resolve discrepancies "in favor of the measurement") or a
deduplicated true-unique-parameter count. Flagged here, not decided.

### 3.3 The only receipt-consistent ladder available today: strict FF-doubling

Because the operator hardcodes exact 2x widening and touches nothing but FF, the **only** sequence of
rungs reachable without new code is repeated doubling from the current landed point (`ff=8192`):

| Rung | `ff` | `N(ff) = 215,000,064 + 61,440*ff` | vs current | Muon-blend VRAM | Full-AdamW VRAM | Fits governed floor (19.19 GiB)? |
|---|---|---|---|---|---|---|
| current (landed) | 8,192 | 718,316,544 (~718.3M) | — | 6.33 GiB | 10.70 GiB | yes, ample |
| rung 1 | 16,384 | 1,221,633,024 (~1.222B) | 1.70x | 10.08 GiB | 18.20 GiB | muon-blend yes (~9.1 GiB headroom); full-AdamW yes but only ~0.99 GiB headroom (below the 1.5 GiB governor margin floor) |
| rung 2 | 32,768 | 2,228,265,984 (~2.228B) | 3.10x | 17.58 GiB | 33.20 GiB | muon-blend yes but only ~1.61 GiB headroom (no room for activations); full-AdamW **no** |
| target | 65,536 | 4,241,531,904 (~4.242B) | 5.90x | 32.58 GiB | 63.20 GiB | **no, both bounds** — exceeds the raw 24 GiB card entirely |

VRAM formula (same convention `docs/spec/growth-v1.md` §8 already uses, computed here exactly per
rung rather than by an approximate 90/10 split): Muon-optimized hidden-2D matrices (attention +
MLP, `docs/domains/governance/design/fp44-multimodal-optimizer-decision.md`'s default) at **8 B/param** (2 bf16 weight + 2 bf16
grad + 4 fp32 momentum, no `v`, no fp32 master); AdamW-optimized embed/norm/head/MTP-head matrices at
**16 B/param** (full state). Per rung: `params_muon(ff) = 83,886,080 + 61,440*ff`; `params_adamw =
131,113,984` (constant — embed/head/norms/MTP fixed regardless of ff, using the state-dict-sum
convention of §3.2). `VRAM = params_muon*8 + params_adamw*16` bytes. Governed floor =
`0.80 * 23.99 GiB = 19.19 GiB` (measured `total_gib`, governor blocks throughout this receipt family).

**This table extends `docs/spec/growth-v1.md` §8's illustrative table (which used the planning-estimate
ladder 368.4M→0.8B→1.6B→3B) with the REAL operator's REAL reachable rungs, computed exactly rather
than approximately.** The qualitative conclusion is the same and sharper: the target rung's VRAM
exceeds the raw 24 GiB card under both bounds, confirming §8's "consequence, previously implicit, now
stated" applies to this actual ladder, not just the illustrative one.

**Honesty rail, stated explicitly per `invalid_memory_fit_as_scale_affordability`:** the "fits governed
floor" column above is an **engineering feasibility check only** — whether the grown checkpoint's
optimizer state physically fits in VRAM at all — and is never itself an affordability or scale-
credibility argument. A rung fitting VRAM says nothing about whether growing to it was *cheap*
(that is S2's token-bill-collapse job, §1.2) or whether the resulting capability is *dense-undismissable*
(C-SCALE's own W1(i) test). "Fits" and "affordable"/"credible" are answered by disjoint receipts; this
table only ever answers the first.

**The strict-doubling ladder overshoots the `>3e9` floor by ~41.4%** (lands at 4.242B where 3.0B was
the floor), with **no intermediate rung available** between 2.228B and 4.242B under the current
exact-2x-only operator. Landing closer to the floor (e.g. `ff≈49,152` → `N≈3.235B`, or `ff≈45,337` for
`N≈3.000B` exactly) would require a **generalized, non-doubling widening operator that does not exist
in code today** — the current surgery only supports `cat([w,w])`-style exact duplication, not an
arbitrary fractional widening factor. **PRE-REGISTRATION DECISION 2**: accept the doubling-only
overshoot to ~4.24B as the S1 target, or authorize building a generalized fractional-widening operator
first (new code, no receipt, own EARNED/identity-preservation obligations under `docs/spec/growth-v1.md`
§1-§2 before it could be used).

---

## 4. Throughput basis per rung

### 4.1 What's receipted at the production shape today

| Optimizer/config | Receipt | `tok_s_paced` | Compile status | Note |
|---|---|---|---|---|
| `muon_split` (production config, real 2026-06-23 run) | `receipts/c04-design-bench-c03-h1024-d20-20260623T024512Z.json` | 19,874.8 | PASS | batch=16, seq=1024, mtp_heads=2 — the actual v0 pretrain segment's own config |
| `muon_split` A_baseline arm (composition A/B, 2026-07-03) | `receipts/ceff-composition-ab-20260703T111351Z.json` (execution tree — **absent as of 2026-07-03 in this contract tree**) | 15,934.32 | not stated in receipt | same nominal config (batch=16, seq=1024, `n_muon=140, n_adamw=44`, `routing_mode: muon_split`) |
| `D_both_composed` (fused-NS5-kernel compile × bf16-NS5 dtype swap) | same composition receipt, arm D | 19,094.38 | not stated | `verdict: COMPOSITION_CLOSES_RESIDUAL_GAP`; synthetic batches (fixed-seed `torch.randint`), **not real PackedShardLoader shards** |

**Honesty flag — an unresolved receipt-vs-receipt discrepancy, surfaced not silently reconciled:** the
design-bench receipt and the composition A/B's own `A_baseline` arm both claim to measure the
identical config (`muon_split`, batch=16, seq=1024, mtp_heads=2, `cut_ce_chunked`) ten days apart, yet
report **19,874.8 vs 15,934.32 tok/s paced — a ~19.8% gap** with no stated cause (governor free_gib
was 22.45 GiB in both governor blocks quoted; no compile-status field distinguishes them in the
composition receipt). Whichever number governs future rung throughput planning should be the one a
reviewer can trace to a specific measured cause, not whichever is more convenient — flagged here as an
open item, not resolved.

**Pending closure confirmation (item the team-lead's assignment named directly):** the composition
receipt's own `corpus_shards_note` states plainly: "synthetic batches, not real PackedShardLoader
shards... **real-shard confirmation is the ladder's own §(e) next step if this cell keeps**"
(`docs/spec/ceff-lever-ladder.md` §(e) item 1's plan — absent as of 2026-08-01 in this contract
tree, unmerged to master: bench-shape cell → quality recheck → "a full
60M-token confirmation run (≈50–65 min) if both keep"). The 19,094.38 tok/s `D_both_composed` figure
is therefore **not yet production-confirmed** — it is a bench-shape/synthetic-data measurement whose
own governing doc names the outstanding step.

### 4.2 The projection-grade rule, and what it rules out for wider rungs

`docs/spec/c-scale-s2-token-bill-protocol.md` §3.2 already establishes the rule this dossier inherits:
throughput numbers with `compile_status: "BREAK"` are eager-mode numbers mislabeled by an attempted-
but-failed compile, and **"must not be used directly to project wall-clock cost at larger widths."**
The only in-tree throughput receipts at widths beyond `h1024` (`h2048-d12/d14`, `h2304-d12`,
`h2560-d12`, all `receipts/c04-design-bench-h*`) are **every one of them `compile_status: BREAK`** —
banned from projection by this same rule.

**Direct consequence for S1's rungs: there is no compile-PASS throughput receipt at ANY of the FF-widened
shapes this dossier's rungs actually need** (`ff=16384/32768/65536`, all at `hidden=1024, layers=20` —
a different axis than the h2048+ family's hidden-widening, and untested regardless). Every rung beyond
the current landed point needs a **fresh, compile-PASS throughput receipt at its own actual shape**
before its stabilization segment's wall-clock cost (or its G-budget requested-run cost, §5) can be
priced from measurement rather than formula. This is a hard prerequisite, not a nice-to-have — it
directly bounds Option C in §6 below.

---

## 5. G-budget / SHATTER interaction

### 5.1 A version-drift finding: the contract tree's copy lacks the mechanism this section needs

`src/ember/governance/scripts/v0_pretrain_launch_gate.py`'s `gate()`/`g_budget()` **in this contract tree** take no
`requested_run` parameter at all (read directly, lines 383/540-553 of the contract-tree copy). The
**execution tree's** copy of the identical filename (`src/ember/governance/scripts/v0_pretrain_launch_gate.py`, execution
tree root) has a materially different, newer `g_budget(launch_date, shatter_fit=None, requested_run=None)` plus a
`_requested_run_compute_fit()` helper and `MICRO_FIT_CEILING_FLOPS`/`MICRO_FIT_FRACTION` constants —
the exact mechanism `scripts/cbase_grow_live.py` and the composition A/B receipt's own `g_budget`
block already depend on and cite in practice (§4.1). **The contract tree's launch-gate script is stale
relative to the one actually gating GPU dispatch decisions today** — a real drift on a script whose
job is refusing unsafe launches, flagged here (build target: import the execution tree's newer copy
into this contract tree before any rung's dispatch receipt cites this gate — **absent as of
2026-07-03 in this contract tree**, per the same convention `docs/spec/growth-v1.md` uses for the
grow scripts themselves).

### 5.2 The fixed micro-fit ceiling — live-executed

`MICRO_FIT_CEILING_FLOPS = MICRO_FIT_FRACTION(0.005) * SHATTER_BUDGET_B(2.2e9) *
6.0 * V0_CERTIFIED_PARAMS(368,354,304)` — this document imported the **execution tree's** copy
read-only (no GPU, no edits) and evaluated it directly:

```
MICRO_FIT_CEILING_FLOPS = 2.4311384064e+16
```

matching the composition A/B receipt's own stated ceiling exactly (§4.1's `2.431e+16`). **This ceiling
is a FIXED absolute number derived from the certified 368,354,304-param pin — it does not scale with
the actual params of whatever run is being priced.** This matters directly for S1: as rungs grow, the
same step-count stabilization segment consumes a growing fraction of a ceiling that never grows.

> **[ACCOUNTING ERRATA 2026-07-10]** The certified count 368,354,304 is n_mtp=0; realized production count with 2 live MTP heads is 433,890,304 (+65,536,000). The MICRO_FIT_CEILING calculation above uses the certified count; for actual production runs, verify the ceiling against the realized parameter count. See [errata issue #679](https://github.com/wordingone/ember/issues/679).

> **Current implementation supersession:** the launch gate now derives its
> fixed ceiling from `V0_REALIZED_PARAMS=433,890,304`, producing
> `MICRO_FIT_CEILING_FLOPS=2.8636760064e+16`. The earlier formula is historical.

### 5.3 Live results for the four candidate rungs (executed 2026-07-03, pure Python, no CUDA)

Calling `g_budget()` with a `requested_run` descriptor (`total_steps=120, batch=16, seq=1024`,
matching the landed precedent's shape exactly) at each rung's measured `N` from §3.3:

```
baseline (no descriptor): BLOCKED — days-remaining -11 < envelope floor 4.55; no banked SHATTER
  compute-fit (shatter-verdict-canonical-20260623.json variants[muon_split].sustained_tok_s not
  numeric/positive)
current (718,316,544, 120 steps):  GREEN — cost=8.474e+15 FLOPs vs ceiling 2.431e+16 -> FIT
rung 1  (1,221,633,024, 120 steps): GREEN — cost=1.441e+16 FLOPs vs ceiling 2.431e+16 -> FIT
rung 2  (2,228,265,984, 120 steps): BLOCKED (exceeds micro-fit ceiling, falls through to the same
  calendar/SHATTER path as baseline -> BLOCKED, identical reason)
target  (4,241,531,904, 120 steps): BLOCKED (same fallthrough)
```

**Honest calendar-deadline state, re-confirmed live and unchanged from S2 §3.3's finding**: the
calendar deadline (2026-06-22) has passed by 11 days; both on-disk SHATTER verdict receipts
(`shatter-verdict-canonical-20260623.json`, `shatter-verdict-bf16ns5-20260623T132000Z.json`) still
fail the gate's own anti-self-reference recompute — one has a non-numeric `sustained_tok_s`, the
other's stated `effective_days=0.9803` disagrees with the honest recompute `1.3007`. **G-budget for
any full-ladder (non-micro-fit) dispatch is BLOCKED today**, exactly as S2 already found; nothing in
this dossier changes that state.

**Derived consequence — the fixed ceiling means larger rungs get fewer "free" steps, not more, as they
grow**: solving `steps_max(N) = MICRO_FIT_CEILING_FLOPS / (6 * N * batch * seq)` for each rung:

| Rung | `N` | `steps_max` at fixed ceiling (batch=16, seq=1024) | 120-step precedent still fits? |
|---|---|---|---|
| current | 718,316,544 | ~344 | yes (used 120) |
| rung 1 | 1,221,633,024 | ~203 | yes |
| rung 2 | 2,228,265,984 | ~111 | **no — just under 120** |
| target | 4,241,531,904 | ~58 | **no — under half of 120** |

The 120-step precedent (the only stabilization segment ever actually run) stops fitting the
micro-fit path **exactly at rung 2** — meaning a flat "same as last time" sizing rule silently
requires the currently-BLOCKED full SHATTER/calendar path from rung 2 onward, not a hypothetical
future concern. This feeds directly into §6.

---

## 6. Stabilization-segment sizing — three honest options, none decided here

Per S2's ratified accounting (Reading A, lineage-path-only, cumulative gradient-touched tokens from
the certified seed). Precedent per-step token cost: `16*1024 = 16,384` tokens/step.

**Option A — fixed step count (120/rung, 60 pre + 60 post, byte-identical to the landed precedent).**
Simplest rule; token bill is flat regardless of rung size (`120 * 16,384 = 1,966,080` tokens/rung).
Projected total lineage tokens through the target rung (3 more rungs, **illustrative only, not a
claim — the current point is 4.2x below the floor per S2 §4.3's own caution**):
`11,960,320 + 3*1,966,080 = 17,858,560`. **G-budget consequence (§5.3, live-verified): FITS the fixed
micro-fit ceiling only through rung 1; rung 2 and the target rung EXCEED it and fall to the
currently-BLOCKED calendar/SHATTER path.** This option is simple but not currently dispatchable past
rung 1 without either a fresh passing SHATTER receipt or importing the requested_run fix (§5.1).

**Option B — fixed FLOPs budget per rung (held at the precedent's own measured post-grow segment
cost, `≈4.2375e15 FLOPs`).** Step count shrinks roughly as `1/N`: rung 1 ≈35 steps, rung 2 ≈19 steps,
target ≈10 steps. Token bills: rung 1 ≈573,440; rung 2 ≈311,296; target ≈163,840 — sum ≈1,048,576
across all three remaining rungs (projected total ≈13,008,896, far below Option A's 17,858,560).
**Guarantees micro-fit-ceiling eligibility by construction at every rung** (since FLOPs is held under
the ceiling by design), but shrinks the actual stabilization exposure sharply exactly where the "post-grow
train segment within pre-grow loss envelope" kill criterion (issue #29) is least precedented — only
ever tested at 60 steps at the 718.3M scale. Ten steps at the target rung is under one-sixth of the one
precedent that exists; whether that is enough steps to distinguish genuine post-grow stability from a
too-short window that simply hasn't diverged yet is an open, unresolved question, not a formality.

**Option C — fixed wall-clock budget per rung (held at the precedent's own post-grow `wall_s=88.095`).**
Step count = `88.095s / seconds-per-step at that rung's own shape`. **Cannot be computed with real
numbers today for rung 1/2/target** — per §4.2, there is no compile-PASS throughput receipt at any
FF-widened shape (`ff=16384/32768/65536`); the only wider-shape numbers on disk are the h2048+ family,
all `compile_status: BREAK` and explicitly banned from projection by the S2-established rule. This
option is the most operationally honest (ties sizing to actual measured wall-clock, the real GPU-day
currency every other gate in this repo uses) but is **blocked on a prerequisite this dossier cannot
supply**: fresh throughput receipts at each candidate rung's actual shape, which do not exist and
require their own GPU window before Option C's numbers are anything but a formula.

None of the three is free of an open decision. **PRE-REGISTRATION DECISION 1**: which rule (or a
fourth not enumerated here) governs, and its exact free parameters (step count, FLOPs ceiling, or
wall-clock target) per rung — this dossier deliberately does not choose.

---

## 7. Pre-registration decisions (session decides; not resolved here)

1. **Stabilization-segment sizing rule** (§6): Option A (fixed steps, simple, hits the micro-fit
   ceiling wall at rung 2) vs Option B (fixed FLOPs, always fits, but shrinks stabilization exposure
   to ~10 steps at the target rung, untested at that shortness) vs Option C (fixed wall-clock, most
   honest, blocked on throughput receipts that don't exist yet) vs a rule not enumerated here.
2. **Rung sizing / count**: accept the strict-doubling-only ladder's overshoot to ~4.242B (~41.4% over
   the `>3e9` floor, no intermediate rung reachable, §3.3) as the S1 target, or authorize building a
   generalized non-doubling widening operator (new code, unreceipted, its own EARNED/identity-
   preservation obligations) to land closer to the floor (e.g. `ff≈49,152` → `N≈3.235B`).
3. **Width-only vs "width/depth"**: issue #29's own text says "width/depth steps," but depthwise
   growth (`G_stack`) has zero receipts at this lineage's actual architecture (only a toy-net proof,
   explicitly "c03-scale outstanding" per `docs/spec/growth-v1.md`). Whether S1 is satisfied by
   width-only (FF) steps alone, or requires at least one depth step before counting as the "width/depth"
   the issue names, is the session's call.
4. **Parameter-count convention** (§3.2): whether `operating_capability_point` uses the receipted
   state_dict-sum convention (double-counts the tied embed/head matrix, a freshly-derived and
   previously unflagged discrepancy) or a deduplicated true-unique-parameter count.
5. **G-budget path for rung 2+** (§5): whether these rungs wait for a fresh, passing SHATTER receipt
   (today: both on-disk SHATTER receipts fail anti-self-reference; calendar deadline expired 11 days)
   before their dispatch can go GREEN, and whether the contract tree's stale `v0_pretrain_launch_gate.py`
   (missing the `requested_run` mechanism entirely, §5.1) must be updated from the execution tree first.
6. **VRAM feasibility routes for rung 2/target** (§3.3): rung 2 is tight under the Muon-blend bound
   (~1.6 GiB headroom, no room costed for activations) and infeasible under full-AdamW; the target rung
   is infeasible under **both** bounds on the raw 24 GiB card. `docs/spec/growth-v1.md` §8 already names
   three routes (parameter-efficient deltas / further-reduced-precision optimizer states / host-RAM
   streaming) for the analogous W2 wall — whether/how these are priced and authorized for the S1
   PRETRAIN case before rung-open at rung 2 or the target is the session's call, per §8's own completion
   criterion ("that pricing must extend to the target-rung PRETRAIN case before rung-open at target
   size").

---

## 8. Citation-checker verification

`python src/ember/governance/scripts/check_goal_citations.py` was run against the repo (this document included, under
`docs/spec/`) — three times: the first pass caught a real gap (a citation of `scripts/cbase_grow_live.py`
in §3.1 with no adjacent absent-marker, plus a typo that mis-prefixed the same filename under the
wrong top-level directory in §5.1), both fixed; a second pass then caught the same filename appearing
a third time, unprefixed, inside this very verification paragraph's own description of the first fix
(the checker cannot distinguish prose-about-a-citation from a citation) — reworded to describe the
defect without repeating the path string. Final result, quoted verbatim:

```
check_goal_citations v4: 43 docs scanned, 726 refs checked, 0 allowlisted, 59 templated-skipped,
12 wrap-joined, 22 documented-absent, 45 stale-absent-marker, 0 cross-tree, 44 anchors checked,
0 anchor-suppressed, 28 row-ids checked (21 map rows)
MISSING: none
ANCHOR-MISS: none
ROW-ID-MISS: none
receipt: receipts/citation-check-20260703T122221Z.json
pass=True
```

Zero missing citations repo-wide. This document contributes 3 of the run's 22 documented-absent
citations — the execution-tree-only paths it names and explicitly marks absent-in-contract-tree at
the citation site: `src/ember/governance/scripts/cbase_grow_dryrun.py` (line 85), `scripts/cbase_grow_live.py` (line 162),
`receipts/ceff-composition-ab-20260703T111351Z.json` (line 262) — each carries the "absent as of
2026-07-03 in this contract tree" marker per the checker's own documented convention (§2 of its module
docstring), confirmed directly against `receipts/citation-check-20260703T122221Z.json`'s
`documented_absent` array.

---

## Citations

`GOAL.md` · `docs/spec/conditions-v1.md` · `docs/spec/growth-v1.md` ·
`docs/spec/c-scale-s2-token-bill-protocol.md` · `docs/spec/ceff-lever-ladder.md` ·
`docs/domains/governance/design/fp44-multimodal-optimizer-decision.md` · `scripts/ember_totality/test_c_scale.py` ·
`src/ember/governance/scripts/v0_pretrain_launch_gate.py` · `src/ember/governance/scripts/cbase_grow_dryrun.py` · `scripts/cbase_grow_live.py` ·
`scripts/timeshare_pretrain.py` · `src/ember/governance/scripts/check_goal_citations.py` ·
`configs/v0-pretrain-config.json` ·
`receipts/v0-live-20260623T105829Z.json` ·
`receipts/cbase-grow-dryrun-20260702T190532Z.json` ·
`receipts/cbase-grow-live/cbase-grow-live-live-20260703T053225Z.json` ·
`receipts/c04-design-bench-c03-h1024-d20-20260623T024512Z.json` ·
`receipts/ceff-composition-ab-20260703T111351Z.json` ·
`receipts/proof-growth-identity-20260702T064211Z.json` ·
`receipts/proof-feasibility-20260702T064430Z.json` ·
`receipts/shatter-verdict-canonical-20260623.json` ·
`receipts/shatter-verdict-bf16ns5-20260623T132000Z.json` — both SHATTER receipts are absent as of 2026-08-01 in this contract tree (the gate-9 closure landed on the C-EFF efficiency lane, unmerged to master).

---

## 9. PRE-REGISTRATION (binding rulings on the six decisions — session, 2026-07-03)

These rulings are the binding interpretation for every S1 rung fired after this landing. Changing
any of them requires a new dated block here BEFORE the affected rung fires, never after its receipt
exists.

**D1 — Sizing rule: Option B (fixed FLOPs per rung, held at the precedent's measured post-grow
segment cost ~=4.2375e15 FLOPs) with a 30-step minimum floor.** steps(rung) =
max(ceil(4.2375e15 / (6*N*16*1024)), 30). Rationale: Option A is not dispatchable past rung 1
(lands on the BLOCKED calendar/SHATTER path, section 5.3); Option C is circular today (needs
throughput receipts only the rung runs themselves will produce — each rung run MUST bank its own
compile-status-honest throughput receipt, which arms Option C as a future re-registration).
The floor cures Option B's worst property: exposure at the target rung rises from ~10 to 30 steps
while staying micro-fit-eligible everywhere (30 < steps_max=58 at the target; verified against
section 5.3's table). The issue-#29 kill criterion is unchanged: post-grow segment loss within the
pre-grow envelope, else the rung is a kill receipt, never a retry-in-place.

**D2 — Ladder: the strict-doubling ladder (1.222B -> 2.228B -> 4.242B) is accepted, CONDITIONALLY.**
The overshoot to ~4.242B violates nothing in W1 (floor is `>3e9`), and a generalized non-doubling
operator is new unreceipted code with its own identity-preservation burden. The condition: D6's
pricing receipt must prove a receipted VRAM route exists for each rung BEFORE that rung opens.
Live arithmetic at this registration: the target rung at bf16-momentum (6 B/param) is 23.7 GiB
against the raw 24 GiB card — under the raw number but with no headroom for activations/allocator/
CUDA context, i.e. NOT presumed feasible; the ~3.235B point (ff~=49,152, generalized operator)
prices at 18.1 GiB under the same bound. **Pre-registered fallback (not scope reduction): if D6's
rung-open pricing shows no receipted route fits the 4.242B rung, the generalized widening operator
to ff~=49,152 becomes the directed path for the final rung** — with its own EARNED/function-
preservation receipts at parity with the doubling operator's (fp_diff tolerance 1e-4, same
echo/identity proof shape).

**D3 — Width-only satisfies S1's chain.** Issue #29's "width/depth steps" is read as enumerating
the operator family, not conjoining both axes. Depthwise G_stack has zero receipts at this
architecture (toy-net proof only, "c03-scale outstanding" per growth-v1.md) and no W1 field depends
on depth. The alternative (conjunctive) reading is preserved: if later ruled conjunctive, one
G_stack rung is added to the chain with its own receipts; nothing in this ladder forecloses it.

**D4 — Parameter convention: the deduplicated true-unique count is authoritative for
`operating_capability_point`; receipts carry BOTH.** Every rung receipt reports
`params_state_dict_sum` (continuity with the two existing receipted points, which double-count the
tied embed/head matrix by +32,772,096) and `params_unique` (authoritative for the `>3e9` floor and
for S2's 20N math). At the target rung the unique count is 4,208,759,808 — the floor clears under
either convention; honesty prefers the one that cannot be accused of padding.

**D5 — G-budget path: NO rung depends on the blocked calendar/SHATTER path.** D1's Option B keeps
every rung inside the micro-fit ceiling by construction, so S1 requires no fresh SHATTER receipt.
Precondition landed with this block: the contract tree's `src/ember/governance/scripts/v0_pretrain_launch_gate.py` is
synced byte-identical from the execution tree (the stale copy lacked the `requested_run` micro-fit
mechanism this section's live results and every rung dispatch depend on; sha mismatch verified
f3617d6a... vs 3e87a4d0... pre-sync).

**D6 — VRAM route: reduced-precision optimizer state (bf16 momentum) is the single authorized
route for rung 2+, priced by receipt BEFORE rung-2 open; host-RAM streaming is the registered
fallback; parameter-efficient deltas are BANNED for S1 pretrain** (a delta-parameterized chain
would hollow out `no_borrowed_weights_load_bearing` / owned-scale semantics — S1's chain is
full-parameter by definition). The pricing obligation: before rung 2 opens, a receipted A/B at the
CURRENT shape (718.3M, where both arms fit comfortably) proving bf16-momentum loss-trajectory
equivalence under protocol-v2-style conjuncts (max-abs delta bound at bf16 granularity + trajectory
equality + an optimizer-state-health check), then the same guard re-run as a smoke at each rung
before its stabilization segment counts. If the priced route still cannot fit a rung, D2's fallback
fires for that rung.

**Dispatch order bound by this block:** rung 1 (1.222B) may open immediately after the D5 gate-sync
lands (it fits every current constraint with no new receipts); the D6 pricing A/B runs before or
alongside rung 1's window; rung 2 opens only after the D6 receipt exists.

---

## 10. Dated corrections to section 9 (2026-07-03, at rung-runner landing — factual, no ruling changed)

1. **D4 dedup constant corrected: the tied embed/head duplicate is 32,768,000 parameters
   (32000 vocab x 1024 hidden), not the "+32,772,096" section 9's prose carried** (itself
   inherited from section 3.2's flagged-but-unresolved residual). The builder measured it
   directly via data_ptr aliasing on the real on-disk parent checkpoint (embed_tokens.weight
   and head.weight share storage after torch.load) — measurement beats both prose numbers.
   Corrected unique count at the target rung: 4,208,763,904. No ruling changes: the floor
   clears under either constant.
2. **D1 exact step count at rung 1 is 36, not the "~35" of section 6**: the runner derives the
   anchor FLOPs from the precedent receipt's own params/batch/seq/steps rather than the spec's
   rounded ~=4.2375e15. The formula (not any literal) is binding; rung-2/target still floor to 30.
3. **Kill tolerance ratified at 1e-4** (the already-receipted PASS_TOL of both landed grow
   events), tighter than issue #29's prose 1e-3. Tighter-than-directed is not scope reduction.
4. **D6 pre-finding (measured on CPU, pending live confirmation at the real shape): production
   momentum state is ALREADY bfloat16-native** — no autocast/GradScaler/fp32 master weights
   anywhere in the optimizer construction path. If the live A/B confirms, section 3.3's
   8 B/param rows priced a phantom route and the REAL per-param optimizer footprint is
   ~6 B/param at production dtype today; the 23.7 GiB zero-headroom figure at the 4.242B target
   is then the CURRENT-production number, and D2's conditional fallback remains armed unchanged.
