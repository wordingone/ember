# Contract B0: Modded-NanoGPT Training-Efficiency Ruler

Status: DRAFT.

## Uncheatable Form

Build or run Ember training artifact `X` that beats external Modded-NanoGPT comparator `Y` on language-model train-to-validation-target metric `Z` by threshold `T`, preserving hardware/data/accounting/reproducibility constraints `C`, under one declared budget `B`, verified by parser/protocol `V`, producing PASS, FAIL, or INVALID-RUN.

## Fields

- Claim ID: `B0-MODNANO-TRAINING-EFFICIENCY-RULER`
- X: Ember governed training run, config and commit to be locked.
- Y: Modded-NanoGPT, source commit and exact record to be locked.
- Z: validation loss target, wall-clock, token count, and hardware-normalized accounting.
- T: not locked yet. Must be numeric before Ember runs.
- C: no hidden hosted compute, declared data, declared preprocessing, declared wall-clock inclusions, line-ending verifier pass, parser pass.
- B: one RTX 4090-class local budget for Ember unless same-hardware comparator reproduction is explicitly justified.
- V: `scripts/emit_verdict.py` plus protocol-specific metric parser.

## Current Verdict

INVALID-RUN if attempted now. Threshold and exact external record are not locked.
