# D6 VRAM pricing note — three conventions, sourced constants (2026-07-06)

Companion note to `docs/domains/governance/spec/c-scale-s1-growth-chain-DRAFT.md` §9 D6 and §10 correction #4.
Written while reconciling the S1 growth-chain artifacts onto master; not a spec, not a ruling —
a pricing recomputation with every constant traced to a receipt or file, so a reviewer can
re-derive every cell without trusting prose.

## Inputs (all cited, none assumed)

- `N(ff) = 215,000,064 + 61,440*ff` — the per-rung total parameter formula, re-derived in
  `c-scale-s1-growth-chain-DRAFT.md` §3.1 directly from the two receipted grow points
  (`param_count_before=466,658,304` at ff=4096, `param_count_after=718,316,544` at ff=8192);
  both give the identical non-FF residual 215,000,064, confirming the formula fits both
  measured points exactly rather than being fit-then-assumed.
- `params_muon(ff) = 83,886,080 + 61,440*ff` — attention (Muon-optimized, ff-independent) +
  the FF-dependent SwiGLU term (`3*hidden*ff*layers = 3*1024*ff*20 = 61,440*ff`), per §3.3.
- `params_adamw = 131,113,984` (constant across all rungs: embed/head/norms/MTP-heads,
  state_dict_sum convention — includes the tied embed/head duplicate per §3.2), per §3.3.
- Governed floor = `0.80 * 23.99 GiB = 19.19 GiB` (governor vram_fraction 0.80, measured
  `total_gib` from the D6 receipt's own governor block).
- **D6 receipt** (`receipts/d6-bf16-momentum-ab-20260703T160041Z.json`, landed this PR): a real
  GPU A/B at the current 718.3M shape, 50 steps, live. Arm A (production, unmodified) measures
  `momentum_buffer` (Muon) AND `exp_avg` (AdamW first moment) as `torch.bfloat16` already —
  zero code change needed to get bf16-native momentum. All three conjuncts pass: weight-delta
  at bf16 granularity (max_rel=0.00075 vs tol 0.0078), loss-trajectory equality (max_rel_delta
  0.0), optimizer-state health (all-finite both arms, momentum-norm ratio 1.000054 in band
  [0.9, 1.1]). Verdict `D6_ROUTE_PRICED_OK`.

## What the D6 receipt does NOT cover (flagged prominently, not glossed over)

The receipt's own `flags` array scopes the momentum-downcast hook to **"Muon momentum_buffer +
AdamW exp_avg, NOT exp_avg_sq/the v term."** AdamW's second moment (`exp_avg_sq`) and any
separate fp32 master-weight copy were never measured by this A/B. The 16 B/param AdamW figure
below is therefore **still an assumption carried from the original §3.3 table, not a
measurement** — it has not been re-priced the way the Muon rows have.

## Three pricing conventions

### 1. OLD (§3.3 as originally written): Muon @ 8 B/param (assumed, now falsified) + AdamW @ 16 B/param

| Rung | ff | N(ff) | VRAM (GiB) | vs 19.19 GiB floor |
|---|---|---|---|---|
| current | 8,192 | 718,316,544 | 6.329 | fits, 12.86 headroom |
| rung 1 | 16,384 | 1,221,633,024 | 10.079 | fits, 9.11 headroom |
| rung 2 | 32,768 | 2,228,265,984 | 17.579 | fits, only 1.60 headroom (no room for activations) |
| target | 65,536 | 4,241,531,904 | 32.579 | **fails** |
| fallback (ff~49,152) | 49,152 | 3,234,898,944 | 25.079 | **fails** |

### 2. CORRECTED-SPLIT: Muon @ 6 B/param (D6-measured) + AdamW @ 16 B/param (unchanged — see caveat above)

`VRAM = params_muon(ff)*6 + params_adamw*16` bytes.

| Rung | ff | VRAM (GiB) | vs 19.19 GiB floor |
|---|---|---|---|
| current | 8,192 | 5.235 | fits, 13.96 headroom |
| rung 1 | 16,384 | 8.048 | fits, 11.14 headroom |
| rung 2 | 32,768 | 13.673 | **fits, 5.52 GiB headroom** |
| target | 65,536 | 24.923 | **fails, -5.73 vs floor** |
| fallback (ff~49,152) | 49,152 | 19.298 | **fails by 0.11 GiB — too close to call** |

### 3. UNIFORM-6B: every parameter (Muon + AdamW) priced at 6 B/param

`VRAM = N(ff)*6` bytes. This reproduces §9 D2's own stated figures exactly (23.7 GiB at the
target, 18.1 GiB at the ff~49,152 fallback) — confirming this simplified uniform convention is
what D2's live-arithmetic paragraph actually used, not the split convention above. It is more
optimistic than convention 2 for AdamW-heavy shapes because it implicitly assumes AdamW's
`exp_avg_sq` is also bf16 — unmeasured, per the caveat.

| Rung | ff | VRAM (GiB) | vs 19.19 GiB floor |
|---|---|---|---|
| current | 8,192 | 4.014 | fits, 15.18 headroom |
| rung 1 | 16,384 | 6.826 | fits, 12.36 headroom |
| rung 2 | 32,768 | 12.451 | **fits, 6.74 GiB headroom** |
| target | 65,536 | 23.701 | **fails, -4.51 vs floor** |
| fallback (ff~49,152) | 49,152 | 18.076 | fits, 1.11 GiB headroom |

## Two hard findings (stated plainly)

1. **Rung 2 (2.228B) FITS the governed floor under both the corrected-split and uniform-6B
   conventions**, with real headroom (5.52–6.74 GiB) — a large improvement over the stale
   §3.3 table's 1.60 GiB margin, which assumed an 8 B/param Muon route the D6 receipt has now
   measured to be wrong (production is already 6 B/param, no code change required).
2. **The 4.242B target rung FAILS the governed floor under every convention tried** (deficits
   of 4.5–5.7 GiB) — nothing in this note changes §9 D2's own conditional fallback (a
   generalized non-doubling operator to ff~49,152 for the final rung).

## One cell too close to call

The ff~49,152 fallback point sits on opposite sides of the floor depending on convention: fits
with 1.11 GiB headroom under uniform-6B, fails by 0.11 GiB under the corrected-split convention.
The deciding factor is exactly the untested quantity above — AdamW's `exp_avg_sq` dtype (and
whether a separate fp32 master weight exists anywhere in the optimizer state). Resolving this
cell for real requires extending the D6 A/B to explicitly measure/force `exp_avg_sq`, not another
arithmetic pass over the existing receipt.

## Provenance

- `receipts/d6-bf16-momentum-ab-20260703T160041Z.json` — landed this PR; sha256 verified
  byte-identical to the copy committed at `wip-anchor-20260704` (commit 0803454).
- `src/ember/governance/scripts/ember_d6_bf16_momentum_ab.py` — landed this PR from `wip-anchor-20260704`
  (blob b82e0318913b058a6154b134e8f1124415a6933d, cross-verified against `git ls-tree`).
- `docs/domains/governance/spec/c-scale-s1-growth-chain-DRAFT.md` §3.1/§3.2/§3.3/§9/§10 — landed this PR from
  `goalforge/definitive-goal-20260701` (blob b56e42cec4e26796b6e33dc2a5b116fd50d20aac).
- All arithmetic above independently recomputed in Python against these sourced constants, not
  copied from any prose figure (the OLD and UNIFORM-6B tables were used as a cross-check that
  the recomputation reproduces the doc's own already-stated numbers exactly, which it does).
