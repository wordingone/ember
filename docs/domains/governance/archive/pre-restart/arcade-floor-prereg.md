# ARC-AGI-3 arcade floor-probe — pre-registration (frozen)

Issue #71 (spec). Frozen 2026-06-11 BEFORE any policy run, per formalization
§7: no training commitment without a measured floor, and the floor's
criterion is written down before the experiment exists. Deviations follow
the audit-§6 registry rule (recorded, power-noted, gate may re-route).

Infrastructure this rides on: `scripts/arcade.py` (#47, PR #66 — offline
`arc_agi` + local `arcengine`, judge = engine verdict ONLY) and its random
reference receipt `arcade-random-smoke-20260610T233807Z.json` (25/25 games,
0 wins, 3 games with level progress @200 steps, seed 16).

## 1. What ember does in this world

Ember writes **explorer-policy PROGRAMS** (Python), not per-step moves. A
candidate is a single function

    choose_action(obs, action_space, rng) -> (GameAction, data)

executed by the harness for a budgeted episode. Verification = the ENGINE's
own verdict (`GameState.WIN`, `levels_completed`) — the world is the
verifier; no model judges anything. This is W-code's shape transplanted:
program synthesis, ground-truth execution, any-of-k feed.

## 2. Frozen game split (sha1(game_id) % 5 — same rule family as #46)

- **train (18):** ar25 bp35 cd82 cn04 dc22 g50t lp85 ls20 m0r0 r11l re86
  sb26 sk48 sp80 tr87 tu93 vc33 wa30
- **heldout (3, hash==3):** ft09 s5i5 sc25 — round evals only, never probed
  for training material.
- **harm-reserve (4, hash==4):** ka59 lf52 su15 tn36 — t5-class only.

Recorded fact, not a choice: 2 of the 3 games where the random floor showed
level progress (ft09, sc25) hash into HELDOUT; sp80/r11l stay in train. The
hash decides; membership is frozen as computed.

## 3. Probe design (the floor experiment)

- **Cores:** 1.5B first, then 3B (smallest-first, mirrors w1). License note
  binds (fp-6/fp-9, audit §8.15/§8.17): episodes destined for the owned
  core's corpus prefer the 1.5B (unencumbered output); the probe measures
  both floors regardless.
- **Generation:** k = 8 policy programs per train game, temp 0.8, seed 14,
  fenced-block extraction (w1 discipline). Prompt carries: obs structure
  (64×64 frame, `available_actions`, `levels_completed`), the
  choose_action contract, and the game id ONLY (no walkthroughs — nothing
  exists to leak; games are interactive-only).
- **Execution:** every program runs every assigned game for **1,000 steps**
  per episode, engine seed 16 (matched to the random receipt), harness
  issues RESET on GAME_OVER (policy never self-resets). Engine cost is
  milliseconds per episode (receipted 0.01–0.26 s per 200 steps), so the
  full probe's verify leg is < 5 min CPU; generation is the binding
  resource — same asymmetry W-code measured at 785× (verify-timing
  receipt), expected steeper here.
- **Matched baseline arm:** random policy re-run at the SAME 1,000-step
  budget × same games × seed 16 (the 200-step receipt is not
  budget-matched; the baseline must be). Its per-game `levels_completed`
  maxima define the random floor vector R(g).

## 4. Frozen admission criterion (engine verdict only)

Per train game g, over its k programs: `best_levels(g)` = max
levels_completed; `win(g)` = any program reaches WIN.

- **F_prog** = |{g in train : best_levels(g) > R(g)}| / 18 — strictly
  beats the budget-matched random floor.
- **F_win** = |{g in train : win(g)}| / 18 — quoted alongside, not the
  admission bar (random's F_win = 0/25 makes any win decisive evidence,
  but the bar must be reachable to admit a floor, not only a ceiling).

**ADMITTED iff F_prog > 0 AND its Wilson 95% lower bound > 0** (at n=18,
one beating game gives lower bound ≈ 0.2% — the same floor>0 shape as
W-code admission and #46). Power note carried on the receipt: n=18 cannot
distinguish F_prog levels below ~15pp; the probe admits or blocks, it does
not rank.

Comparators quoted on the receipt (context, not criteria): frozen dolphin
v3 = 6/25 wins (the-search); the 792-experiment zero-learning RHAE
baseline (the-search ledger).

## 5. Episode semantics on admission

- **Ledger-grade:** win-verified episodes only — (game, program src, seed,
  steps, levels, WIN), `sampler` + `license_class` stamped at ingest (eng
  #70 mechanism). Bits valuation per-game Laplace — round design, NOT this
  probe.
- **Candidate pool:** progress-beyond-random episodes (verified flag
  false) — G2-style material, kept but not burned.

## 6. What fires on the verdict

- **ADMITTED →** NC1d round-design pre-registration (separate doc, its own
  freeze): arms, budgets, G1-analog paired eval on heldout games, t5-analog
  on harm-reserve.
- **NOT admitted →** world stays blocked at this core; harness retained;
  fire condition for re-probe = a core/curriculum change that moves the
  W-code frontier (recorded in the registry, not re-litigated ad hoc).

## 7. Receipts

- Probe receipt: `arcade-floor-<core>-<ts>.json` — per-game rows (program
  sha, steps, levels, final_state, win), F_prog, F_win, Wilson bounds,
  matched-baseline vector, power note, split echo (the §2 lists verbatim —
  a receipt with a different split is invalid by construction).
- Baseline receipt: `arcade-random-1k-<ts>.json`.

*Frozen. Edits after the first probe dispatch are deviations (audit §6).*
