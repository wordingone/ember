# W-code round-1 G1 verdict — pre-registered decision tree (#32)

Written 2026-06-10 ~22:20Z, BEFORE any paired delta is computed. Honesty
note on timing: legs 1–2 receipts (base `w1-floor-g1-base-20260610T215814Z`,
arm-A `w1-floor-g1-a-20260610T220325Z`) are already gated — their POINT
estimates are known (base feed 90.7%, A 81.4%; sample-level 65.7% vs
67.15%). Control and MTP legs are NOT yet landed and no paired test has
been run. The tree below is symmetric across outcomes and binds the
reading of all cells, including the two whose point direction is visible.

## Surface + statistics (binding)

- Validation 43 heldout tasks, k=8, seed 16, identical across arms →
  per-task pairing.
- **Task-level feed** (any-of-8): McNemar on discordant pairs (b = base-only
  fed, c = arm-only fed), exact binomial. n=43.
- **Sample-level rate**: per-task verify rate (of 8), paired difference,
  bootstrap CI over tasks (10k resamples, seed 16) via power.py.
- UP / DOWN = 95% CI excludes 0. FLAT = CI includes 0 — always reported
  WITH the MDE; an underpowered null reads "no detectable effect at MDE X",
  never "no effect".

**CEILING (structural, known from the base receipt before this tree):**
base feeds 39/43 — only 4 tasks of task-level upside exist. Task-level UP
is therefore near-undetectable by construction. Binding consequence:
**sample-level paired delta is the PRIMARY metric for gains; task-level
feed is the primary metric for HARM** (39 tasks of downside room). This is
fixed now so the verdict cannot cherry-pick its metric after the fact.

## Decision axes

- **D1 — A vs base** (did training on own verified episodes move the
  heldout floor?): UP / FLAT / DOWN per the primary-metric rule above.
- **D2 — A vs control** (the goal's matched-control gate: is the signal
  CONTENT, not format?): A>C / A≈C / A<C on the same metrics.
- **D3 — MTP vs A** (does the densified aux signal buy anything at matched
  data/steps?): MTP>A / ≈ / MTP<A.
- **Signature check — "sharpening-narrowing":** task-feed DOWN while
  sample-rate UP (the t5-harm family: mass concentrates on solved modes,
  tail coverage lost). Checked on D1 regardless of cell.

## Cells → named round-2 designs

| D1 (A vs base) | D2 (A vs control) | Verdict reading | Round-2 design |
|---|---|---|---|
| UP | A>C | Genuine verified-experience gain | **R2-SCALE** |
| UP | A≈C | Format effect masquerading as gain — content null | **R2-RETHINK** |
| FLAT/DOWN | A>C | Content signal exists but objective narrows/wastes it | **R2-PRESERVE** |
| FLAT/DOWN | A≈C | Content null at this scale | **R2-RETHINK** |
| any | A<C | Verified episodes WORSE than fails — verdict-class anomaly | **R2-INVERT** |

- **R2-SCALE** — the loop works: more rounds, adaptive-k sampling on
  frontier/dead, ext-clean builds (#22), bank-and-train cadence; winner arm
  continues; MTP per D3.
- **R2-PRESERVE** — coverage-preserving mechanism becomes MANDATORY in
  every arm: KL-to-base (GRPO #24 has it built in), replay-mix, or
  retrain-from-base-on-full-ledger; plain-SFT continuation is dead as a
  candidate (kept only as a baseline arm). Fires automatically if the
  sharpening-narrowing signature confirms on paired tests.
- **R2-RETHINK** — content null: 209 ext-clean bits is the suspect numerator.
  math-1 (#29) + math-2 (#30) decide between (a) accumulate-more-rounds
  before training (bank episodes across sampling rounds, train at a bits
  threshold), (b) denser worlds (reasoning-2 #33), (c) fp-1 (#37) smaller
  core — the 90.7% base feed says validation MBPP may be near-saturated for
  3B: the world's headroom, not the method, may be the binding constraint.
- **R2-INVERT** — audit the data path (leakage, ext-noise asymmetry,
  split contamination) BEFORE any design choice; no round-2 launch until
  the anomaly is explained with receipts.

**D3 overlay (independent of the table):** MTP>A → MTP joins the round-2
default recipe; MTP≈A → drop at SFT scale (simplicity), re-evaluate at the
NC2-own pretrain rung where its real case lives (denser signal per token at
a 20B-token budget); MTP<A → receipt the negative, same pretrain-rung
re-evaluation, never silently dropped.

**t5 harm gate (binding, rides on top of every cell):** any arm advancing
to round-2 must show t5 non-regression vs base on MBPP-50 test split —
round-1's only significant effect was harm; a G1 winner that regresses t5
is dead. GRPO joins this same tree when #24 makes it trainable.

## Analysis invocation (pre-registered)

power.py paired mode over the four samples files
(`w1-floor-g1-{base,a,control,mtp}-*-samples.jsonl`), seed 16, 10k
bootstrap, both metrics + McNemar counts + MDE. The deltas receipt MUST
name which cell of this tree fired and which round-2 design follows.
