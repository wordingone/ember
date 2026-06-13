# fp-42 — Two-wall §3 feasibility envelope for the c04 pick

**Question:** the c04 design benches (#353, `c04-receipt3`) show the §3 gate (clear 2.2B
tokens in ≤1 governed day → ≥ **25,463 tok/s**) FAIL on all 5 candidates at eager.
eli's receipt named two walls but did not compute whether breaking them clears §3.
Does it — and which levers are required?

## The model

Wall time per step splits into model (forward/backward) and optimizer (Muon
Newton-Schulz). With `opt_share = T_opt / T`, compile speeds only the model fraction
by `s_c`, fused-muon (#329) speeds only the optimizer fraction by `s_m`:

```
tok_s' = tok_s / ( (1 - opt_share)/s_c + opt_share/s_m )
```

## c03 (the only clean reference — see contamination below)

`tok_s = 16834`, `opt_share = 0.4137`, target `25463`:

| levers | result | clears §3? |
|---|---|---|
| compile alone (s_m=1) | needs **s_c ≥ 2.37×** | implausible (train compile ~1.3–1.7×) |
| compile 1.5× + fused 1.5× | 25251 tok/s | **NO** — 0.8% short |
| compile 1.5× + fused **1.53×** | 25463 | yes (threshold) |
| compile 1.6× + fused 1.6× | 26934 | yes |

**Compile alone cannot clear §3** — Muon NS is 41% of wall and uncompiled, so even
infinite model speedup leaves a 41% optimizer floor. §3 clears only with **both**
levers, each slightly above 1.5×. The margin is **thin**: the textbook 1.5/1.5
operating point misses by 0.8%.

## Consequences

1. **#329 (fused-muon) is load-bearing on the critical path**, not a side
   optimization. The c04 → pretrain path requires both #373 (compile) and #329
   (fused-muon) to land.
2. **Re-bench c03 SOLO, compiled + fused.** The measured tok/s is the binding
   verdict (the `s_c`/`s_m` independence-and-multiplicativity model is an estimate
   for setting targets, not a guarantee).
3. **The 4 larger candidates are contaminated** — `h2048/h2304/h2560` benches were
   dispatched 4-way parallel on the shared GPU, so their tok/s (252–313) are lower
   bounds only and cannot be compared. They need clean solo re-benches before the
   c04 pick can rank candidates.
4. **Escalation trigger (precise):** only if a real compiled+fused solo re-bench is
   *still* < 25,463 tok/s does the ≤1-day bar become the user's call (wall-day
   fraction). A budget cut is not ours to make — only the user reduces scope.

## Successor — fp-43

Gate the compiled+fused solo re-bench verdict: when #373 + #329 land and eli
re-benches c03 (and the 4 clean), verify measured tok/s vs 25,463 → c04 pick or
user-escalation. Trigger: the re-bench receipt.
