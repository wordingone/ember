# fp-36: 1B INFO probe — pre-registered interpretation frame v0 (FROZEN)

The 1B-token checkpoint (~step 244k of run 12c050e7) is the first fp-23
PROTOCOL probe. Its `decide()` verdict is INFO by frozen design — the
protocol consumes it mechanically, but what the reading MEANS is otherwise
unconstrained prose at verdict time. This document freezes the
interpretation BEFORE the data exists, while the only observations are two
mute pre-protocol points. Same discipline as the sp-6b designation rule:
remove the discretionary input before it can bias the call.

## Observed trajectory at freeze time (all data that exists)

| checkpoint | tokens | L1 verified | tasks any-verified | governed-min | receipt (sha256 prefix) |
|---|---|---|---|---|---|
| step-25000 | 102,400,000 (0.1024B) | 0 | 0/100 | 51.685 | sp-checkpoint-probe-step-25000-20260612T090913Z.json (6ccec8468ba06637) |
| step-50000 | 204,800,000 (0.2048B) | 0 | 0/100 | 48.965 | sp-checkpoint-probe-step-50000-20260612T093809Z.json (c3fd769915df475f) |

Both probes: k=4 candidates/task, 100 tasks, greedy raw-text decode,
frozen probe set (sha 105fd3700b2f684b...). Battery context: the step-25k
seat shakedown emitted zero grammar-conforming lines (degenerate
repetition) — the core is MUTE at 0.1B, not "almost verbal."

## What the 1B INFO reading is FOR (and not for)

1. **Calibration toward the 2B floor decision** — the only protocol
   decision the 1B point informs. The floor bar (>=1.0 verified L1
   episode / governed-minute at 2B) does NOT move (fp-23 frozen;
   gate-discipline: tighten on failure, never relax).
2. **2B-probe preparation intensity** — harness readiness, k selection
   within the frozen <=16, probe scheduling against the 06-20..21 window.
3. **Honest reporting upward** — the user sees the reading with this
   frame, not a vibes summary composed after seeing the number.

It is NOT: a kill input (no KILL branch exists at 1B), a pass input, a
reason to touch the run, the bar, the corpus, or the curriculum mid-run,
nor a trigger for any unplanned intervention.

## Pre-registered reading bands (1B probe result, rate r = verified/governed-min)

- **Band A — r = 0 (still mute).** Reading: L1 onset has not begun by 1B.
  Consequence (all pre-existing protocol, nothing new): the 2B probe
  proceeds as scheduled; a 2B fail returns RETRY-AT-4B (fp-23), and the
  fp-29 synthesis-gate reconciliation governs the 4B leg. Pre-registered
  honesty: under Band A the 2B floor requires verbal onset AND verified-L1
  competence to emerge inside one doubling — possible (small-model onset
  is characteristically abrupt) but it is the THIN branch, and we say so
  in the report rather than discovering pessimism after the 2B fail.
  Band A changes preparation only: the 4B-leg logistics get pre-staged
  early (probe dispatch templates, prior-2B verdict plumbing already
  merged in fp-24b).
- **Band B — 0 < r < 1.0 (onset begun, below floor).** Reading: first
  nonzero point; one-point slope toward the floor is computable and goes
  in the report (tokens-to-floor extrapolation labeled as one-point,
  low-confidence). Consequence: none beyond schedule; floor decision
  stays entirely at 2B.
- **Band C — r >= 1.0 (at/above floor early).** Reading: ahead of
  protocol; floor at 2B is the expected outcome absent regression.
  Consequence: none — no early declaration of the 2B result; the 2B probe
  still runs (a regression between 1B and 2B is information the protocol
  is built to catch).

## Commitments (frozen with this doc)

1. No bar movement, no early termination, no run intervention follows
   from the 1B reading — the only consumers are the three uses above.
2. The 1B probe receipt must be produced by a COMMITTED harness
   (fp-24b guard, PR #321: harness_sha/protocol_sha must be real git
   shas or the verdict executor refuses the receipt).
3. The fp-36b execution (successor issue) quotes this doc's sha and
   names the band BEFORE any prose interpretation is written.
4. Post-freeze edits to this doc are fp-30b-class registered deviations;
   edits after the 1B receipt exists void the frame.

## Consistency guard

`scripts/fp36_consistency.py` — fail-closed: asserts the trajectory
table's numbers (tokens, verified, governed-min) byte-derive from the two
named receipts on disk, and that no `fp24-verdict-1B-*.json` exists yet
(frame frozen pre-data). Run it in the same PR that lands this doc and at
fp-36b execution time.
