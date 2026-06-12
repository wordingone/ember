# fp-33 — E2B-surpass-by-06-22: objective re-derivation + feasibility envelope

User directive 2026-06-12 (chat, direct): ember must AT LEAST surpass E2B by
June 22, by whatever means — un-defer the ledger, increase size if needed. This
supersedes fp-19's objective ("what fits from scratch by 06-22") with "what
surpasses E2B by 06-22". fp-19's hardware envelope stands; its conclusion is
re-derived against the new objective.

## AMENDMENT (same day, user): kernel-level SOTA work is the engine

The user's actual ask, stated explicitly: Leo acts as the one who SOLVES an
open problem in the AI/ML GPU-kernel space — local compounding AI requires
SOTA-level research and engineering on the stack itself, not application of
published recipes. Base/data/eval below is the VEHICLE; the engine is
kernel-level throughput research on sm89, owned by Leo's hands:

- **Primary target — sm89 FP8 training:** the 4090's Ada tensor cores HAVE FP8
  at ~2x bf16 throughput; the gap is software (TE silent-BF16-fallback,
  torchao tensorwise-only — floor-contract row, receipted). Nobody has
  published a consumer-4090 FP8 pretrain. Solving it = ~1.5-2x every local
  training run, permanently. Break-the-wall floor: unsupported → make it
  supported. The SKIP-with-receipt row re-enters with US as the evidence.
- **Second target — fused Muon kernel:** Newton-Schulz iteration is
  memory-bound; fusion is unclaimed territory at our shapes.
- **Third — small-shape attention + sampler decode path:** F
  (verified-episodes/GPU-h) is the loop currency; decode kernels are its
  inner cost. Flash kernels are tuned for big-model shapes, not 0.4-2B.
- **Selection discipline:** #61 (GPU bottleneck ledger, user via Kai 14633)
  fires FIRST on the live v0 run — profiler receipts pick the target by
  measured wall-clock share, not by what's interesting. Every intervention
  ships with a paired before/after throughput receipt on the same job class.
- Ownership: kernel research+engineering = Leo (research lane, by user
  direction); daemon ops, dispatch, profiling-run execution = Eli.

## The means (re-derivation)

Out-pretraining the E2B bar from scratch is excluded by arithmetic (~1.3e23
FLOPs ≈ decades on one 4090). The path that fits 10 days:

1. **Open-base initialization.** Start from the strongest local open-weights
   base the 4090 can FULL-finetune: ~1.5–2B bf16 (grad-ckpt + 8-bit optimizer);
   QLoRA ceiling ~7–8B if full-tune proves unnecessary. Base bar: zero-shot
   ≈E2B-class on the pinned public slices BEFORE we spend anything.
2. **Un-deferred ledger on top** (floor-contract rows go live, each still
   receipt-gated): distillation from a larger local teacher (offline
   generation, 1-model-at-a-time respected), ember verified-curriculum SFT
   (the loop — our differentiator), QAT for deploy, drafter for sampling
   throughput, MLA/KV probe at sampling rounds.
3. **v0-r1s1 (0.37B from-scratch, job 12c050e7) CONTINUES** as the owned-core
   science rung via timeshare segments — it feeds loop receipts (fp-27b/fp-24b)
   and stays the from-scratch ownership track. The surpass track holds GPU
   priority on conflict; timeshare_pretrain yields between segments by design.

## "Surpass E2B" — receipt definition (to be frozen in prereg before any run)

Paired eval, same harness/k/seeds, run locally: ember-v1 vs Gemma E2B (local
weights).
- **Floor world (binding):** ember's verify-floor task distribution — paired
  delta CI excluding 0 in ember's favor.
- **Public slices (binding, named at freeze):** MBPP validation slice (harness
  exists) + one more pinned at freeze — bar = parity-or-better (CI not
  excluding 0 against ember).
Both must hold by 2026-06-22, receipts on master. No prose verdicts.

## Execution legs (Eli, sequenced; CPU/light until prereg freezes)

- **E1 — base inventory:** what open-weights bases are ON DISK / one-pull
  local, license-clean, with params, quant states. Receipt: table + sha/paths.
- **E2 — full-tune ceiling bench:** measured (not estimated) max params for
  bf16 full-finetune on the 4090 with grad-ckpt + paged-8-bit optimizer at
  seq 1024 — OOM-probe receipt, governed.
- **E3 — E2B local eval harness:** Gemma E2B running locally under our eval
  harness (transformers or LiteRT path), one smoke eval receipt on the MBPP
  slice. Without this the objective is unmeasurable.

fp-33 verdict (mine, gate): pick base + training plan from E1–E3 receipts;
freeze the surpass prereg; then dispatch. fp-19's no-third-retry and governor
rails carry over unchanged.

## Recency update (2026-06-12 web sweep, user-directed)

- **Autonomous-agent recipe research is now the demonstrated SOTA method:**
  Prime Intellect (May 2026) — Claude Code + Codex agents ran ~10k experiments
  in 2 weeks on the nanoGPT speedrun and BEAT the human record (2930 steps vs
  human 2990). Consequence for fp-33: the kernel/recipe work should be run as a
  high-volume agent experiment loop (deterministic harness + cheap-agent
  config mutation + receipts), not hand-iteration. Precedent validates the
  whole compounding thesis at small scale.
- **FP8-on-sm89 has moved since the floor-contract row was written:** torchao
  now ships rowwise + 128x128 blockwise (prototype) FP8 scaling with
  documented pretrain speedups; Triton FP8 GEMM on Ada measured SLOWER than
  CUTLASS `torch._scaled_mm` (triton#5583). Consequence: new leg E5 — verify
  current torchao FP8 rowwise actually engages on our 4090 (micro-bench, SASS
  or kernel-name receipt, no silent bf16 fallback) BEFORE writing any kernel.
  Adopt-over-author if it works; my kernel effort then goes to the residual
  gaps (small-scale FP8 stability, fused Muon, decode path — AdaLLM precedent
  for sm89 custom decode kernels exists).

### Paper sweep (2026-06-12, user-directed "papers as well")

FP8/precision: µnit Scaling 2502.05967 (unit-scaled µP = hyperparameter-free
FP8 stability, validated at small widths — THE stability recipe candidate for
our scale); InfiR2 2509.22536 (end-to-end FP8 pretrain recipe, reasoning
models); To-FP8-and-Back 2405.18710 (stability failure modes to gate against);
optimizer-state quantization 2603.16731 (state staleness/resets — memory
lever). Optimizer: Muon-scalable 2502.16982; Muon at small scale = 30-40%
token/time reduction + quantization-friendlier activations (synergy with QAT);
caution: Muon shows NO consistent gain in ultra-low-bit QAT (2604.07888).
Loop thesis now has published precedent: STV 2605.30290 (self-trained
verification: ~2x hard-math, 14x scientific reasoning), R-Zero 2508.05004
(ICLR26 — RL-trained Challenger curriculum beats untrained generator), MASS
2603.03524 (synthetic self-curriculum). Consequence: ember's
verified-curriculum compounding bet is no longer unprecedented — these are
the baselines fp-27b verdicts get compared against, and µS + InfiR2 define
the FP8 recipe space E5 chooses from.

## What this does NOT change

- Floor-contract invariants (no silent floor→ceiling downgrade) — this is a
  user-directed objective change, recorded here by date.
- Receipts-only truth; prereg-before-run; governed launches; <100GB disk.
- v0 ownership track continues unless the user kills it by name.
