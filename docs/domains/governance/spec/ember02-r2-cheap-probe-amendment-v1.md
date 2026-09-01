# EMBER-02 R2 cheap-probe authority amendment v1

**Issue:** #1442  
**Decision ID:** D-03  
**Form:** `deferred_amendment`

This append-only amendment extends, but does not rewrite,
`ember02-preregistration-v1.md` and
`ember02-preregistration-thresholds-v1.json`. The older files describe a
"frozen cheap-probe battery", but no accepted manifest enumerates even one
probe. Therefore R2-E3, R2-E4, and F-03 are explicitly deferred.

## Current executable authority

`src/ember/governance/scripts/r2_cheap_probe_battery.py` remains the executable consumer. Its empty
registry and `BATTERY_UNDEFINED` refusal are the only truthful current result.
That refusal grants no R2 advancement credit and no R3 funding. It is not a
failed model result and it does not establish capability, training, or
scientific-completion credit.

For future proportion probes, this amendment ratifies the runner's one-sided Wilson
score lower bound at T-24 confidence (0.95), without continuity
correction. A probe passes only when `lower_bound > chance_rate`. This settles
the statistical-method ambiguity without inventing a battery or scorer.

## Settlement gate

A later accepted superseding amendment must land before R2 dispatch and must:

- freeze a nonempty manifest containing at least one probe;
- bind the manifest bytes and custody identity;
- bind an executable scorer for every probe type;
- preserve the T-24 Wilson predicate for proportion probes or explicitly
  tighten it under the preregistration change-control law; and
- pass the existing runner's manifest, checkpoint, refusal, and receipt tests.

Until every item is satisfied, R2-E3, R2-E4, and F-03 remain unexecutable gates,
and the runner must continue to refuse rather than infer, skip, or substitute
probe evidence.

## Rollback and claim boundary

Revert this amendment and its contract test together. The pre-existing
`BATTERY_UNDEFINED` refusal remains authoritative after rollback unless another
accepted superseding amendment is merged. This document defines no probes and
claims no model, checkpoint, GPU, training, capability, or result evidence.
