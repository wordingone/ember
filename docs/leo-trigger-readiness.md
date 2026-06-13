# Leo-issue trigger-readiness map (verdict side)

Est. 2026-06-13. The verdict-side June-22 audit: every open Leo-class issue,
its **frozen pre-stageable artifact**, that artifact's selftest status, the
exact trigger that fires execution, and the single binding constraint.

This map exists because the eng-stop-gate (Leo-class) names the lowest open
issue each turn. The honest position it records: **all open Leo issues are
already pre-staged to their trigger boundaries** — scorers built, frozen, and
selftest-green — so the remaining work is *execution on receipts that do not
yet exist*. The one thing that produces those receipts is the
c04 → gate-9 → pretrain chain (frozen + gate-coherent as of 2026-06-13 08:34Z,
STATE). That is the STATE-justified critical-path the queue jumps toward; no
Leo scorer can advance further until its trigger receipt lands.

Re-derive this table every tick (sequenced-successor recheck) — never cache
"all trigger-gated." A trigger flips the moment its predecessor receipt lands,
not when someone notices.

| # | issue | frozen artifact | selftest | trigger (fires execution) | binding |
|---|-------|-----------------|----------|----------------------------|---------|
| #205 | fp-27b round-1 verdicts | `fp27b_round1_verdict.py` (fail-closed; GAIN/FLAT/NEGATIVE by paired CI) | **PASS** | round-1 dispatch post floor-PASS | pretrain |
| #210 | sp-2b P/D gate vs sp-2 | sp-2 spec frozen (#201); gate runs on instances | n/a (spec) | first P-own-resume + D-round receipts | pretrain |
| #223 | fp-24b floor verdicts | `fp24_verdict.py` | **PASS** | 1B/2B/4B probe receipts | pretrain ckpt |
| #273 | fp-35 band→allocation | prereg frozen; policy emits on round-1 stats | n/a (prereg) | fp-34 prong-A PREDICTIVE (round-1 stats) | pretrain |
| #282 | sp-6b B3 replay both seats | sp6b v1.1 + duty-battery spec + sp6c seat-adapter FROZEN | n/a (spec) | ember ckpt resident in NC-K + E2B adapter (06-20..21) | pretrain ckpt |
| #328 | fp-36b 1B INFO frame | frozen 1B INFO frame (fp-36b) | n/a (frame) | real 1B probe receipt | pretrain ckpt |
| ~~#359~~ | ~~fp-39 budget/grid recal + density A/B spec~~ **CLOSED 06-13** | both halves delivered + consumed; adjudicated by `fp39-density-power-audit` | — | n/a — disposed | done |
| #372 | fp-41 powered density A/B | graded-probe + multi-seed prereg | n/a (prereg) | a POWERED density run (current was underpowered) | GPU (density) |
| #377 | fp-44 horizon optimizer-equiv | `fp44_horizon_equiv_gate.py` | **PASS** | fp44 horizon-equiv receipt (job 57706bdc RUNNING) | **imminent** |

Also frozen + selftest-PASS, feeding the same terminal gate (not separate
issues): `sp3_terminal_audit.py` (#214, fires 06-22), `fp33_surpass_verdict.py`
(completion-condition #2), `c04_optimizer_pick.py` (the means-side pick).

## Reads off this table

- **7 of 8 open issues gate on the pretrain receipt chain** (#359 closed 06-13).
  Nothing the verdict side can do advances them; the lever is getting to pretrain. The c04→gate-9 chain is
  that lever and it is now frozen + coherent (STATE 08:34Z).
- **#377 (fp-44) is the nearest fire** — its gate is built and green; it
  executes the moment job 57706bdc emits its receipt. That receipt is also the
  P1/P2 input to `c04_optimizer_pick`. One landing, two unblocks.
- **#359 SETTLED + CLOSED (06-13).** Both halves delivered + consumed:
  half-1 recalibration re-priced f_sustained 69.3→42.5 TFLOPS (`c04-budget`
  f_scale=0.613, 38.7% deviation >> 10% trigger) → feeds the §3 budget the c04
  pick uses (`c04-receipt3` budget_b=2.2e9, req_tok_s=25463); half-2 density A/B
  verdict DENSITY_CONFIRMED directional (33.33pp@100%), adjudicated underpowered
  by `fp39-density-power-audit` (bimodal probe → seed is the unit not the prompt;
  n=400 prompt-independence = pseudoreplication; seed-level p=0.50). D-CONF
  consumed as a directional prior, hedged by the 2.2B cap + user ≤1-day bar.
  POWERED confirmation continues under **#372** (the audit's named hardening
  successor: graded probe + more seeds), GPU-gated.

## What "done" looks like per issue

Each row closes when its trigger receipt lands and its frozen scorer emits a
committed verdict receipt (GAIN/FLAT/NEGATIVE, PASS/FAIL, SURPASS/SHORTFALL —
per that scorer's frozen vocabulary). FLAT/NEGATIVE/SHORTFALL are *data*, never
a rung-kill — only the user moves a bar or a date.
