# c04 gate-time playbook — what happens the moment fp44 lands

Est. 2026-06-13 ~10:40Z. The means-side chain (config + optimizer pick + launch
gate) is frozen, coherent, and order-safe. This doc is the **deterministic
action map** for when fp44 (job 57706bdc) emits its horizon-equiv receipt — so
gate-time is execution, not improvisation. The composition below is proven
end-to-end (not asserted): a synthetic eli-shaped fp44 receipt run through the
REAL `fp44_horizon_equiv_gate.score_receipt()` → `c04_optimizer_pick.pick()`.

## The one command

When both the fp44 receipt AND the batched-NS5 bench receipt are on disk:

    python scripts/c04_optimizer_pick.py

`analyze()` loads both receipts, runs the fp44 gate internally (P2), and emits
the frozen 3-way verdict. Nothing else to wire.

## The deciding lever is batched-NS5, NOT the fp44 verdict

The live fp44 trajectory hints at Muon ahead (muon_split_baseline seed16
@2000 = 6.2305; full_fused_adamw seed16 tracking ~7.3–7.4). IF that holds the
fp44 gate returns **ESCALATE_USER_TRADEOFF** (Muon meaningfully lower than the
0.605 noise floor) or **HOLD_INCONCLUSIVE** (adamw non-monotone / diverging) —
NOT a clean COMMIT_ADAMW. But that does **not** route to the user yet:

- The pick **P1** (`COMMIT_MUON_BATCHED`) fires iff the batched-NS5 production
  bench clears §3 (≥25463 tok/s) with the kernel proven exact (ns5_equiv
  ≤2e-7). batched-NS5-Muon is the SAME optimizer as fp44's Muon arm — so if it
  clears, we keep Muon quality AT ≤1-day throughput and **fp44 is moot**
  (`fp44_moot=True`). The escalation never reaches the user.
- The pick is **order-safe** (#395): while batched-NS5 is absent-but-expected
  it HOLDS at PENDING — it will NOT prematurely consult fp44 and escalate.

So the true critical path after fp44 lands is **eli dispatching the batched-NS5
bench** (PR #390 harness), not the fp44 verdict. eli has this queued.

## UPDATE 2026-06-13 ~13:08Z — run4 landed: batched-NS5 RAN and fell SHORT

The deciding lever resolved on real data; the picture moved.

- **Footprint wall broken** (eli `empty_cache` after warmup; hyp-A confirmed —
  reserved caching-allocator held step-1 NS5 transients, never a leak). batch=16
  now runs complete timed steps.
- **batched-NS5-Muon = 7212 tok/s — 3.5× SHORT of §3** (25463); ns5_equiv
  2.8e-7 > 2e-7 on (4096,1024). The torch.stack batching is 5.8× SLOWER than the
  sequential fp40 baseline (NS phase 1648ms vs 285ms) — batching backfired
  (bandwidth-bound, GiB intermediates). `c04_optimizer_pick` →
  ESCALATE_TORCH_OR_TRADEOFF (batched-NS5 ran-and-short, P2 consults fp44).
- **The escalation is HELD (break-the-wall) — one lever untried before Jun:**
  the optimizer step runs EAGER/uncompiled (PROBE 2: plain Python `step()`
  outside the compiled `fwd_fn` region). It has NO backward, so the 08:10Z
  compile falsification (`Tensor.backward()` Unsupported on torch 2.6) does NOT
  apply — `torch.compile` on the optimizer step may compile cleanly on torch 2.6
  and deliver the 3-4× the NS phase needs WITHOUT the torch≥2.7 env bump. NS5
  already transposes to min-dim (PROBE 3) — that lever is spent.

Pre-escalation order now:
1. eli compiles the optimizer step (+ per-shape-group bmm, not all-stack).
2. compiled+per-group step clears §3 → COMMIT_MUON_BATCHED, Muon kept, NO Jun
   escalation. gate-9 muon_batched authorization verified open (PR #405).
3. ONLY if it still can't clear §3 → torch≥2.7 is the genuine Jun tradeoff below
   (env-risk for Muon's thin/jude-flagged quality edge vs AdamW free at 0.919d).
   The measured Muon number is now 7212-class, not 19223 — refresh the ESCALATE
   numbers from eli's compiled-step receipt before presenting to Jun.

## Verdict → action (verified composition)

| fp44 verdict | batched-NS5 state | pick output | action |
|---|---|---|---|
| any | absent, still expected | `PENDING` | wait for batched-NS5 (eli dispatches) |
| any | **clears §3 + exact** | `COMMIT_MUON_BATCHED` (fp44 moot) | gate-9 `--optimizer muon_batched` → pretrain (Muon kept, ≤1 day) |
| `COMMIT_ADAMW` | ran-short / ruled-out | `COMMIT_ADAMW` | gate-9 `--optimizer full_fused_adamw` → pretrain |
| `ESCALATE_USER_TRADEOFF` | ran-short / ruled-out | `ESCALATE_TORCH_OR_TRADEOFF` | present to user (below) |
| `HOLD_INCONCLUSIVE` | ran-short / ruled-out | `HOLD` | longer horizon / re-seed before any commit |

## IF it reaches the user (ESCALATE) — the framing, numbers pre-filled

Only reached if batched-NS5 is ruled-out OR ran short. The tradeoff (only the
user moves the ≤1-day bar or the optimizer quality, §4.5 residual):

- **Keep Muon** (the C-3 design optimizer, measured lower loss at 2000 steps):
  `MUON_TOK_S=19223.3` → **1.325 governed days** for the 2.2B budget. Over the
  ≤1-day bar.
- **Take AdamW** (clears §3 free, quality gap = the measured delta): 
  `ADAMW_TOK_S=27702.8` → **0.919 days**. Under the bar.
- **torch≥2.7 compile lever** (restores the falsified compile path to keep Muon
  AND clear §3): shared-env major bump, user risk-envelope flag — last resort.

Leo presents the **measured delta** (muon−adamw @2000) and the noise floor;
AdamW is NOT auto-picked to dodge the escalation. The gate-9 coupling (#396)
mechanically refuses to authorize a launch on an optimizer the pick has not
committed — so an ESCALATE cannot silently become a launch; only an explicit
`--force-optimizer-authorized` (user) overrides.

## Gate-time receipt discipline

Verdict comes from running the scorer on eli's receipt — never from the live
training log (separation of concerns). `noise_floor_source` in the fp44 gate
output must read `derived` (it read eli's Phase-1 floor); a `default` there is
the red flag that the floor key didn't match (#398) — STOP and reconcile the
schema before trusting the verdict.
