# Historical v0 MTP parameter accounting and mechanism identity

Status: authoritative erratum for the historical, execution-denied
`configs/v0-pretrain-config.json` surface.

This record resolves issue #679's declaration and identity ambiguity. It does
not provide live storage-deduplicated ownership proof, an actual-run pricing
receipt, an MTP quality result, or authority to train the historical v0
configuration.

## Parameter partition

The historical c03 base count excludes MTP:

| Partition | Parameters | Derivation |
|---|---:|---|
| base excluding MTP | 368,354,304 | fp19/c03 base count with `n_mtp=0` |
| two MTP auxiliary heads | 65,536,000 | `2 * 1024 * 32,000` |
| realized declared total | 433,890,304 | base plus MTP auxiliary heads |

The machine-readable source is
`model.parameter_accounting` in `configs/v0-pretrain-config.json`.
`src/ember/governance/scripts/v0_config_check.py` rejects a wrong base, a head count/dimension
mismatch, an arithmetic mismatch, or a wrong mechanism identity.

This is declaration-level accounting. Issue #688 remains open for the live
unique-Parameter/storage-identity partition, exact ownership proof, and
actual-run pricing receipt. No declaration in this erratum substitutes for
that evidence.

## Implemented mechanism

The historical v0 runner constructs:

- one shared hidden state from the decoder trunk; and
- two independent `Linear(hidden=1024, vocab=32000, bias=False)` projection
  heads.

It does not implement a sequential state transition between MTP depths. It is
not equivalent to DeepSeek-V3 sequential MTP, and it is not a speculative
decode drafter. Those are separate mechanism candidates and cannot receive
credit from this implementation.

The machine-readable identity is
`objective.mtp_aux_heads.mechanism_identity` in the config. The production
builder is `scripts/timeshare_pretrain.py::build_v0_model`.

## Claim and execution boundary

Disposition:
`HISTORICAL_UNSCREENED_INDEPENDENT_AUXILIARY_HEADS`.

Therefore:

- the component receives no DeepSeek-MTP or drafter credit;
- the component receives no quality, data-efficiency, activation-cost, or
  production-gap credit without a matched experiment;
- the historical v0 config remains `execution_authority=denied`;
- the current H-Q experiment remains issue #722; and
- the live ownership/pricing closure remains issue #688.

## Consumer crosswalk

| Consumer class | Binding after this erratum |
|---|---|
| config | explicit base, MTP auxiliary, and realized fields |
| config validator | exact values, formula, arithmetic, and identity enforced |
| launch budget | realized total, never the old bare base-only constant |
| accounting harness | base count remains valid only when `n_mtp=0`; heads are added explicitly |
| historical receipts | immutable; interpret 368,354,304 as base excluding MTP |
| human-facing v0 docs | label base-only and realized totals distinctly |
| DeepSeek/drafter references | external comparator or future candidate only |

Rollback is the ordinary revert of the merge commit carrying this erratum.
