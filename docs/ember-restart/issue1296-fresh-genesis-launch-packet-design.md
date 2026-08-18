# Issue 1296 Fresh-Genesis Launch Packet Design

## Claim boundary

This change builds and validates a CPU-only `READY_FOR_COMPUTE` packet for the
R1 WARM-100 entry. It does not launch training, produce a checkpoint, evaluate
a model, or claim an R1 exit. The packet keeps the existing
`scripts/ember_restart/contract.py` R1-entry validator and
`tools/ember-restart-3b/certified_train_launch.py` consumer authoritative.

## Inputs and authorities

The builder consumes:

- a source-bound `ember-r1-warm100-entry-v2` receipt and its governed rung
  manifest;
- an externally minted certified declaration, declaration ledger, and exact
  source-binding map;
- the current text-lab authority index and every file it transitively binds;
- a repository-contained `TOKEN-SHARDS-V0` receipt, external shard root, and
  canonical tokenizer;
- run-scoped custody and artifact roots.

The R1 entry is reopened by `validate_r1_warm100_entry`. The text authority is
reopened by `text_lab_corpus.validate_authority_index` and must return
`VERIFIED`; partial corpus admission remains a refusal. The generated run spec
is reopened by `validate_certified_request`, and the executable argv is
obtained only from `build_runner_argv`.

## Packet construction

The builder stages a canonical five-file external launch-authority packet
under the authorized custody root. It copies the already-minted certificate,
ledger, and binding map; writes one semantic-canary run spec fixed to seed 83,
100 optimizer steps, `warm-100`, no resume keys, and telemetry under custody;
then writes the custody receipt using the certified consumer's closed filename
and key constants. The certified consumer reopens the staged packet with its
prepublication destination check and derives the runner argv.

After validation, the builder writes a separate self-hashed manifest beside
the packet. That manifest binds the R1 entry, the validated text authority
receipt, the certificate and generated run spec, the CLI-to-Lab command argv,
and immutable source blobs for each R1 exit E1 through E8. The staging
directory is atomically promoted to `<custody>/<run-id>` only after every
check passes.

## Failure behavior

The builder refuses non-PREP entry receipts, non-VERIFIED text authority,
resume-bearing templates, paths outside the declared custody root, an existing
destination, and any certified-consumer refusal. Failed staging directories
are removed. No subprocess that can train is spawned.

## Tests

Tests create a hermetic certified-launch bundle and a fully admitted text
authority fixture. The positive test builds the packet and runs the real
`validate_certified_request` and `build_runner_argv` downstream consumers over
the emitted bytes. Negative tests cover authority tampering, widened R1 claim
boundaries, telemetry escaping custody, and resume-key injection.
