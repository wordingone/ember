# fp-32 — GPU bottleneck ledger (#225)

Relayed directive (mail 14633): diagnose every GPU bottleneck end-to-end,
challenge the math from first principles, and prove at least one measurable
gain with receipts — without disturbing the G-shards → launch critical path.

**Provenance rule (binding for this document):** every number is tagged
`[R]` receipt (named file), `[L]` daemon log (job id), or `[H]` hypothesis.
Nothing untagged is load-bearing. The receipt-side numbers are re-derived
mechanically by `scripts/fp32_baseline_miner.py` (emits
`receipts/fp32-baselines-*.json`); the intervention numbers come from
`scripts/fp32_step_econ_bench.py` (emits `receipts/fp32-step-econ-*.json`).

Limit taxonomy used below — a row must name exactly which limit binds:
**FLOP** (arithmetic throughput), **BW** (memory bandwidth), **IO** (disk),
**SCHED** (kernel-launch / occupancy / fixed per-step costs), **PACE**
(governor duty-cycle pacing), **SIG** (verifier-signal supply), **STAT**
(statistical power of the verdict instrument). "GPU slow" is not a limit.

---

## 1. Rows — critical path (binds before/at v0 launch)

### R1 — pretrain step economics: frozen batch=4 is a bench artifact, not a choice
- **Limit class:** SCHED + PACE (not FLOP).
- **Invariant:** `wall_days = T / (B·S / (t_c(B) + p)) / 86400` with
  T = corpus tokens, B = batch, S = 1024 seq, p = 0.05 s/step governor pace,
  t_c(B) sublinear in B until compute saturation. At small B the GPU is
  launch/occupancy-starved AND p is amortized over few tokens.
- **Baseline:** c03-qat paced 18,737.7 tok/s, raw 24,294.7, at B=4
  `[R fp19-bench-20260611T024648Z.json]` → v0 wall = 4.308 days at the live
  frozen total 6,973,632,296 `[R tokenizer-freeze-20260611T060423Z.json]`.
  17.19 GiB VRAM left free post-warmup at B=4 `[R same]`.
- **Provenance of the frozen value:** `configs/v0-pretrain-config.json`
  `throughput.batch: 4` cites fp19-bench as basis; fp19_bench's
  `BENCH_CONFIGS["c03"]["batch"] = 4` is the harness default. No receipt
  anywhere selects 4 by sweep — the config froze the bench harness's
  measurement setting as if it were a design choice. `[R config + file]`
- **Intervention (E1, fp32_step_econ_bench):** batch sweep {4,8,16,24,32}
  × grad-ckpt {on,off} × {eager,compile} under the UNCHANGED governor
  (fraction 0.80, margin 1.5 GiB, pace 0.05 — amortized, never loosened),
  anchored by a same-day reproduction of the fp19 cell that voids the
  comparison on >10% drift.
- **Measured (run 2, receipted):** anchor B=4 reproduced 17,899 paced
  (−4.48% drift, anchor_ok); B=8 23,088; B=16 23,474 (free 10.83 GiB);
  **B=24 24,078.9 (1.345× vs reproduced anchor; tax 4.9%; free
  5.15 GiB)**; B=32-ckpt and B=16/32-nockpt SKIPPED-OOM under the 0.80
  fraction cap `[R fp32-step-econ-20260611T142831Z.json]`. Raw plateaus
  ≈ 25–27k tok/s at B≥8 — eager compute ceiling reached; beyond B=8 the
  gains are pacing amortization (R2). (Run 1, job 93e74934, measured the
  same shape but lost its receipt to an uncontained compile-cell error —
  the harness now contains any cell failure.)
- **Result:** v0 wall 4.509 → 3.352 days = **1.157 days saved**
  `[R fp32-step-econ-20260611T142831Z.json result.projection_live_total]`.
  Deviation candidate: B=16 conservative (the real trainer adds Muon
  states + MTP heads + loader buffers the bench doesn't carry; 10.83 GiB
  free is honest headroom) with B=24 as the receipted ceiling — E1b
  decides.
