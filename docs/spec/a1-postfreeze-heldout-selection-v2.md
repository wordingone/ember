# A1 post-freeze held-out selection — non-discretionary beacon rule v2

**Status: FROZEN at authorship (ember #631 deliverable 4).** Supersedes the *mechanism*
of `a1-postfreeze-heldout-selection-v1.md`. v1's selection function was reproducible but
**grindable**: it used the author-controlled commit sha (`eval_freeze_hash`) as the
selection beacon, so an author could vary an inert commit-message nonce until the modulo
landed on any candidate (refs #123 finding 4; reproduced in
`receipts/eval-suite-freeze/a1-beacon-grindability-repro-*.json`: all 8 indices reachable
in ~20 tries, index 7 = SciQ reachable). v2 freezes the pool/rule **first** and consumes an
**independent, author-uncontrollable, externally-verifiable beacon that does not exist until
after the freeze**.

## The pool (unchanged from v1 — re-picking the pool would itself be discretionary)

| index | dataset | canonical source | split |
|-------|---------|------------------|-------|
| 0 | WinoGrande (winogrande_xl) | `allenai/winogrande` | validation |
| 1 | PIQA | `ybisk/piqa` | validation |
| 2 | OpenBookQA (main) | `allenai/openbookqa` | test |
| 3 | BoolQ | `google/boolq` | validation |
| 4 | CommonsenseQA | `tau/commonsense_qa` | validation |
| 5 | LAMBADA (standard) | `EleutherAI/lambada_openai` | test |
| 6 | TruthfulQA (multiple_choice) | `truthfulqa/truthful_qa` | validation |
| 7 | SciQ | `allenai/sciq` | test |

All eight remain public, consent-gate-free, locally runnable, and verified absent from every
tracked receipt at authorship (never-before-run).

## The beacon (independent, post-freeze, author-uncontrollable)

- **Source**: the NIST Randomness Beacon v2 (`https://beacon.nist.gov/beacon/2.0/`), a signed,
  hash-chained public randomness service. (drand / League of Entropy is an accepted equivalent
  if NIST is unavailable; the source is fixed at authorship, not chosen after the value is seen.)
- **Pulse selector `T`**: the **first beacon pulse whose `timeStamp` is strictly greater than
  the committer timestamp of the commit that merges this spec to `master`**. The merge time is
  set by the coordinator/GitHub at merge, not by the authoring lane; the pulse after it does not
  exist until then and cannot be forged (the beacon chain is signed). `B` = that pulse's
  `outputValue` (512-bit hex).

## The selection function (one line, no tunable parameter)

```
index = int(B[:8], 16) mod 8
```

with the same **never-before-run collision handling** as v1: if the selected candidate is ever
found cited pre-freeze by the quarantine pass, the selection moves to `(index + 1) mod 8`,
repeating deterministically until a never-before-run candidate is reached.

## Why this is non-grindable (the property v1 lacked)

The pool, the selection function, the beacon source, and the pulse selector `T` are all frozen
in **this** PR — **before** the beacon value `B` exists (`T` postdates the merge, which postdates
this authorship). The author cannot compute, choose, or influence a signed NIST pulse. Anyone can
independently fetch the pulse at `T` and recompute the index. Non-discretion is therefore proven
**by construction**, not asserted. (Same commitment class as hash-committed placement generators,
refs #582 O4 — but with an *external* beacon instead of a self-authored commit sha.)

## Resolution status and the v1 record

Resolution is **PENDING** the pulse at `T` (the beacon value cannot exist in-PR by design). The
selected dataset is a development-signal-only held-out addition until pinned into suite **v2**
(the freeze doc's versioning law: a frozen suite is never appended to).

**v1 record (`ccde4a67 → index 7 → SciQ`)**: the landed v1 declaration + amendment carry an
`ac4_anchoring` clause stating the selection "binds once, at first derivation, dated" and "an
amendment NEVER re-rolls AC4." Those landed artifacts are **byte-law immutable and are not
re-rolled here.** This v2 spec does not edit them; it installs the non-grindable beacon as the
authority for the held-out selection that will be pinned into suite v2, and marks the v1
commit-sha derivation **grindable-mechanism, superseded-for-clearance**. Whether the v1 SciQ pick
is grandfathered (it was never consumed by a capability claim) or replaced by the v2 pulse result
is a **coordinator ruling** — this lane surfaces the conflict rather than deciding it (refs #631
"STOP that point and report the exact conflict" for hash-pinned-artifact conflicts).
