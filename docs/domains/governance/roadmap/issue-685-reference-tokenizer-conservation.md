# Issue #685 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the unavailable historical Qwen-27B GGUF
tokenizer-extraction subject. Exact reference-tokenizer and benchmark identity
obligations are conserved by EMBER-11 issue #1125, with EMBER-02 issue #1116
retaining the frozen-reference evaluation boundary.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

## Authority and credit boundary

- `completion_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

No tokenizer, benchmark score or reference-model result is credited. An
unavailable exact GGUF remains an exact external blocker, never permission to
substitute another tokenizer or model.

## Lossless tokenizer and scoring contract

Preserve local-only extraction from the exact source GGUF, source SHA-256,
committed extraction code, HF-format tokenizer files and provenance sidecar;
no network fetch and no model-weight modification. Require full vocabulary and
special-token-ID identity, with BOS, `add_special_tokens` and normalization
flags frozen for both server and HF paths.

Differential evidence must use real ARC Challenge, HellaSwag and MMLU-Pro
context/continuation pairs plus leading-space, NFC/NFD, byte-fallback,
special-token and prefix-competition adversaries. For every pair, bind server
and HF context tokens, combined tokens, exact continuation offsets and masks.
Require a hand-computable end-to-end loglikelihood oracle comparing scored
positions and per-token log probabilities. A limit-five smoke must expose
lengths, masks, payloads and scores; merely passing the old assertion is not
acceptance.

## Lossless transfer

Canonical transfer URL placeholders:

- EMBER-11 / #1125: https://github.com/wordingone/ember/issues/1125#issuecomment-5224553042
- EMBER-02 / #1116: https://github.com/wordingone/ember/issues/1116#issuecomment-5224552859

## Reopen and falsifier

Reopen if the accepted transfer omits exact GGUF identity, local-only
extraction, full vocabulary/special IDs, frozen flags, actual-eval and
adversarial boundary corpus, offsets/masks, logprob oracle, payload disclosure,
or no-substitution rule. Any mismatch or unavailable exact subject refuses.

`NO_NEW_PARALLEL_AUTHORITY`
