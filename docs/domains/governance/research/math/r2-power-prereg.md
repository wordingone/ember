# Round-2 G1 power pre-registration (#29)

Every number below is from the executed run `receipts/r2-power-prereg-20260610T223032Z.json`
(`scripts/r2_power.py` on the EMPIRICAL per-task base rates of the G1 base
leg, `w1-floor-g1-base-20260610T215814Z-samples.jsonl`: 43 validation
tasks, base mean per-sample rate 0.657; 2,000 sims/cell, seed 16;
POWER_SELFTEST_PASS includes the new primitives).

## Sample-level paired design (the gains metric)

MDE (80% power, two-sided α=.05, homogeneous shift):

| k | MDE |
|---|---|
| 8 | 6.07pp |
| 16 | 4.27pp |
| 24 | **3.48pp** |
| 32 | 3.01pp |

Monte-Carlo power (normal-proxy test; null rejection calibrated at
4.9–5.3% across k):

| k | +3pp | +5pp | +8pp |
|---|---|---|---|
| 8 | .133 | .259 | .525 |
| 16 | .197 | .443 | .815 |
| 24 | .283 | .618 | .927 |
| 32 | .350 | .732 | .978 |

**Honest re-read of round 1:** MTP's +5.23pp was detected at k=8 where a
priori power for +5pp is only ~26% — a low-power detection, consistent
with its CI lower bound sitting at +0.58pp. Round-2 must not rely on that
luck repeating.

## Task-level feed (any-of-k)

McNemar power ≤ 0.10 at every (k, δ) cell and FALLS with k (at base mean
rate 0.657, any-of-k saturates: k=8 already feeds 39/43; larger k feeds
both arms everywhere and discordance vanishes). This receipts the
decision-tree's structural call: **task-feed is the HARM metric only;
it cannot detect gains on this world at this floor.**

## Binding choices for round-2 G1 (consumed by #36)

1. **k=24** on validation-43, seed 16, paired across all arms — MDE
   3.48pp, power 62% at +5pp / 93% at +8pp. Cost ≈3× the k=8 leg (~10–12
   min/arm) — affordable. k=32 is the authorized stretch if the GPU window
   allows (every arm same k; never mixed).
2. Gains read on the sample-level paired bootstrap exactly as in
   `g1_paired.py`; feed reported for harm only.
3. MDE caveat carried: homogeneous-shift + binomial-noise-only assumption
   makes these optimistic lower bounds (heterogeneous true effects widen
   the SE — round 1's per-task diffs already show heterogeneity).
4. Any "FLAT" verdict in round-2 receipts MUST quote the k=24 MDE (3.48pp)
   beside it.
