# c04 candidate grid v1 — fp-37 (#352) arithmetic (2026-06-12, ~3:10 PM LA)

> **FALSIFICATION NOTE (3:45 PM LA, receipt fp38-l9-flash-ab-20260612T223639Z):**
> the no-ckpt+flash knee rows below are DEAD at c03 widths — flash cells
> OOM'd at B=39/33/26. The activation model undercounts (modeled ~20 B/unit
> vs ≥~28 measured); F-1's 40,631 tok/s projection is falsified. What
> stands: FLOP/token and tokens/day arithmetic (ckpt rows), and F-2's joint
> (P × budget) constraint — which only tightens. L9 completion cells
> (b16/b8-nockpt-flash, never measured) decide revive-at-reduced-batch vs
> KILL-at-all-batches. SECOND correction (fp37-l7-v2 reconciliation): the
> F anchor is BENCH-PATH (Llama+AdamW proxy); production path (MTP+chunked
> CE+Muon) measured ~2× slower on the dead run — all tokens/day columns are
> optimistic until the production-path cell lands (fp-39 recalibrates).

Receipt: `receipts/c04-grid-20260612T220829Z.json` (`scripts/c04_grid.py`,
selftest anchors reproduce c03: P=284.4M, 2.21G FLOP/tok, 69.3 TFLOPS
sustained from the compiled-cell receipt, and the b16-nockpt OOM boundary).
Projections are paced-sustained-FLOPS-anchored; the design bench (#353)
converts them to receipts.

## The two findings that matter

**F-1. The missed lever is attention memory (new lever L9, flash/SDPA).**
The selftest proves c03's no-ckpt OOM is the S² attention-scores term
(~10.7 GB at B=16) — c03 materializes attention; flash eliminates that
term. With flash, c03's OWN SHAPE runs no-ckpt at B≈39: projected
**40,631 tok/s = 2.27× the live-run anchor** — bigger than every lever
landed tonight COMBINED, on the existing architecture, from one kernel
swap. L9 bench cell (<1h) is the next GPU action; it recalibrates the
whole grid before any c04 pick.

**F-2. The ≤1-governed-day criterion binds (params × token-budget)
JOINTLY — no kernel stack escapes it.** tokens/day = 86,400 × F/flop_tok
at the receipted F=69.3 TFLOPS:

| candidate | params | mode (flash) | B_knee | proj tok/s | tokens/day | 7B budget |
|---|---|---|---|---|---|---|
| c03-shape h1024 d20 | 284M | no-ckpt | 39 | 40,631 | 3.51B | 1.99 d |
| h2048 d12 | 670M | no-ckpt | 26 | 17,261 | 1.49B | 4.69 d |
| h2048 d14 | 770M | no-ckpt | 21 | 15,005 | 1.30B | 5.40 d |
| h2304 d12 | 838M | no-ckpt | 21 | 13,788 | 1.19B | 5.88 d |
| h2560 d12 | 1.03B | no-ckpt | 16 | 11,268 | 0.97B | 7.19 d |

(Full grid incl. ckpt rows in the receipt; no-ckpt+flash dominates
everywhere it fits.) Even the SMALLEST shape affords only 3.5B tokens in
a governed day — the 7B bulk-token budget fits NOTHING at ≤1 day. The
shatter criterion is therefore reachable only by closing BOTH sides:
kernels (L9 + landed levers) AND token budget (verified-dense curriculum —
H2/L8 stops being a round-design nicety and becomes the load-bearing half
of the compute solution). Concretely: h2048 d12 × ≤1.5B curated tokens =
one governed day; c03-class × ≤3.5B = one day.

## Consequences

1. **L9 flash bench first** — eli, one cell on c03 shape (no-ckpt, B≈39,
   compiled). If it lands near projection, every number above firms and
   the c04 pick follows the measured F.
2. **fp-38 (successor, minted at close):** derive c04-v0's REQUIRED token
   budget from curriculum density — verified bits/token of the owned
   corpus vs bulk web tokens; the budget the gain gate actually needs,
   not the Chinchilla-bulk default. The (P, budget) pair that passes §3
   of c04-design-constraints-v1 is chosen from THIS doc's table × fp-38's
   budget — both receipted.
3. ARCH verdict nuance recorded honestly: flash was an ENG lever hiding
   in the ARCH residual — the verdict's redesign direction stands (wider
   cores still dominate fp8/intensity), but the c03-shape row stays a
   live candidate until the L9 receipt prices it.
