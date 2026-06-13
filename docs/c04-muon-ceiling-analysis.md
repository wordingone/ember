# c04 Muon §3 ceiling — pre-registered run6 decomposition gate

Est. 2026-06-13 ~13:30Z, BEFORE run6 (compiled_ns5, job dc51a19c) lands. Freezes
the throughput break-even from run5's measured components so run6's verdict is
mechanical, not reverse-justified (anti-goalpost, fp-39/42 class).

## run5 decomposition (receipt 20260613T130912Z)

tok_s_paced = 6922.1 → step = 16384 tok / 6922 = **2367 ms**. §3 needs
tok_s ≥ 25463 → step ≤ 16384/25463 = **643.4 ms**. So Muon must shed ~1724 ms.

| component | ms | note |
|---|---|---|
| NS (1024,1024) ×80 | 89 | min-dim, fine |
| NS (1024,4096) ×20 | 62 | fine |
| NS (32000,1024) ×2 (MTP) | 43 | transpose works — cheap, NOT the problem |
| NS (4096,1024) ×40 | **1529** | **89% of NS** — warmup was ~111ms → 13.7× |
| NS total | 1723 | |
| other_opt (mom+upd+adamw+py) | 430 | opt_wall 2153 − NS 1723 |
| non-opt (fwd+bwd) | 214 | step 2367 − opt_wall 2153 |

## Root cause (eli): allocator fragmentation, not compute

The (4096,1024) group is 40 params torch.stack'd into a 671 MB FP32 tensor each
step. Warmup ~111 ms, timed 1529 ms (13.7×): the caching allocator can't find
contiguous 671 MB blocks after a few steps → padding/fragmentation. The COMPUTE
is ~111 ms (warmup proves it); the 1418 ms excess is allocation.

## Best-case ceilings (what each lever can buy)

- **Defrag only** ((4096,1024) → its 111 ms warmup): NS = 89+62+43+111 = 305 ms
  → step = 305 + 430 + 214 = **949 ms → 17.3k tok/s. STILL SHORT.**
- **Defrag + other_opt compiled** (if the 430 ms is mostly Python overhead that
  torch.compile fuses, → ~100 ms): step = 305 + 100 + 214 = **619 ms → 26.5k
  tok/s. CLEARS §3 (marginal, ~4% over).**

The other_opt floor is load-bearing: with NS→0 but other_opt unchanged at 430 ms,
step = 644 ms → 25.4k — right at the boundary. So defrag ALONE cannot clear §3;
other_opt must also drop. Muon's §3 viability hinges on BOTH levers.

## PRE-REGISTERED run6 gate (frozen here, before the receipt)

run6 adds compiled_ns5 + the ns_ms/mom_ms/upd_ms/adamw_ms/other_muon_ms split.
Muon clears §3 **iff BOTH**:
- (a) (4096,1024) NS ≤ ~150 ms (compile/defrag killed the fragmentation), AND
- (b) other_opt components (mom+upd+adamw+other_muon) ≤ ~125 ms (compile fused
  the within-Muon Python overhead).

If either lands short → Muon tok_s < 25463 → `c04_optimizer_pick` =
ESCALATE_TORCH_OR_TRADEOFF. That is the genuine Jun tradeoff (NOT premature —
defrag + optimizer-step-compile are the exhausted means; torch≥2.7 is the only
remaining Muon-preserving lever, compiling the whole step incl optimizer at once):
**Muon + torch≥2.7 env-risk** vs **AdamW free at 0.919 governed days** (fp44
quality edge thin/jude-flagged at delta_T −0.746 vs 0.605 floor). Only the user
moves the env-risk envelope or the ≤1-day bar.

Verdict is read off run6's receipt via the existing pick — this doc only freezes
the break-even so the number can't be reinterpreted after the fact.
