# C04 pretrain launch — authorization brief (Jun-facing, pre-staged)

Est. 2026-06-13 ~14:15Z, BEFORE the deciding clean §3 receipt lands. The
multi-day C04 governed pretrain is the next rung. Both candidate profiles exceed
12 GPU-h, so by the long-job-launch rule the launch needs **a measured lever
receipt + Jun authorization** — it is not a checkpoint to start silently. This
brief is the single decision, every number pre-computed, **one fill-in** from the
clean bench. The moment gate-9 passes, the ask below is ready — launch is
execution, not improvisation.

## What is being authorized

The **C04 governed pretrain run** — the from-scratch owned-core accumulation
(round-1), 2.2B-token governed budget, weights trained on this machine alone
(goal: "weights eventually pretrained from scratch here"). Launching it fires the
round-1 execution chain (#205) and begins the checkpoint stream that gates the
downstream verdicts (1B probe → #223/#328; D/P rounds → #210; coverage → #208).
It is the rung the 8 gated Leo issues sit behind.

## Why it reaches you (not auto-launched)

Both candidate profiles are multi-day / >12 GPU-h:

| profile | tok/s | governed days | bar (≤1 day) |
|---|---|---|---|
| Muon-batched (if clean bench clears §3) | ≥25462.963 | ≤1.000 (by §3 definition) | **PASS** |
| AdamW | 27702.8 | 0.919 | PASS |
| Muon un-batched | 19223.3 | 1.325 | OVER |

§3 (≥25462.963 tok/s) **is** the ≤1-governed-day bar for 2.2B tokens
(2.2e9 / 86400). So a Muon-batched receipt that clears §3 is ≤1 day by
arithmetic, not by promise. The long-job rule still routes the launch to you for
the go — the clean bench is the measured lever receipt that backs it.

## The decision — one fill-in from the clean §3 receipt

`python scripts/c04_optimizer_pick.py` reads the clean no-sync bench
(measure=False, harness b73b85b) and emits the committed optimizer. Two outcomes:

- **PROFILE A — clean bench `tok_s_paced` ≥ 25462.963** (and ns5_equiv ≤ 2e-7):
  → `COMMIT_MUON_BATCHED`, fp44 moot. **Muon is kept** — the C-3 design
  optimizer, measured-lower loss at 2000 steps — at ≤1 governed day. This is an
  **informational** authorization: no quality tradeoff, just the long-job go.
  gate-9 `--optimizer muon_batched` (authorization path verified open, #405).

- **PROFILE B — clean bench short (< 25462.963)**: the **genuine tradeoff**, the
  only branch that is a real choice for you:
  - **Keep Muon** → requires the torch≥2.7 compile env-bump (the last
    Muon-preserving lever; un-batched Muon is 1.325 d, over the bar). Cost:
    shared-env major version bump = your risk-envelope call.
  - **Take AdamW** → clears §3 free at 0.919 d. Cost: the measured quality gap =
    fp44 `delta_T = −0.746` nats (Muon lower). **That edge is thin and
    jude-flagged**: 0.141 nats over the 0.605 noise floor, and it collapses to
    within-noise by step 1500. AdamW is **not** auto-picked to dodge the
    escalation — the measured delta and the floor are both on the table.
  - Only you move the env-risk envelope or the ≤1-day bar (§4.5 residual).

## Governor rails — mechanical, non-negotiable, identical both profiles

VRAM_FRACTION=0.80 · MARGIN_GIB=1.5 · decode pacer 0.05s. Margin violation
auto-kills the launch; **fix-forward on a margin violation is BANNED** — the run
is killed and relaunched governed (the 2026-06-10 PC-crash precedent). This is
what makes a multi-day unattended run safe.

## Means-side authorization chain — PROVEN, not asserted

Each link verified by my own execution (receipts-only), both block and green
paths, both optimizers:
- config frozen; `c04_optimizer_pick` frozen + **order-safe** (#395 — holds
  PENDING while the bench is absent-but-expected; never prematurely escalates).
- gate-9 **couples** authorization to the committed pick (#396 —
  `_PICK_TO_GATE9` has exactly 2 keys; PENDING/HOLD/ESCALATE and every other
  optimizer → BLOCKED). `--force-optimizer-authorized` is the **only** user
  override.
- gate-chain scorers crash-hardened against malformed receipts, fail-closed
  (#411 fp44 / #412 pick / #413 fp33, merged 2026-06-13 — a garbage field can
  never produce a false-permissive verdict).

Nothing can authorize a launch on an optimizer the pick has not committed.

## Kill criteria — frozen BEFORE launch (anti-goalpost)

The run aborts (not babysat) on any of:
1. Governor margin violation → auto-kill (mechanical, already wired).
2. D-gate or P-gate failure at any owned-core instance (sp-2 / #201) → halt.
3. Loss divergence / NaN → halt.
4. Sustained throughput regression below the committed profile's measured tok/s
   → halt + re-measure (the run is measurement, not a checkpoint to nurse).
5. Checkpoint-1 (1B) floor-probe FAILS the fp-24b floor → halt **before**
   continuing to 2B — do not spend the remaining GPU-days on a run the
   floor-probe says will not transfer.

## The ask (ready at gate-9 green)

> Authorize the C04 governed pretrain launch on **[Profile A: muon_batched]** /
> **[Profile B: your tradeoff pick]**, **[N]** governed GPU-days, rails + kill
> criteria above?

## Status — what is pending before this reaches you

The clean no-sync production bench receipt (eli; GPU-serialized behind the
density seed-2 D-CONF run — one model at a time on the single GPU) is the lone
remaining input. It decides Profile A vs B. This brief is pre-staged so the
moment it lands the gate→pick→gate-9 is mechanical and the ask is one fill-in.
