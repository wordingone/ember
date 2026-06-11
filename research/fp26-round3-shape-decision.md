# fp-26 — round-3 shape under the transfer ceiling + frontier exhaustion (#166)

DRAFT 2026-06-11 (~06:42). Decision artifact for the round-3 fork. Verdict
wording for the B-surface premise is held OPEN pending the monitor's MDE
audit reply (mail 14582 ask #2: CEILING vs UNDERPOWERED-AT-FLOOR at N=17);
everything else here is receipt-derived and stands either way.

## Receipted premises (binding inputs)

| Premise | Receipt | Consequence |
|---|---|---|
| Recipe LEARNS in-dist (+75.9pp sft on trained tasks; control BELOW base) | `fp25-indist-20260611T060416Z` | the verify-floor loop's learning mechanism is validated; verified content carries it |
| No transfer at 98-episode budget (all arms FLAT on 17 held-out frontier, fresh seed) | `fp25b-surfaceb-20260611T063604Z` | re-running transfer at the same budget in the same world is DEAD |
| Frontier exhaustion: 120-pool = 76 easy + 29 trained + 8 dead + 7 frontier | `w4-eval-fp25b-cov-20260611T060930Z` + `fp25b-select-20260611T062523Z` | the sanitized MBPP world cannot host another training round of r2's shape |
| v0 owned-core pretrain envelope: 4.55 d receipted-unstacked to compute-optimal (3.12/2.56 stacked, conditional) | `fp19-bench-20260611T024648Z` (+ v2 table) | owned-core v0 fits the June-22 window with margin |
| v0 corpus merged: 25.30 GB / 7.39 B heuristic tokens, license-clean | eng-36 assembly receipt (#149) | corpus dependency of the owned core is CLOSED |
| Tokenizer freeze in flight (#160; production receipt pending) | eng/160 branch + monitor audit 14576 | the last gate before v0 pretrain launch |

## Candidate shapes

**(a) Borrowed-core round 3 in a deeper world** — episode-budget scale-up
to test whether the ceiling moves with verified-episode count.
- World candidates needing a frontier-depth coverage receipt (the gated
  fp25b-cov shape, reusable as-is): MBPP+HumanEval union (164 untouched
  tasks, same harness family); full-MBPP re-sanitization (254 excluded
  tasks — RISK: sanitization exists for verifier soundness; re-admission
  weakens the floor and is likely a false-accept channel — disfavored);
  ARC-1 code-synthesis (the original NC0 world; deep frontier, heavier
  verification).
- Cost: per round-2 receipts, a full round (sampling + 3 arms training +
  gate evals) ≈ 1.5–2 GPU-days, against an 11-day window that also has to
  fit v0 pretrain (~4.6 d receipted-unstacked).

**(b) Owned-core in-dist accumulation as round 3 proper** — the NC2-own
shape: v0 pretrain (corpus ✓, tokenizer pending) → fp-22 verify-floor
world → accumulation rounds where eval distribution = train distribution
BY CONSTRUCTION.
- This is what the fp-25 decomposition validates: the loop's proven
  mechanism is in-dist accumulation; the owned core's world is in-dist by
  design, so the receipted ceiling does not bind it.
- fp-21b (#132) + fp-20c (#146) retarget to the owned core's FIRST
  sampling round (they are round-3-sampling-triggered, core-agnostic).
- fp-24 (#139) fires on real v0 checkpoints — same launch.

## Recommendation (Leo, receipt-derived; user may redirect)

**(b).** Rationale: (1) every additional borrowed-core round spends the
June-22 window on instrumentation for a substrate that is explicitly not
the terminal one (NC2-own non-negotiable); (2) the decomposition already
extracted the borrowed core's lesson — mechanism validated, transfer is
data-scale; (3) the owned core's loop is structurally immune to the
specific receipted failure (eval=train distribution); (4) the envelope
fits with margin only if v0 launches promptly after tokenizer freeze.

**(a) demotes to the pre-registered fallback:** if the v0 owned core
cannot clear a K1-equivalent verify floor in the fp-22 world even with
curriculum synthesis (the NC2-own rung-level kill), the borrowed core
returns as the instrument, in the MBPP+HumanEval union world, WITH a
frontier-depth coverage receipt gated before any prereg freeze.

## Monitor wording resolution (Kai 14589 — closes AC item 4)

The B-surface premise wording is RESOLVED. `OOD-TRANSFER-CEILING` is
acceptable **only as scoped to the preregistered floor**: no detected
≥13–21pp transfer effect on N=17 held-out frontier tasks at the
98-episode budget. It must NOT be propagated as "no small transfer
exists" or as architecture-level evidence. UNDERPOWERED-AT-FLOOR is a
**caveat**, not the primary verdict, because the receipt reports the MDE
and the claim is budget/floor-scoped. The fp-26 prereg carries this
scoping verbatim; the round-3 decision rests on the floor-scoped reading,
which does not over-claim and is robust to the power caveat (the
recommendation holds whether or not a sub-floor transfer effect exists,
because (b)'s world is in-dist by construction and does not depend on
transfer at all).

## AC checklist (from #166)

- [x] World chosen + rationale (this artifact; world = fp-22 verify-floor
      world on the owned corpus)
- [~] Frontier-depth receipt for the chosen world — for (b) this is the
      v0 world's task-pool coverage run, **executable only post-v0-pretrain**
      (preregistered obligation, gated by `fp26_prereg.py` as a deferred
      post-checkpoint receipt); the fallback (a) world keeps the
      fp25b-cov-shape coverage obligation BEFORE any (a) prereg freeze
- [x] Round-3 prereg frozen BEFORE any training dispatch — `fp26_prereg.py
      --freeze` emits `fp26-prereg-<ts>.json` (`prereg_frozen:true`),
      pinning this artifact + the two fp-25 premise receipts (tamper-guarded)
- [x] Monitor audit of the B-surface wording incorporated (14582 ask #2 /
      14589 — section above)

*Owner: Leo (#166 / task #49). Status: FROZEN. Round-3 shape = (b)
owned-core in-dist accumulation (v0 pretrain → fp-22 verify-floor world →
accumulation rounds, eval=train by construction); kill rule → fallback (a)
with its own pre-freeze coverage obligation. The frontier-depth receipt
for (b) is a deferred post-v0-checkpoint obligation, not a launch blocker.*
