# c04 token budget v1 — fp-38 (#355): the budget half of the joint constraint (2026-06-12, ~3:25 PM LA)

Receipt: `receipts/c04-budget-20260612T222520Z.json` (`scripts/c04_budget.py`,
receipt-chained to the fp-37 grid — selftest anchors reproduce the #352
table). Recalibrates mechanically on eli's measured L9 flash F via
`--f-sustained` (fp-39 carries that).

> **RECALIBRATION CAVEAT (3:45 PM LA):** this table is anchored to the
> BENCH-PATH F (Llama+AdamW proxy). The production path measured ~2× slower
> on the dead run (fp37-l7-v2 reconciliation), and the no-ckpt knees are
> falsified (fp38-l9 OOM rows) — so every "afford/1d" is optimistic and
> every multiplier is UNDERSTATED until the production-path cell lands
> (fp-39, C-7). Direction survives: the gap scales all rows equally, so
> c03-shape remains the smallest-multiplier candidate by ~5.5× over the
> next row; in ckpt mode at bench-path F it affords ~2.9B/day → mult ≈1.9×.

## The derivation

The §3 criterion (budget ÷ tok/s_paced ≤ 24 governed hours) makes the budget
a DERIVED quantity per candidate: one governed day AFFORDS what the table
says, no more. The bulk default (Chinchilla-class ~20 tok/param, ESTIMATE —
no local receipt) DEMANDS 20·P. The ratio between them is the **required
curated-density multiplier** — how much more competence per token the owned
curriculum must deliver vs bulk for the 1-day pretrain to be
Chinchilla-equivalent:

| candidate | params | afford/1d | tok/param | Chinchilla | mult required |
|---|---|---|---|---|---|
| c03-shape h1024 d20 | 284M | 3.51B | 12.3 | 5.69B | **1.62×** |
| h2048 d12 | 670M | 1.49B | 2.2 | 13.4B | **8.98×** |
| h2048 d14 | 770M | 1.30B | 1.7 | 15.4B | 11.9× |
| h2304 d12 | 838M | 1.19B | 1.4 | 16.8B | 14.1× |
| h2560 d12 | 1.03B | 0.97B | 0.9 | 20.5B | 21.1× |

Data side never binds: even 3.51B/day = 0.5 epochs of the owned 6.98B stream
(`token-shards-v0-...T170047Z`), under the ~4-fresh-epoch ceiling (ESTIMATE,
data-constrained scaling).

## F-3. The joint constraint resolves toward small P — against the wider prior

The ARCH verdict's receipt-backed prior said wider-not-deeper (fp8 shapes,
arithmetic intensity). The budget side says the opposite: a 1.62× density
multiplier (c03-shape) is plausibly closable by a curated curriculum; 9–21×
(h2048+) is not a curriculum, it's a different scaling law. **Unless the L9
measured F or a density receipt says otherwise, the c04 pick is
small-P + flash + curated-dense tokens, not a wider core.** The two priors
collide exactly where receipts are thinnest — which is why both pending
receipts (L9 bench, density A/B) gate the pick.

## F-4. The multiplier is an obligation, not an optimization

The only local density datapoint is NEGATIVE: ~3B bulk-weighted tokens on a
c03-class run produced floor-marginal W-code rates (0–2/100; q15 round-1
0.0% all arms — H2 register). Bulk tokens at the affordable budget do NOT
reach the floor the rounds need. So even the 1.62× row is unproven until a
**density A/B** exists: two matched-FLOP small cells, curated-shard mix vs
bulk-shard mix, floor-metric delta as the receipt. That bench is the
cheapest decision-changing receipt on the board (CPU-light, <1h GPU), and it
prices H2/L8 directly.

## Consequences

1. **fp-39 (successor):** recompute this table at the measured L9 F when
   eli's flash receipt lands (`--f-sustained`); spec + gate the density A/B
   (curated vs bulk, matched FLOPs, floor metric, MDE-aware n per the
   power-helper receipts: n=100 ⇒ 10.2pp visible, n=400 ⇒ 3.85pp).
2. **Gate-9 linkage:** the (P, budget) pair entering any c04 pretrain must
   cite THIS table's row (or its fp-39 recalibration) + the density receipt
   class — a budget without a density obligation attached is the 12c050e7
   miss in new clothes.
3. **Round visibility (H2):** whatever budget is picked, round-1 eval n must
   make the expected delta visible (MDE table above) — a round whose
   best-case movement is under the gate's MDE is unfalsifiable by design.
