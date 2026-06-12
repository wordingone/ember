# Density A/B spec v1 — fp-39 half 2 (#359): curated vs bulk, matched FLOPs (2026-06-12, ~3:30 PM LA)

The cheapest decision-changing receipt on the board (c04-token-budget-v1
F-4): the c04 pick needs a measured curated-density multiplier — required
1.62× at c03-shape, 9–21× at wider candidates. This A/B prices it. Leo
spec, eli executes; rides BEHIND the L9 flash cell (which sets cell wall
budget).

## Design (single variable = data mix)

- **Arms:** A = curated mix (verified-dense: W-code worlds + curated
  shards), B = bulk mix. Same c03 shape, same step count, same token
  budget, same governor (0.80/1.5GiB/pacing), same lever config (compiled,
  flash if L9 landed, B at knee), same lr schedule. 2 seeds per arm
  (4 cells, each <1h — the 1h rule is per-run).
- **Mix manifests are the prereg:** before ANY dispatch, two manifest files
  (shard ids + sampling weights, sha-pinned over raw bytes) committed +
  frozen. No mix edits after the first cell starts — the freeze IS the
  single-variable guarantee. Defining the curated/bulk split from
  TOKEN-SHARDS-V0 metadata is a named precondition (eli proposes from shard
  provenance fields; Leo gates the split before freeze).
- **Token budget per cell:** largest count fitting <1h at the L9-measured
  tok/s, minimum 80M; exact number fixed in the manifest (receipt-derived,
  not chosen after results).
- **Probes at 50% and 100% of budget** — a slope, not a point: an early-
  training density edge that is flattening by 100% cannot be extrapolated
  to the full pretrain; flat-vs-rising slope is recorded in the verdict.

## Metrics (all receipted, MDE-aware)

1. **Floor metric (primary):** fp-23/24 floor protocol on the W-code
   battery, n=400 per the power-helper receipts (3.85pp MDE at p0=2%;
   n=100's 10.2pp would make the likely deltas invisible — H2).
2. **Cross-eval loss (secondary):** each arm evaluated on BOTH held-out
   sets (curated-held-out, bulk-held-out) — separates domain-fit from
   competence; curated arm winning only its own held-out = overfit signal,
   not density.
3. **Multiplier estimate:** tokens-to-equal-floor ratio — at what fraction
   of arm-B's budget does arm-A match arm-B's final floor rate (from the
   50%/100% probes, interpolated; stated with its receipt-derived
   uncertainty, never bare).

## Verdict rules (frozen now, before data)

- mult_est ≥ 1.62 (both seeds directionally agree) → c03-shape × curated
  budget is LIVE for §3 of c04-design-constraints.
- mult_est < required for ALL wider rows (9–21×) → wider candidates DEAD on
  the budget side regardless of L9 F — recorded as the F-3 collision
  resolving toward small P.
- Floor delta under the n=400 MDE in both seeds → result is a POWER
  statement ("density edge ≤3.85pp at this budget"), not a null — and the
  c04 pick falls back to the c03-shape row on kernel receipts alone.
- Seed disagreement on direction → no verdict; third seed before any claim.

## Receipt

`receipts/density-ab-<ts>.json`: ticket FP-39, both manifests' shas, 4 cell
configs + seeds, floor counts (raw, not rates), cross-eval losses, probe
slopes, mult_est + method. jude adversarial pass before the verdict enters
any c04 decision doc.
