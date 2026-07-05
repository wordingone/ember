# Rung-2 grow spec v1 — FROZEN

Decision source: `docs/dossier/rung2-growth-ladder-dossier-v1.md` (#76, gated 2026-07-04:
params arithmetic independently re-derived; S9 pre-registration and corpus citations
spot-verified). Pre-registration remains binding: `docs/spec/c-scale-s1-growth-chain-DRAFT.md`
§9 (D1–D6). This spec adds the rung-2 execution decision on top of both.

## The rung

- Operator: net2net FF-widening, strict doubling — identical operator to the rung-1 precedent
  (gate/up/down_proj, all 20 layers), ff 16384 → 32768.
- params_unique: 1,188,865,024 → ~2,195,376,000 (delta = 20 × 3 × 1024 × 16384; the D4 ruling
  stands — unique counts authoritative, state-dict sums double-count the tied embed/head).
- Function preservation: same gate as rung-1 (fp_diff ≤ 1e-4 on the pinned probe batch;
  rung-1 measured 2.38e-6).
- Stabilization: D1 fixed-FLOPs floor → 30 steps / 491,520 tokens, drawn from the VERIFIED
  26-shard corpus (#77: 6,977,868,758 tokens, 26/26 shas re-verified, loader-compatible,
  contamination-checked vs both receipted eval batches). The #77 gating found the old
  mixture default was ABSENT on this machine (broken fallback, now repointed) — fresh-corpus
  stabilization also supersedes the 13th-epoch-mixture concern. Contamination re-check vs
  the real W1 capability batch is required once #53's control run produces one (open item
  carried in the corpus-verification receipt).

## Preconditions (ALL, before any dispatch)

1. **W1 control terminal outcome** (L1/L2/L3) — sequencing per dossier Q6: growing before the
   in-flight rung-1-pinned W1 run terminates would manufacture avoidable evidence-invalidation
   ambiguity. Not a compute dependency; a claims-hygiene dependency.
2. **Measured activation point**: the S3 `--working-set` receipt at rung-1 (window Block D
   8b). The dossier's two activation extrapolations disagree ~2× and one pushes even rung-2
   over the governed floor — VRAM fit is RECOMPUTED with the measured point before launch.
   If the measured extrapolation exceeds the governed floor at rung-2 shape, the
   checkpointing/accumulation decision returns to the maintainer; never silent fix-forward.
3. Optimizer-state pricing per the D6 bf16-momentum receipt (6B/param confirmed in
   production) — already receipted, cited here so the launch arithmetic has one source.

## Explicitly NOT decided here

- Rung-3 shape (direct ff 32768→49152 → 3.202B vs minimal overshoot). Decided AFTER rung-2
  lands and the working set is measured at 2.2B scale. The dossier's finding that the frozen
  spec's own ff≈45,337 figure lands BELOW 3e9 under the unique convention is accepted — any
  future minimal-overshoot target uses ff=45,863 (3.0002B unique).
- The 4.21B doubling target: fails VRAM before activations are counted (dossier Q4). Not
  authorized under today's evidence.

## Execution shape

The rung-1 grow+stabilize runner generalizes at config level. When preconditions clear
(expected: this window closes W1 + working-set), a builder gets the config delta + this spec;
receipts land under the cbase-grow-rung family with the same fields as rung-1 (growth maps,
params_unique before/after, fp_diff, stabilization eval trajectory).
