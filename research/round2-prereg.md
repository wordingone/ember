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
   tests in-path — eng-21/23/24 stack). Pinned dispatch (pre-launch):
   `w1_mbpp.py --model Qwen/Qwen2.5-Coder-3B-Instruct --adapter
   adapters/r1w-q3-mtp --split train --k 8 --ext-verify --calibrate
   --seed 18 --tag q3-r2mtp` (seed 18 = fresh, r1 used 14/15;
   --calibrate = the §4 elicitation). New verified episodes →
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

## 5. Deviation registry (post-launch, per audit-§6)

- **2026-06-11 (pre-arms, post-sampling): sft/control data path.** The
  §1.2 line "sft — t2_r2_sft" named the #112 wrapper; at the launch
  gate that wrapper's delegation was found to build from the FULL mixed
  ledger with flat caps (its theta filter computed but never consumed —
  not the registered arm). Corrected runner `scripts/t2_r2w.py` trains
  the registered semantics: W-code view (regenerated from current
  ledger) → ext-clean → theta (0, 0.5] via r2_arms single-source rates
  → flat MAX_PER_TASK cap → train_lora; control mirrors the sft
  per-task counts from the W control pool. Arm SEMANTICS unchanged from
  §1.2; only the executing script differs. mtp/grpo dispatch via the
  #112 wrappers as written (data paths verified correct in source).
  Evidence: t2-r2w-sft dry-run + live receipts; audit §8.29.
- **2026-06-11: fp-20 settlement surface.** §1.3 said fp-20 settles on
  the sampling receipt; that receipt carries no pacing block (w1 write
  not wired — eng-37/#129). fp-20 re-pinned to the first instrumented
  w1 receipt; the t2-class receipts carry the block as specified.
- **2026-06-11 (pre-rerun, GRPO pool clarification — pinned BEFORE the
  certified GRPO rerun):** the #112 GRPO wrapper declared a theta
  (0, 0.5] frontier filter but t2_grpo's prompt pool ignored it
  (informational-only — kai 14511; load-bearing fix = eng-39/#142).
  CALL: the certified round-2 GRPO arm uses the wrapper's declared
  theta (0, 0.5] LIVE-frontier set strictly — NO dead (rate-0) tasks —
  because that is the closest executable reading of the frozen
  declaration, and expanding the pool after seeing round-2 sampling
  data is the goalpost-move the freeze bans. The r1 precedent
  ("dead ×4 — RL can crack what SFT can't imitate") is recorded as the
  counterargument; dead-task GRPO = a NAMED round-3 arm candidate, not
  a silent round-2 expansion.
- **2026-06-11 (arm certification status):** sft + control receipts
  certified once the w2-ingest-proof companion receipt landed
  (byte-append proven in-receipt). mtp + grpo first runs =
  PRE-GATE/QUARANTINED (receipt-integrity: wrapper claims not tied to
  executed data path — kai 14508/14511); certified reruns dispatch
  after eng-38 (#140) / eng-39 (#142) merge. G1 (w4_r2_g1) HOLDS until
  the certified arm set is complete.
