# fp-44 — Horizon optimizer-equivalence gate (the c04 optimizer commit)

**Pre-registered before eli's horizon-equiv receipt exists** (anti-goalpost-moving,
the fp-39/fp-42 discipline). Scorer: `scripts/fp44_horizon_equiv_gate.py`
(`FP44_HORIZON_EQUIV_GATE_SELFTEST_PASS`, 7 cases).

## Why this gate exists

eng-363 broke the §3 throughput wall on the optimizer axis: c03 + `full_fused_adamw`
= **27,703 tok/s** (clears 25,463). The fused-Muon kernel (#329 / fp35) is *viable*
but only **+8.1%** — far short of the **~3.2×** the NS phase (285.83 ms → ≤89 ms)
would need to keep Muon under the ≤1-day bar. Fusion cannot 3× cuBLAS matmuls, so
Muon cannot clear §3. The §3-clearing optimizer is **AdamW, which drops Muon** (the
C-3 design optimizer).

eli's eng-363 `equiv_pass` is **100-step** (losses → 0 by step 25) — structurally
blind to a cross-optimizer swap, the same pseudo-replication class fp-40 flagged for
the bimodal density probe. So "equiv PASS@100" does **not** certify AdamW ≡ Muon at a
pretrain-relevant horizon. fp-44 is the **2000-step real-data** equiv that does.

## The frozen decision rule

`delta = val_loss(muon) − val_loss(adamw)` in nats (delta < 0 ⇒ Muon lower ⇒ better).
At terminal step T = 2000:

| condition | verdict | consequence |
|---|---|---|
| AdamW val_loss diverging (monotone↑ last 3) | HOLD_INCONCLUSIVE | longer horizon / re-seed |
| sign(delta) crosses ±noise in last 3 | HOLD_INCONCLUSIVE | noisy crossover, not a coin-flip |
| `|delta@T| ≤ noise_floor` | **COMMIT_ADAMW** | equiv → AdamW (clears §3 ≤1 day; Muon doesn't) |
| `delta@T > +noise_floor` (AdamW lower) | **COMMIT_ADAMW** | AdamW faster AND better — strict win |
| `delta@T < −noise_floor` (Muon lower) | **ESCALATE_USER_TRADEOFF** | Muon 1.32 d vs AdamW ≤1 d — user's call (§4.5) |

`noise_floor = max(harness-derived threshold, paired-seed val_loss std@T, 0.05 nats)`
— a derived floor can only *widen* the boundary, never shrink it. The escalation is
**never auto-resolved to AdamW**: if Muon is meaningfully better, Leo presents the
measured delta and the user owns the ≤1-day relaxation.

## Expected receipt schema (so eli's `eng/329c` harness matches; loader is tolerant)

```
ticket: "FP44-HORIZON-OPTIMIZER-EQUIV"   (or any ticket containing horizon+equiv)
arms: {
  "muon_split_baseline": { "val_loss": {"250":.., "500":.., "1000":.., "1500":.., "2000":..},
                            "seed_val_loss_at_T": [.., ..] },
  "full_fused_adamw":    { "val_loss": {...}, "seed_val_loss_at_T": [.., ..] }
}
noise_floor_nats | derived_threshold_nats: optional harness-derived floor
```

Key spellings are matched flexibly (`muon`/`muon_split_baseline`/`muon_ns5`;
`adamw`/`full_fused_adamw`; `val_loss`/`losses_at`/`val_loss_at`). If the landed
schema diverges, the loader adapts; the **decision logic is frozen here**.

## Path after the verdict

- **COMMIT_ADAMW** → c04 pick = c03-class + AdamW → gate-9 (#349, user sees the
  ≤1-day wall fraction) → pretrain dispatch.
- **ESCALATE_USER_TRADEOFF** → present Muon-quality vs the ≤1-day bar (Muon 1.32 d).
- **HOLD_INCONCLUSIVE** → longer-horizon / re-seed equiv before any commit.
