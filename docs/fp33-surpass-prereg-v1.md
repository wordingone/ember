# fp-33 surpass prereg v1 — E2B-surpass paired protocol (FROZEN 2026-06-12)

Status: FROZEN at merge commit (this file's landing SHA). Any post-freeze
change is a registered deviation per the fp-30b deviation protocol — file the
deviation note in docs/deviations.md BEFORE the changed run, never after.

This prereg freezes the MEASUREMENT contract for the E2B-SURPASS MILESTONE
(GOAL.md 2026-06-12). It deliberately does NOT freeze the means (base pick,
training plan) — those gate on fp-33 legs E1–E5 receipts and may change
freely without touching this protocol.

## Common protocol (both legs)

- **Opponent:** Gemma E2B, local weights; sha256 of the weight files recorded
  in the first eval receipt and PINNED for all subsequent runs. Never updated
  mid-protocol.
- **Seat-swap rule (GOAL milestone, binding):** E2B is evaluated swapped into
  ember's OWN harness and worlds — same harness commit, same event stream,
  same governed budgets. No bespoke E2B tuning beyond prompt-template
  adaptation (template recorded in receipt).
- **Matched compute:** each paired run records wall-clock, GPU-seconds, and
  token budgets per side; sides must match within 10% or the receipt is
  INVALID (re-run, don't reinterpret).
- **Seeds:** {16, 17, 18} for any stochastic sampling; greedy decoding where
  the harness default is greedy. Harness sha + k + seeds recorded in every
  receipt.
- **Statistics:** paired bootstrap over tasks, 10,000 resamples, 95% CI on
  the per-task delta (ember − E2B). "In ember's favor" = CI excludes 0 with
  positive mean. "Parity-or-better" = CI does not exclude 0 against ember
  (lower bound > −MDE recorded at run time) OR excludes 0 in ember's favor.
  Binary duty episodes use McNemar's exact test, p < 0.05.
- **Receipts-only:** every bar lands as a jsonl/md receipt committed to
  master. No prose verdicts. Governor + headroom rails on every run.

## Leg A — ember-work (best at being ember's work)

- **A1 — floor-world paired eval (binding):** ember owned core vs E2B on the
  frozen verify-floor task distribution (the floor set as of this file's
  landing SHA — receipt must name the floor-set manifest sha). Bar: paired
  delta CI excluding 0 in ember's favor.
- **A2 — accumulation-loop differential (binding; THE thesis bar):** one full
  self-curriculum accumulation round per side at matched compute, through the
  same loop machinery. Each side's gain measured as held-out-transfer delta
  (pre→post), with the standard three-test gate applied (held-out transfer,
  matched control, deletion test). Bar: ember's gain passes all three tests
  AND ember's transfer delta exceeds E2B-in-the-same-seat's transfer delta
  with paired CI excluding 0. E2B failing to produce a three-test-passing
  gain while ember produces one ALSO satisfies A2.
- **A3 — public slices (binding, parity floor):** (i) MBPP validation slice
  (harness exists); (ii) GSM8K test slice, first 200 problems, greedy,
  exact-match answer extraction (harness = eng successor named below). Bar:
  parity-or-better per the statistics block. A3 is a floor, not the contest —
  the contest is A1/A2.

## Leg B — founder-likeness (through the NC-K harness, sp-5)

All B bars run inside the clean-room harness (sp5-nck-harness-port-spec-v0).
Same harness commit both sides; E2B seated identically.

- **B1 — answers when spoken to:** round-trip mail — a probe mail naming an
  on-disk artifact; reply must arrive within the harness's bounded-latency
  window and pass a deterministic content check (names the artifact + one
  correct fact from it, checked by script, not by model judge). 5 probes;
  bar: ember ≥4/5 AND ember > E2B (McNemar if both imperfect).
- **B2 — agency (initiates and completes):** identical replayed event stream
  containing 5 events that obligate an unprompted action (job receipt → gate
  + file receipt; failure event → escalation mail; schedule tick → status
  line). Bar: ember completes ≥4/5 obligated actions with receipts AND
  ember > E2B on completion count.
- **B3 — duty battery (paired, binding):** frozen battery of 20 duty
  episodes (mail triage, receipt gating, schedule actions, file hygiene)
  replayed identically to both sides; per-episode deterministic pass/fail
  (emitted action matches expected verb class + target). Bar: ember strictly
  better, McNemar exact p < 0.05.
- **B4 — evals-through-harness:** the Leg A evals are DISPATCHED through
  ember's harness interface (sp-5 milestone hook receipt). Binary: receipt
  exists.

## Verdict semantics (frozen)

SURPASS = A1 ∧ A2 ∧ A3 ∧ B1 ∧ B2 ∧ B3 ∧ B4, receipts on master by
2026-06-22. Shortfall on the date = measured-distance receipt per the GOAL
CALIBRATION block (which bars passed, numeric distance on each failed bar)
and the loop continues unchanged. Only the user moves the date, the bar, or
retires the milestone — by name.

## Named successors (minted with this freeze)

- eng: GSM8K-200 greedy exact-match harness leg (A3-ii prerequisite).
- spec: B3 duty-battery episode set + expected-verb table (frozen BEFORE
  first B-run; battery content is itself prereg-class).
- The fp-33 E1–E5 base-pick verdict remains open on #255 — it selects the
  MEANS and cannot amend this protocol without a registered deviation.
