# Issue 1464 E8 Parity Plumbing Design

## Goal

Build the receipt and telemetry plumbing required to compare a certified A1
Tier-2 candidate with a fresh certified A1 Tier-1 reference over the frozen
T-09 100-step window, without changing either training mechanism or weakening
the existing R1-E8 validator.

## Authority and frozen constraints

- Public source starts at `8846f5981bc01ee1a661de5e9a518a86dec57ab3`.
- The corrected liveness receipt remains `FALLBACK_REQUIRED` and is an input,
  never recomputed by the parity producer.
- Candidate and reference use the same dense model identity, frozen data
  stream, genesis, seed, schedule, and 100 matched steps.
- `grad_norm` is measured before projection, optimizer update, clipping, or
  gradient release. Both tiers execute the same accumulator code.
- The existing `src/ember/governance/scripts/r1_e8_validator.py` remains the arithmetic authority.
  A producer may derive and serialize its expected values but may not redefine
  them.
- All output creation is no-overwrite and self-digested. Every referenced input
  is reopened and SHA-256 verified immediately before publication.

## Architecture

### Shared full-gradient norm measurement

`a1_optimizer.py` gains a small `FullGradientNormAccumulator` used by every
fused dense optimizer. A backward hook calls `accumulate(parameter.grad)` before
the optimizer reads, projects, updates, or clears the gradient. The accumulator
adds the FP32 sum of squares for each full parameter gradient in canonical
parameter-registration order. `finish_step()` returns the square root as a
finite Python float and resets the accumulator. It refuses an empty step, a
non-finite contribution, a second finish, or accumulation after finish.

Tier-1's existing fused hook adopts the accumulator without changing its AdamW
update. `run_dense_a1` reads the completed norm after `loss.backward()` and
`optimizer.step()`, then emits it in the existing `train_step` payload as a
12-decimal string. Tier-2 calls the same helper at the same point. Unused text
modality projectors contribute no gradient in either arm and therefore no norm
term.

### E7 dimensionless ratio sigma

The credited E7 receipt currently publishes `sigma_seed.grad_norm`, while the
frozen F-11 formula and validator require `sigma_seed.grad_norm_ratio`. A raw
field alias is forbidden because it would use a dimensionful norm tolerance for
a dimensionless ratio.

The replacement E7 v2 composition uses only the two already credited immutable
seed telemetry roots pinned by evidence v1. At
each matched step, it divides each seed's positive finite gradient norm by the
arithmetic mean of all seed gradient norms at that step. It then applies the
existing pooled population-variance method to those dimensionless normalized
values: population variance across seeds at each step, mean of the step
variances, square root. It is seed-order invariant. With the frozen T-07 value
of two seeds it equals `sqrt(mean_t(d(t)^2))`, where
`d=(g1-g2)/(g1+g2)`; near ratio one this is approximately `(r-1)/2`, making the
band about twice as tight as a literal per-step-ratio sigma. The receipt discloses
that conservative direction explicitly.

The receipt emits `loss` recomputed by the existing method,
`grad_norm_ratio` as the F-11 authority, and `grad_norm` retained for the record
with an explicit statement that the validator does not consume it. The
preregistration pin `3d48d3870919bd04cec735f68d0fad45fcfae0b2` and threshold
SHA `12c83ca9ac90f85d5e8c0ce2c8156ac0c2cf9695929b211971ee277582a5eeb5`
remain unchanged. The v2 receipt carries the complete `prereg` block
byte-identical to v1, including `document_pin` and `thresholds_sha256`, because
the parity validator reopens `e7.prereg.thresholds_sha256` rather than a
top-level alias. The old E7 receipt and evidence remain immutable and receive
the normal supersession custody note; the parity packet references only the new
v2 composition after separate adjudication. The validator is unchanged: an E7
receipt carrying only `loss` and `grad_norm` correctly refuses
`E7_SIGMA_MISSING`.

The reviewed estimator lives in a focused in-repository composer,
`src/ember/governance/scripts/r1_e7_ratio_sigma.py`. Its command accepts the immutable v1 evidence
path, v1 receipt path, two explicit telemetry paths, threshold authority, and a
clean output directory. It reopens all pins, derives the v2 metrics, and emits
both the v2 E7 receipt and a no-overwrite composition receipt containing input
raw hashes, output raw/self hashes, estimator identity, and the factor-two and
seed-order disclosures. Runtime custody keeps those two outputs together.

### Parity producer

A new focused module `src/ember/infrastructure/tools/ember-restart-3b/a1_e8_parity.py` publishes exactly
three files into a clean flat packet directory:

- `tier2-parity-series.json`
- `tier1-parity-series.json`
- `a1-e8-parity.json`

The producer accepts explicit paths for the candidate run receipt, reference run
receipt, both telemetry files and run IDs, corrected liveness receipt, threshold
authority, and green E7 receipt. It performs the same closed-schema run checks as
the validator, binds each series to the raw run-receipt SHA, selects exactly
contiguous steps 1 through 100, and serializes only `step`, `loss`, and
`grad_norm`. Duplicate, missing, non-finite, foreign-run, or post-window rows
refuse publication.

The receipt carries the exact fields already required by
`r1_e8_validator._validate_parity`: schema, threshold SHA, liveness SHA,
candidate/reference run references, candidate/reference series references, E7
reference, metrics, verdict, and self digest. Arithmetic uses `Decimal` and the
validator's 12-decimal serialization convention. The producer writes series
first and the top-level receipt last, each with exclusive creation and durable
flush. A partial packet is evidence-missing and is never resumptively
overwritten.

## Failure behavior

- No telemetry norm: refuse `PARITY_GRAD_NORM_MISSING`.
- Duplicate or non-contiguous step: refuse `PARITY_STEP_IDENTITY_INVALID`.
- Candidate/reference identity drift: refuse before any output is created.
- Live E7 lacks the ruled dimensionless key: refuse `E7_SIGMA_MISSING`.
- Existing output path: raise `FileExistsError`; custody must archive the whole
  partial namespace before a fresh mint.
- Computed out-of-band metrics are published honestly with verdict `FAIL`; they
  are not converted into a producer error.

## Testing

- Unit-test accumulator lifecycle, numeric value, unused parameters, and
  pre-update ordering.
- Extend fused/non-fused Tier-1 equivalence tests to prove the accumulator does
  not change parameter or optimizer bytes.
- Prove the real telemetry consumer reads the new `grad_norm` field.
- Add E7 ratio-sigma analytic fixtures with two seeds and known normalized
  variance, seed-order invariance, the disclosed two-seed identity, and
  zero-mean/non-finite refusals.
- Test the real `src/ember/governance/scripts/r1_e7_ratio_sigma.py` composer against v1-shaped
  fixtures, prereg-block byte identity, input/output hash bindings,
  composition-receipt closure, and no-overwrite behavior.
- Add producer success, exact arithmetic, no-overwrite, missing/duplicate step,
  identity mismatch, E7 mismatch, and honest `FAIL` tests.
- Replay `tests/domain-governance/test_r1_e8_validator.py` against the v2 E7 shape and assert that
  the old `{loss, grad_norm}`-only shape still refuses `E7_SIGMA_MISSING`.

## Publication and runtime sequence

This plumbing carrier merges before the Tier-2 mechanism carrier. After both
merge, the reference and candidate runs are executed serially under one-GPU
custody. The producer runs only after both terminal run receipts and telemetry
files are independently reopened. The frozen battery is then rerun and routed to
the independent gate owner for adjudication.
