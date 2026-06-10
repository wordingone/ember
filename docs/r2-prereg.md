# W-code round-2 pre-registration (#36)

Committed BEFORE any round-2 train/sample dispatch (binding). Consumes, by
receipt: G1 paired verdict `g1-paired-r1w-20260610T222435Z` (cell
R2-RETHINK on plain-SFT, D3 overlay UP — MTP advances), t5
`t5-r1w-q3-mtp-20260610T222615Z` (harm_flag false, Δ CI [−18,0], power
caveat), `r2-power-prereg-20260610T223032Z` (k=24 binding, MDE 3.48pp,
feed=harm-only), `bits-account-20260610T223429Z` (B = 196.73
[195.9,197.45] corrected), `calibration-decomp-20260610T223737Z`
(resolution 0.0; skill criterion), `research/world-choice-r2.md` (W-code
stays the r2 training world). Note: #24 (GRPO integration) completes
ROUND-1's arm B whenever it lands; GRPO joins round-2 only through the
arm-4 precondition below.

## Phase S — sampling (fires first)

1. `w1_mbpp --split train --k 8 --seed 17 --calibrate --ext-verify` over
   the full 120-task pool (round-2 seed bumps: sampling seed 17; eval seed
   stays 16 for cross-round comparability of the G1 surface).
2. Adaptive top-up: `--focus-from <s1> --focus-max-rate 0.75 --k 24
   --seed 18 --ext-verify` (same shape as the receipted round-1 top-up).
3. Calibration rides at full pool (n=120; detects |skill| ≥ 0.085 per
   #31). vbits stays on preference-2 unless the new receipt clears the
   criterion (skill bootstrap CI > 0 AND resolution > 0.01).
4. Ingest via w2 with frontier annotations; dataset builds are ext-clean
   (eng #21); the three-estimator bits receipt (`bits_account.py`) runs at
   ingest. NO bits threshold gates training this round — 196.73 corrected
   bits already produced a control-beating gain; the round-2 number is
   reported, not gated on.

## Phase T — arms (all from BASE on the full ext-clean ledger; replay-by-
retraining per the KEEP-BURNING annex; governed; one model at a time)

1. **MTP arm** (the advancing recipe): t2_mtp on round-1+round-2 episodes.
2. **Control-MTP** (the G1 caveat fix): IDENTICAL architecture — aux heads,
   λ, K — trained on matched control-pool fails with matched effective
   texts. Round-1's control matched steps/data but not the aux-head
   params; round-2's control matches params, steps, data size, AND
   objective, isolating verified-content as the only delta.
3. **Plain-SFT** (continuity baseline, cheap): t2_wcode.
4. **GRPO** — joins IFF #24 produced a trainable arm before Phase T
   dispatch; otherwise it continues as integration work and round-2 runs
   3-armed (starvation-guard pattern: the chain never waits on one arm).

## Phase E — eval (pre-registered, in order)

1. **G1**: validation 43 × **k=24** (binding, #29), seed 16, all arms +
   base, `g1_paired.py`. Gains metric = sample-level paired bootstrap;
   feed = harm-only; any FLAT quotes MDE 3.48pp.
2. **t5 powered up** (the round-1 caveat): FULL MBPP sanitized test split
   (every problem, not 50), k=4 seed 14, per-problem paired analysis
   (g1_paired-style discordants + bootstrap), MDE quoted. Binding
   non-regression: an arm whose t5 delta CI sits below 0 is dead
   regardless of G1.
3. **HumanEval+ admission probe** (#46) in the trailing GPU window —
   round-3 surface prep, not a round-2 verdict input.

## Verdict cells (fixed now)

- **REPRODUCE**: MTP-r2 beats base AND control-MTP on the k=24 gains
  metric (CIs exclude 0) → MTP is ember's confirmed round objective;
  round-3 scales accumulation and starts the smaller-core fp-1 probe.
- **PARAM-ARTIFACT**: MTP-r2 ≈ control-MTP (both possibly > base) → the
  round-1 gain was aux-head capacity, not verified content → fp-3/fp-1
  escalate (objective/core rethink), accumulation pauses for design.
- **NO-REPRODUCE**: MTP-r2 FLAT vs base at k=24 (MDE 3.48pp quoted) →
  round-1's +5.23pp was the ~26%-power fluke #29 warned about → R2-RETHINK
  resumes in full: bank rounds before training + fp-1 smaller-core probe.
- **HARM**: any t5 CI < 0 → arm dead; if ALL candidate arms die on t5,
  round-3 is anti-forgetting design (KL/replay-mix arms), nothing ships.
- Mixed cells resolve by precedence: HARM > PARAM-ARTIFACT > REPRODUCE >
  NO-REPRODUCE; the round-2 gate entry MUST name the fired cell.

## Invariants carried

Split discipline (train=pool, validation=G1, test=t5 only); seeds fixed
above; governor on every launch; receipts committed same-session as their
gate; deviations recorded per the audit-§6 registry rule.
