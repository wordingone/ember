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
| #359 | fp-39 budget/grid recal + density A/B spec | spec frozen; `act_model_refit.py` (ledger r18) | — | density A/B verdict (LANDED) — **RECHECK** | see note |
| #372 | fp-41 powered density A/B | graded-probe + multi-seed prereg | n/a (prereg) | a POWERED density run (current was underpowered) | GPU (density) |
| #377 | fp-44 horizon optimizer-equiv | `fp44_horizon_equiv_gate.py` | **PASS** | fp44 horizon-equiv receipt (job 57706bdc RUNNING) | **imminent** |

Also frozen + selftest-PASS, feeding the same terminal gate (not separate
issues): `sp3_terminal_audit.py` (#214, fires 06-22), `fp33_surpass_verdict.py`
(completion-condition #2), `c04_optimizer_pick.py` (the means-side pick).

## Reads off this table

- **7 of 9 gate on the pretrain receipt chain.** Nothing the verdict side can
  do advances them; the lever is getting to pretrain. The c04→gate-9 chain is
  that lever and it is now frozen + coherent (STATE 08:34Z).
- **#377 (fp-44) is the nearest fire** — its gate is built and green; it
  executes the moment job 57706bdc emits its receipt. That receipt is also the
  P1/P2 input to `c04_optimizer_pick`. One landing, two unblocks.
- **#359 / #372 are density-coupled and need a focused recheck.** The density
  A/B verdict (`density-ab-verdict-20260613T043948Z.json`) and power audit
  (`fp39-density-power-audit-20260613T051216Z.json`) have LANDED; the audit
  found the +33pp result underpowered (seed-level Fisher p=0.50,
  pseudoreplication — 12/12 bimodal). That is exactly *why* #372 (powered
  density A/B) is open. Whether #359's spec/recalibration deliverable is now
  dischargeable on the landed verdict is the next verdict-side question to
  settle — flagged, not assumed.

## What "done" looks like per issue

Each row closes when its trigger receipt lands and its frozen scorer emits a
committed verdict receipt (GAIN/FLAT/NEGATIVE, PASS/FAIL, SURPASS/SHORTFALL —
per that scorer's frozen vocabulary). FLAT/NEGATIVE/SHORTFALL are *data*, never
a rung-kill — only the user moves a bar or a date.
