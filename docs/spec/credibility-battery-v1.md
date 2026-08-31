# Credibility battery v1 — the 15-question evidence registry

Source: [issue #487](https://github.com/wordingone/ember/issues/487) (2026-07-08), which this
document lands verbatim as a standing registry. Read `docs/domains/governance/guides/START-HERE.md` first if any term below
is unfamiliar.

## The operator-set bar (verbatim, 2026-07-08)

> If every question has a precise, receipt-backed answer, Ember becomes credible. If every answer
> is clean under external review, Ember becomes publishable. If the answers show a real effect
> that survives ablations, matched-budget controls, leakage checks, and external benchmarks, then
> Ember may be a serious contribution.

**Strong-answer schema (verbatim):**

> Baseline is commit X, config Y, dataset Z, budget B, eval suite E, run receipt R. It scores
> A/B/C. Ember variant differs only by mechanism M. Matched control gets N. Ablation removing M
> collapses the gain.

## Standing rules (binding)

1. Any PR banking a capability claim must update the battery row it touches.
2. A claim whose battery row is not STRONG is not publishable-class, whatever its board color.
3. The stranger-audit protocol (issue #481) re-grades this battery on its cadence — external-review
   cleanliness is graded by a reader with no context, never by the team that wrote the claim.
4. **Any answer without an openable, repo-relative artifact path grades ABSENT**, regardless of
   what any prose (including this document's own source issue) asserts. A grade of WEAK or STRONG
   requires a path a stranger with only this repository can open and check today.

**Enforcement-gap disclosure (per issue #487 comment, 2026-07-08):** rule 1 is currently text with
no mechanical check. The proposed cure is a `tools/repo-guard.sh` heuristic (a diff adding
claim-bearing receipts without touching this file fails the guard) — not yet implemented. Until it
lands, rule 1 is enforced by coordinator review, not by machine. This gap is disclosed here on
purpose, per the same legibility standard the rest of this document holds itself to: an external
reviewer should know which rule is code-enforced and which is enforced by habit.

## Reading this battery honestly

Every path below was checked against this repository at the time this document was written —
each one either opens to a real file, or is marked otherwise. Issue #487's original fill (quoted
per-question below) cited a few artifacts that were, at the time, generated locally in this
repository's own working tree but not yet landed by a PR — most visibly a newer totality-board
receipt, `ember-totality-20260708T215158Z`, and a newer D3 loop receipt,
`d3-native-loop-20260708T221708Z`. Neither is a different or private repository's artifact: this
repo's own custody check (`scripts/ember_totality/test_c_custody.py`) names exactly this state
`pending_landing` — a fresh, untracked file in the working tree, real and locally generated,
simply not yet committed. As of this PR's rebase onto `public/master`, both remain untracked-
pending-landing (a custody lane is landing the D3 receipts; board receipts land with board-run
PRs) — disclosed per-row below, not silently smoothed over. One prior gap in this same family has
since closed: the eval-suite-freeze spec and pin receipt this document's Q14 originally disclosed
as absent landed via PR #490 and are cited directly there now. Per this document's own rule 4, an
artifact a stranger cannot open does not support a STRONG or WEAK grade; where this repo cannot
yet show a cited artifact, the closest artifact this repo **can** show is cited instead, and the
gap is named.

---

## Q1 — Baseline

**Strong-form schema, instantiated:** a from-scratch owned checkpoint at a pinned commit/config/
corpus-manifest/budget/eval-suite, with one receipt naming all five.

**Grade: WEAK** (issue #487). Per-experiment arms exist with equal-budget blocks inside individual
loop receipts, but the *program-level* from-scratch baseline is not yet a single closed artifact.

**Check it yourself:**
- `docs/domains/governance/spec/conditions-v1.md` §4.2, condition `C1` — the CHK a discovery receipt must pass
  (sources + hashes + rationale + in-tree hash-verify).
- `receipts/ember-post-resident-discovery/benchmark-discovery-20260620T230519Z.json`,
  `receipts/ember-post-resident-discovery/benchmark-discovery-20260621T070500Z.json`,
  `receipts/ember-post-resident-discovery/benchmark-discovery-20260622T011400Z.json` — the three
  candidate discovery receipts the board's `C1` row names as failing hash-verify (in-tree,
  openable now).
- `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` — the newest
  board receipt in this checkout; its `C1` row reads `RED` for exactly this reason. Issue #487's
  fill cites a later board receipt (`ember-totality-20260708T215158Z`) generated locally in this
  repository's working tree but not yet landed via a board-run PR (`pending_landing`, per
  `scripts/ember_totality/test_c_custody.py`) — the `RED` verdict itself is confirmed by both;
  the exact violation count may differ between the two receipts.

## Q2 — Exact claim

**Strong-form schema, instantiated:** Ember variant differs only by mechanism M; state the exact
delta measured.

**Grade: WEAK-to-STRONG** for the one banked measurement claim (issue #487): the rung-2
zero-momentum commutation measurement. Everything else is **ABSENT** — no capability claim is
currently banked (an honest zero, not a gap).

**Check it yourself:**
- `receipts/cbase-grow-rung2-event-grow-rung2-20260708-real-b3.json` — walked field-by-field in
  `docs/domains/governance/guides/START-HERE.md` §3. `d_comm = 0.156090`, `cos_alignment = 0.988060`, band `iii`.
- [issue #449](https://github.com/wordingone/ember/issues/449) — the frozen measurement protocol
  and its later amendment (the u_pre provenance correction; see the START-HERE walkthrough).

## Q3 — Ablation

**Strong-form schema, instantiated:** ablation removing mechanism M collapses the gain.

**Grade: WEAK** (issue #487): a deleted-arm collapse was measured the same day issue #487 was
filed; the momentum-side ablation is only half-valid pending a re-measure (the same defect the
`b3` receipt's amendment covers).

**Check it yourself:**
- `receipts/ember-d3-native-loop/d3-native-loop-20260704T161315Z-c3-wall-time-rerun-redacted-edition.json`
  and `receipts/ember-d3-native-loop/d3-native-loop-rerun-20260704T-redacted-edition.json` —
  executed instances of this repo's fixed A/B/C/Deleted contract (`docs/domains/governance/spec/conditions-v1.md`
  §6), the general mechanism this question's ablation runs against.
- **Disclosed gap:** issue #487 cites a receipt, `d3-native-loop-20260708T221708Z.json` (the
  specific 1.0 → 0.054 collapse number), generated locally in this repository's working tree but
  not yet landed — a custody lane is landing it now (`pending_landing`, per
  `scripts/ember_totality/test_c_custody.py`), not a different repository's artifact. That
  specific number is not independently verifiable from this checkout until it lands.

## Q4 — Matched compute control

**Strong-form schema, instantiated:** the Ember variant's matched control gets N, under an
equal-budget arm.

**Grade: WEAK** (issue #487): equal-budget arms are executed at the loop-mechanism level; the
training-claim dense control (W2 S-arm) is designed but not yet executed.

**Check it yourself:**
- `receipts/ember-d3-native-loop/d3-native-loop-rerun-20260704T-redacted-edition.json` — the
  board's `C3` `GREEN` evidence: a real equal-budget A/B/C arm contract (`docs/domains/governance/spec/conditions-v1.md`
  §4.2, condition `C3`).
- `receipts/ember-c-scale/w2-garm-108-verification-w2-garm-dryrun-20260706T043654Z.json` and the
  sibling `w2-garm-*-w2-garm-dryrun-20260706T043654Z.json` files — the W2 S-arm design
  ([issue #108](https://github.com/wordingone/ember/issues/108)), captured as a **dry-run**, not a
  live execution — matching issue #487's "designed but never executed."
- `docs/domains/governance/archive/pre-restart/c-scale-execution-graph.md` §"W2 Window" — states plainly that W2's fields are
  fixture-only (`ts 20990101`), no live receipt yet.

## Q5 — Reusable capacity vs. overfitting / leakage / bookkeeping

**Strong-form schema, instantiated:** the measured gain is capacity, not leakage or a bookkeeping
artifact — proven by a held-out split with a leakage predicate run against it before the claim.

**Grade: WEAK** (issue #487): the framework exists (`C2`'s held-out conjunction, D-gate/P-gate,
a leakage predicate); no at-scale capability delta has survived it yet.

**Check it yourself:**
- `docs/domains/governance/spec/conditions-v1.md` §4.2, condition `C2` — the held-out-task CHK (frozen-before-run,
  no label-read in the candidate path).
- `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` — board row
  `C-SCALE`, `RED`: no at-scale capability point currently clears.
- [issue #440](https://github.com/wordingone/ember/issues/440) — the corpus near-duplication
  defect this leakage predicate is designed against. **Disclosed gap:** no receipt path for the
  "calibration scan in flight" mentioned in issue #487's fill is present in this checkout.

## Q6 — Receipts-to-claim correspondence

**Strong-form schema, instantiated:** the receipt's own fields, independently re-derived, produce
the stated verdict — not asserted, not hand-waved.

**Grade: STRONG as a process, WEAK as coverage** (issue #487): the board mechanically re-derives
verdicts from artifacts (this same PR's `docs/domains/governance/guides/START-HERE.md` §3 is one worked example — a
falsified provenance line was caught and amended, in the open, not silently); custody coverage
itself is not yet fully clean.

**Check it yourself:**
- `docs/domains/governance/guides/START-HERE.md` §3 — the `b3` receipt's `u_pre` provenance falsification and its
  correction, worked end to end.
- `docs/domains/governance/custody/custody-disposition-20260708.md` — the dated, row-by-row disposition record for every
  currently-cited-but-missing receipt path (governed by
  [issue #415](https://github.com/wordingone/ember/issues/415) and
  [PR #432](https://github.com/wordingone/ember/pull/432)).
- `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` — board row
  `C-CUSTODY`, `RED`, 27 violations in this checkout (issue #487's fill cites a different,
  later count from a board receipt not present here — the `RED` verdict is confirmed either way).

## Q7 — Fits 24GB?

**Strong-form schema, instantiated:** the measured (not estimated) VRAM footprint of inference and
of training, against the 24 GB card.

**Grade: STRONG for inference/measurement; STRONG-NEGATIVE for training-as-spec'd** (issue #487).

**Check it yourself:**
- `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json` — real, measured (not
  synthetic-estimated) VRAM: `total_gib: 23.988`, peak `used_gib: 19.465` under contended
  conditions (resident server never stopped).
- `docs/domains/governance/ledgers/deviations.md` (the rung-2 production-stabilization deviation entry) — the frozen spec's
  VRAM-resident-AdamW config is measured at an estimated **30.903 GiB required vs. 23.988 GiB
  total** — infeasible outright. Cure path:
  [issue #480](https://github.com/wordingone/ember/issues/480).

## Q8 — What runs on the 4090

**Strong-form schema, instantiated:** a receipted, liveness-checked account of what process/model
is actually resident on the GPU at any given time.

**Grade: STRONG** (issue #487).

**Check it yourself:**
- `src/ember/governance/scripts/cockpit_watchdog.py` — the standing liveness watchdog (issue #362): composed predicate
  over window/process/VRAM-tenant residency, report-only, one receipt row + one heartbeat row per
  cycle (module docstring, read in full for the exact composed-state logic).
- `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json`'s `server_contention` block
  — the resident-server-liveness check executed as part of a training-side measurement, disclosing
  exactly what was and was not reachable during the probe.

## Q9 — What is offloaded

**Strong-form schema, instantiated:** which tensors/states leave VRAM, to where, and under what
mechanism.

**Grade: WEAK** (issue #487): the memmap optimizer-state mechanism is landed; the production
offload configuration itself is still unpriced.

**Check it yourself:**
- `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json` — a real CPU-offloaded
  optimizer + micro-batch/accum configuration (`arm: rung2-cpu-offload-cure-gpu-measured`, PR
  #429), including its own disclosed crash history (issue #446) and the mitigation used.
- `docs/domains/governance/ledgers/deviations.md` — candidate cures (gradient checkpointing, batch reduction + grad
  accumulation) priced against the same receipt, with `MEASURE` slots explicitly marked
  `REGISTERED-PENDING` rather than asserted.

## Q10 — Throughput

**Strong-form schema, instantiated:** measured tokens/s (or equivalent) at the production
configuration, not a synthetic estimate.

**Grade: ABSENT at production config, deliberately** (issue #487): a synthetic-vs-real divergence
was found and receipted; no throughput number is claimed until the real path is measured.

**Check it yourself:**
- `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T160854Z.json`,
  `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T171259Z.json`,
  `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json` — successive
  measured-not-estimated probes on this exact question, each disclosing its own scope limits
  (module docstrings +
  `scope` field) rather than a throughput headline.

## Q11 — Batch-size sensitivity

**Grade: ABSENT** (issue #487): no sweep receipt exists; a muP same-LR check is queued.

**Check it yourself:** none — this is an honest zero. No `mup`-named file exists anywhere in this
repository as of this PR; there is nothing to cite because nothing has been measured.

## Q12 — Training-loop stability

**Strong-form schema, instantiated:** the loop runs stably over a long horizon at production
scale, receipted.

**Grade: WEAK** (issue #487): bounded episodic receipts exist; a long-horizon run at production
scale has never executed; the WSD (warmup-stable-decay) schedule's exact production parameters are
undisclosed — flagged as an open unknown for the next growth rung, not asserted either way.

**Check it yourself:**
- `receipts/cbase-grow-rung2-event-grow-rung2-20260708-real-preflight.json` and
  `receipts/cbase-grow-rung2-contended-launch-gate-20260708T125724Z.json` — bounded, episodic,
  receipted phases of the same rung-2 event; neither is a long-horizon production run.

## Q13 — Wall-clock / VRAM / checkpoint / optstate / recovery

**Strong-form schema, instantiated:** all five measured together, on the same run, with one
consolidated closure receipt.

**Grade: WEAK** (issue #487): all five are measured *per-event*, with receipts; no single
consolidated closure row exists yet — this is exactly what board condition `C-EFF` is RED for.

**Check it yourself:**
- `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` — board row
  `C-EFF`, `RED`: "no `receipts/ceff-RESOLVED-*.json` closure receipt."
- `receipts/cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json` — VRAM + wall-clock +
  contention state measured together for one event (not a closure receipt, a component measurement).

## Q14 — External benchmarks

**Strong-form schema, instantiated:** the model's score on a frozen, external, zero-cost,
contamination-audited eval suite.

**Grade: WEAK** (updated post-#490 landing) — the suite is now frozen and pinned, but no
reference run has executed against it yet, so no capability claim can cite a score from it. This
is an upgrade from issue #487's original gap ("the frozen external eval suite does not exist in
this repository yet") — the suite exists now; running it does not.

`docs/domains/governance/spec/eval-suite-freeze-v1.md` (landed via PR #490) freezes 7 of 8 test splits by sha256
(MMLU-Pro, GSM8K, MATH-500, ARC-Challenge, HumanEval+, MBPP, HellaSwag) plus the harness commit
(`EleutherAI/lm-evaluation-harness@97a5e2c710e2b56b9dd48f367bb6fe87bbb2c176`); the 8th split,
GPQA-diamond, is honestly `PIN-PENDING` — its automated download is blocked pending HuggingFace
license acceptance (the receipt's own `blocker` field states this). The spec's Clause 2 (Binding
Clauses) requires reference scores to be locally reproduced, never paper-quoted, and names the
first such run as still riding "the next free GPU window" — it has not happened yet.

**Check it yourself:**
- `docs/domains/governance/spec/eval-suite-freeze-v1.md` — suite composition, the harness pin, and both binding
  clauses (Clause 1: text+code-only, explicitly insufficient for a C1 parity claim; Clause 2:
  local-reproduction-not-paper-quoted).
- `receipts/eval-suite-freeze/eval-suite-freeze-v1.json` — the freeze receipt itself: per-split
  sha256/row-count/size-bytes, the pinned harness commit, and GPQA's `PIN-PENDING` status with
  its blocker reason, openable directly.
- **Disclosed gap:** no reference-run receipt exists yet against this suite. Until one lands,
  this question stays WEAK regardless of how complete the frozen suite itself is — a suite nobody
  has run yet proves nothing about any model's score.

## Q15 — Internal benchmarks

**Strong-form schema, instantiated:** a code-gated, receipt-backed internal scoreboard, honestly
reported.

**Grade: STRONG** (issue #487): the totality board — 40 conditions (37 state-conditions + 3
process-invariants), code-gated, honestly re-derived from artifacts every run.

**Check it yourself:**
- `scripts/ember_totality/receipts-totality/ember-totality-20260708T034014Z.json` — the newest
  board receipt in this checkout: 7-GREEN / 28-RED / 2-UNEVALUABLE / 3-AUDIT-PENDING-EPOCH.
  `docs/authority/CONTINUITY.md` generated status (`src/ember/governance/scripts/gen_readme_status.py`) always points
  at whichever receipt is newest in its selected receipt root.
- `docs/domains/governance/spec/conditions-v1.md` — the full registry these rows are checked against.

---

## How to use this battery

Pick any row above, open the path(s) it cites, and check the grade against the artifact yourself —
this is the concrete instance of `docs/domains/governance/guides/START-HERE.md` §5's "verify one claim yourself" recipe.
Grades change only when a new PR cites the receipt that moved them (standing rule 1); this
document is re-graded by the stranger-audit protocol on its own cadence (standing rule 3, issue
#481).
