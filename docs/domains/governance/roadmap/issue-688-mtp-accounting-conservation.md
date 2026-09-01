# Issue #688 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical v0 MTP configuration and
sub-3B H-Q pilot vehicle. Current live MTP accounting belongs to EMBER-02
issue #1116; the preserved horizon-quality question and manifest binding also
remain linked to issue #722.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

## Authority and credit boundary

- `completion_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

Historical values `368354304`, `65536000` and `433890304` remain provenance,
not current 3B constants.

## Lossless accounting contract

The machine-readable fields remain named exactly `base_excluding_mtp`,
`mtp_aux`, and `realized`. Validation must enforce
`base_excluding_mtp + mtp_aux == realized` fail-closed. Every bare
`V0_CERTIFIED_PARAMS` consumer must be retired or replaced so launch, pricing
and H-Q consumers read only split and manifest-derived values.

The current owner must derive the split from the live model and optimizer by
emitting every unique trainable Parameter with all names/aliases, shape,
numel, dtype, Python object identity, underlying storage identity, optimizer
group, and exactly one owner in `{base, mtp_head_i}`. Count once by storage;
cross-owner sharing, orphan ownership, duplicate assignment, non-exhaustive
partition, or disagreement with config refuses. Bind the manifest SHA into
launch, governed actual-run pricing and H-Q receipts. Preserve shared-head,
compensating-trunk, orphan and independent-head fixtures.

## Existing #1514 boundary

Draft PR #1514 remains historical apparatus at head
`39ca211ac2c6461fd0ecf5d74f7a905224846b99`. Its checked configuration is
`artifact_class=historical_only` with `execution_authority=denied`. It has no
authorized actual-run pricing receipt and grants no completion, production,
training, GPU or capability credit. This ruling does not merge, revive or
silently transplant that draft.

## Lossless transfer

Canonical transfer URL placeholders:

- EMBER-02 / #1116: https://github.com/wordingone/ember/issues/1116#issuecomment-5224553272
- H-Q / #722: https://github.com/wordingone/ember/issues/722#issuecomment-5224553441

The historical sub-3B H-Q execution vehicle is prohibited. Its horizon
question, common accounting projection and manifest binding survive only on
an admissible current 3B-or-larger subject.

## Reopen and falsifier

Reopen if the accepted transfers omit the exact field names, arithmetic,
`V0_CERTIFIED_PARAMS` retirement, live unique-Parameter ownership/storage
proof, manifest consumer binding, actual governed-run pricing, fixtures, H-Q
link, or #1514 denial/no-run boundary. Declared totals, structural tests or a
candidate receipt cannot substitute for an externally governed real run.

`NO_NEW_PARALLEL_AUTHORITY`