- **Kill:** best safe cell < anchor × 1.05 → batch row dead, R2 stands alone.
- **Deviation discipline:** a GAIN receipt changes nothing by itself. The
  config is frozen; the change lands only as a registered deviation PR
  (throughput.batch + the optimizer-coupling evidence from E1b below),
  gated like every other deviation (#218 class). Routed to Eli — the
  runner (eng-54) reads the config contract.

### R2 — governor pacing tax at small batch
- **Limit class:** PACE.
- **Invariant:** `tax = p / (t_c + p)`; p is a FLOOR (env may tighten,
  never loosen). The tax is a function of step size, so it is amortized
  by B without touching the governor.
- **Baseline:** 22.9% of wall at B=4 (1 − 18737.7/24294.7)
  `[R fp19-bench]`; reproduced 21.3% `[L 93e74934]`.
- **Measured:** 13.8% at B=8, **7.3% at B=16** `[L 93e74934]`.
- **Intervention:** same as R1 (one intervention, two rows).
- **Kill:** arithmetic — cannot be falsified separately from R1.

### R3 — torch.compile is broken in the launch environment
- **Limit class:** SCHED (foregone kernel fusion).
- **Fact:** the frozen config promises `torch.compile (TorchInductor) on
  the train step`. In the actual daemon env (torch 2.6.0+cu124,
  transformers with `utils/output_capturing.py`), dynamo tracing of
  LlamaForCausalLM dies with `NameError: name 'torch' is not defined`
  inside transformers' wrapper `[L job 93e74934, full traceback]`. The v0
  trainer will hit the same wall.
- **Consequence:** the config's own fallback clause fires — "fallback
  eager if compile fails on the QAT graph — deviation RECEIPTED". This is
  now a KNOWN pre-launch fact, not a launch-night surprise. The eager
  ceiling (~26k raw at B≥8) is the real planning number.
- **Intervention:** none on the critical path (env surgery pre-launch is
  risk without receipts). Next-rung: pin a transformers version where the
  wrapper is compile-safe, or export the step to a plain nn.Module.
- **Kill:** a future fp32-step-econ receipt with a compile cell status OK.

### R4 — IO / 9p loader starvation: KILLED by arithmetic
- **Limit class:** IO (claimed) — does not bind.
- **Check:** v0 consumes 6.97B tokens × 2 B = 13.95 GB over ≥3.2 days →
  ~50 KB/s sustained. The 9p mount (`/mnt/b`, all daemon jobs' receipt
  args show it) delivers ≥ tens of MB/s sequential — ≥3 orders of
  magnitude headroom. Shard EMISSION reads 25.3 GB once, CPU-tokenizer
  bound (census currently running on it, Eli's lane).
- **Verdict:** not a bottleneck at v0 scale. Recorded so nobody
  "optimizes" it.

### R5 — checkpoint-write stall: WATCH (cadence-dependent)
- **Limit class:** IO, synchronous-stall variant.
- **Bound:** ckpt ≈ 0.74 GB bf16 weights + ~3 GB fp32 AdamW moments +
  Muon momentum ≈ ~5 GB `[H — sizes from param count; measure at first
  real checkpoint]`. Over 9p at ~150 MB/s ≈ 30–35 s GPU-idle per
  checkpoint if written synchronously to `/mnt/b`.
- **Binds iff** cadence < ~10 min (then tax >5%). WSD stable-phase
  checkpoints ride fp-23 probe windows — cadence is an eng-54 impl
  choice. Spec note routed to Eli: write to WSL-native ext4, async copy
  to B:; or accept the stall at sparse cadence.
- **Kill:** first P-own-resume receipt shows ckpt wall ≤5% of segment wall.

### R10 — daemon failures: no evidenced mid-run threat; interruption budget bounded [R] (fp-32c, #234)
- **Limit class:** SCHED (interruption risk to the multi-day run), settled
  as an evidence row. Was "observational (58/439 = 13.2% lifetime)" —
  that framing mixed eras and read fail-closed refusals as waste.
- **Taxonomy** `[R — receipts/fp32-r10-taxonomy-20260611T152522Z.json,
  store snapshot sha-pinned]`: June ember-era 30/285 failed → 8
  NON-EMBER-TRACK (build scripts via daemon) + 2 MISUSE-CLASS (mail
  one-offs) + 14 FAST-FAIL-BOUNDED (next dispatch ≤600 s — setup-class
  iteration, e.g. the 5-in-8-min t2_grpo cluster) + 2 ROOT-CAUSED (R3
  bench crash; D-gate divisor bug, both fixed + receipted) + 4
  UNKNOWN-EVIDENCE-EXPIRED (pre-log_name shared-log overwrite).
  **Evidenced spontaneous mid-run deaths: 0.**
- **Budget (pessimistic — every unknown counted as a death):** 4/11.0
  era-days = 0.364/day → **1.22 interruptions over the 3.352-day v0
  run**, each costing ≤ one checkpoint interval + restart (resume
  bit-exact, v0ext receipt). This row is the interruption-rate INPUT to
  R5/#231's cadence decision: even at the pessimistic rate, cadence-cost
  trades against ~1.2 expected losses, not a crashloop.
- **Re-open:** any v0 segment dying mid-run without a receipted root cause.

## 2. Rows — round loop (fires at first owned-core accumulation round)

### R6 — round wall is generation-dominated ~10:1
- **Limit class:** BW (autoregressive decode) + PACE.
- **Baseline:** borrowed-3B round leg: generation 836.9 s (99 tasks × k8,
  1.057 s/sample, 38.9 verified episodes/gen-min)
  `[R w1-humaneval-q3-20260610T234716Z.json]` vs training 85.6 s / 98
  examples `[R t2-r2-q3-mtp-20260611T044201Z.json]` → gen:train ≈ 9.8:1.
  Generation pacing fraction as-operated: 25.35%
  `[R fp20b-settle-20260611T040647Z.json]`.
- **Structure:** HF `generate` with max_new=512 and batch=8 holds the
  whole batch until every stream stops — short mean completions
  (~46–150 tok `[R fp11 mean_src_chars / 3.5]`) + one straggler = most
  decode slots idle. `[H — slot-occupancy not yet instrumented]`
- **Intervention:** NOT a borrowed-core patch (that loop is fallback-(a),
  #132). The owned-core round-1 sampler is being built fresh against the
  0.37B core — spec it with bucketed lengths / per-stream early exit /
  batch refill from day one. Routed to Eli as a spec note on the round-1
  sampler surface (post-launch item; nothing changes pre-launch).
- **Expected sign:** verified episodes per gen-minute ↑ ≥2× vs naive
  whole-batch decode at equal governor pacing.
- **Kill:** if round-1 sampling wall < 10% of round wall at v0 scale
  (0.37B decodes ~10× faster than 3B), deprioritize — measure first.

### R7 — training share of the round loop: KILLED by arithmetic
- 85.6 s per round-leg of training vs 836.9 s generation `[R above]`.
  Optimizing the round trainer buys <10% of loop wall. Not a bottleneck.

## 3. Rows — verdict instrument (statistical power)

### R8 — round verdicts are STAT-limited, not GPU-limited
- **Limit class:** STAT.
- **Invariant:** the round-gate verdict (GAIN/FLAT/NEGATIVE, fp-27 frozen)
  is computed on N=100 held-out tasks. Paired-difference resolution:
  CI95 half-width = 1.96·√(disc/N); MDE at 80% power ≈ 2.49·√(disc/N).
- **Measured baseline:** live w4 instrument at N=43: CI95 widths
  16.3–20.9 pp `[R w4-eval-r2w-q3-20260611T044559Z.json]`. At the frozen
  round-gate N=100: half-width ±8.8 pp, MDE80 ≈ 11.1 pp at discordance
  0.2 (full grid in `[R fp32-baselines-20260611T142515Z.json]`).
- **Consequence:** a true +5 pp transfer-class effect is INVISIBLE to the
  frozen instrument; fp-25's +75.9 pp in-dist effect was ~7× MDE (which
  is why it was decidable). GPU-hours spent sampling beyond the frozen
  budget buy ZERO verdict information — the verdict channel is capped by
  N, not throughput.
- **Intervention:** none pre-launch (N=100 is frozen in the fp-27 prereg;
  changing it now would be goalpost-moving). Next-rung: round-2 prereg
  may raise N or adopt a group-sequential design — with the MDE table as
  the sizing instrument instead of a habit number.
- **Kill:** a round-1 verdict receipt whose CI is decisively one-sided
  despite the predicted width (i.e., effects at this rung are large
  enough that power was never binding).

## 4. First-principles challenge to the standing hypothesis (Kai, 14633)

Hypothesis as stated: *"the deepest mathematical bottleneck is verified
signal density per GPU-hour."*

Split it by where the GPU-hour goes:

1. **Pretrain (critical path now):** there is no verifier in the loop —
   signal density per GPU-hour is just token throughput × (data quality),
   and the measured limiter is R1/R2 (SCHED+PACE: a bench-default batch
   wasting ~25–36% of achievable throughput) `[L 93e74934]`. Kai's
   hypothesis does not bind here.
2. **Round loop (next rung):** episode SUPPLY is GPU-bound (R6: 38.9
   verified/gen-min, generation 10:1 over training) — here the hypothesis
   is directionally right, with the refinement that fp-25 receipts show
   the binding variable at round-2 was episode DIVERSITY (in-dist +75.9pp
   vs transfer ceiling at the SAME verified-bit budget
   `[R fp25-indist-20260611T060416Z.json, fp25b-surfaceb-*]`) — more
   verified bits of the same distribution would not have moved the
   transfer verdict.
3. **Verdict instrument:** R8 shows the information actually EXTRACTED
   from a round is capped by frozen N (STAT), independent of GPU-hours.

So: "signal density per GPU-hour" is the right lens for exactly one of
the three GPU consumers, and even there diversity-per-GPU-hour, not raw
density, is what the receipts implicate. The deepest CURRENT bottleneck
is R1/R2 — boring, mechanical, and worth ~1+ wall-day before June 22.

## 5. Prioritized plan

Machine-shaped rows (Kai proof-gate schema, every required field):
`research/fp32-bottleneck-ledger.json`.

| # | what | cost | gate | status |
|---|---|---|---|---|
| E1 | step-econ sweep (R1/R2) on idle GPU, synthetic data, governed | ~3 min GPU | anchor reproduction ±10% | **DONE — GAIN** `[R fp32-step-econ-20260611T142831Z.json]` |
| E1b | loss-match pair: two short governed segments (~10M real tokens each) B=4 vs best-B at frozen lr; loss-at-token-budget must match/improve | ~15 min GPU | REQUIRED before the batch deviation lands; needs shards → queued behind re-freeze (#218) | queued |
| — | deviation PR: config `throughput.batch` + E1/E1b receipts | review only | normal deviation gate | after E1b |
| E2 | owned-core round-1 sampler spec: bucketed lengths, per-stream stop, batch refill (R6) | spec only | — | this doc, routed to Eli with eng-54 |
| E3 | checkpoint-write locality (R5) | bench post-census | only if cadence math binds | WATCH |
| — | R8 MDE table → round-2 prereg sizing input | none | — | done (miner) |

**Non-plan (explicitly killed):** 9p loader work (R4), round-trainer
optimization (R7), pre-launch env surgery for compile (R3), any
generation-loop patch to the borrowed core (R6 — fallback track only).

## 6. Critical-path discipline

Nothing in this ledger touches: census → recount → superseding freeze →
#218 deviations → shard rerun → launch gate → governed `--live` dispatch.
E1 used the idle GPU window during the CPU-side census; E1b inserts after
shards exist and before `--live`, inside the launch gate's normal evidence
window. The governor floor (0.80 fraction / 1.5 GiB margin / 0.05 s pace)
is identical in every cell of every experiment — amortized, never loosened.
