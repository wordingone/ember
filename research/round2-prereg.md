# Round-2 pre-registration — FROZEN 2026-06-11 (task #35; consumes #112/#110/#102/#105)

Binding before launch. Changes after launch = deviations, recorded per
the audit-§6 registry rule. Round-1 binding consequences carried in
full (t5 powered; MTP default; param caveat addressed; exact stats).

## 1. Sequence

1. **Sampling (accumulation step):** W-code train pool sampled WITH
   `adapters/r1w-q3-mtp` (the r1 gains-winner; sampling with the best
   artifact = the loop's accumulation semantics). k per task: 8 default;
   instrument = the existing w1 generation path with adapter +
   `--ext-verify` (strict comparator + reachability guard + extended
   tests in-path — eng-21/23/24 stack). New verified episodes →
   `w2_ingest` (appends ledger + eng-25 sidecar stamps; main files
   byte-append-only).
2. **Arms (training, via the #112 wrappers, interlocked):**
   - `base` — no adapter (eval-only arm).
   - `sft` — t2_r2_sft, frontier-weighted theta=0.5 (solve-rate single
     source = r2_arms; rate computed over ledger+control_pool).
   - `mtp` — t2_r2_mtp (r1 default-recipe winner).
   - `grpo` — t2_r2_grpo (verifier-reward).
   - `control` — matched-budget fails (t2_round --control,
     match_texts = the sft arm's effective text count; matched steps
     AND data; MTP aux-param caveat quantified in-receipt as in r1).
   - Cluster-cap arm is ROUND-3 (fp-17 prereg) — NOT here.
3. **Gates (all binding, receipts or the round is incomplete):**
   - **G1:** w4_eval on MBPP sanitized VALIDATION (43 heldout), paired
     bootstrap + EXACT methods (stats_exact #110; Newcombe BINDING for
     zero-inflated counts). Primary metric: per-sample verify delta,
     each arm − base and each trained arm − control (gains metric,
     unchanged from r1).
   - **t5 POWERED (r1 binding consequence):** FULL sanitized MBPP test
     split, per-problem paired analysis, MDE quoted on any FLAT.
   - **D-gate + P-gate** legs per `research/persistence-gates-spec.md`
     (eng-32 harness; P-gate boundary = daemon restart).
   - **Pacing:** every t2 receipt carries the fp-14 measured block;
     fp-20 (#116) settles on the sampling receipt; fp-21 (#120)
     executes the frozen band-transfer prong-A on it.
4. **Calibration (zero marginal GPU):** per-task P(verify) elicitation
   pre-sampling; Brier vs V in the receipt (#112 instrumentation).

## 2. Decision rules (frozen)

- An arm ADVANCES to round-3 default only if G1 delta vs base AND vs
  control both exclude 0 (exact CI), AND powered-t5 harm_flag is FALSE.
- All-FLAT round → the loop's first replication failure: round-3
  method comes from the receipts (band fp-21 verdict + cluster-cap
  arm), never improvisation; fp-15 prong-B does NOT fire unless
  prong-A was PREDICTIVE.
- No post-hoc metric additions; exploratory cuts go in a clearly
  marked non-binding receipt section.

## 3. Launch interlock

Wrappers refuse without `--leo-gate-token`. Token for this round:
**`r2-prereg-20260611-leo`** — valid ONLY after (a) this doc is merged,
(b) the sampling receipt is gated with ledger byte-append verified +
eng-25 view freshness (fresh --backfill), (c) governor preflight on
the dispatch. Token appears in receipts; any run carrying it without
(a)-(c) receipted is a gate violation.

## 4. GPU budget

Sampling ≈ governed hours (k=8 × pool at q3 pace with pacing);
arms ≈ r1-scale minutes each; evals ≈ w4/t5 windows. Fits the map's
round-2 day (06-12) with the v0 pretrain timeshare (eng-33) untouched.
