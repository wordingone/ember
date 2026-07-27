<!-- goal_id: EMBER-01 -->
<!-- workstream_id: EMBER-01B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Ember custody, benchmark, and issue census

This namespace inventories and classifies evidence. It does not select a
canonical tree, move or delete material, mutate issues, run a model or
benchmark, or create research progress.

## Paths and discovery

root-spec.json names logical roots. Machine paths are supplied at run time as
ROOT_ID=PATH bindings. Artifact rows use a logical root ID plus a relative
path. Registered worktree and discovered-root rows additionally retain a
normalized absolute path so a future local agent can reopen the exact surface.

Git repository scans record commit, every ref (including stash and pull refs),
bare/worktree kind, and dirty-state identity. git_ignored_registry hashes ignored
bytes. git_worktree_material_registry sequentially hashes the union of modified,
staged, untracked, and ignored files in every registered worktree.
directory_discovery applies frozen name patterns to one parent, records Git/bare
identities, and hashes non-Git material. Git object databases are never walked
as ordinary files.

## Hash algorithm and contradictions

Files use SHA-256 over the exact byte stream under algorithm
sha256-byte-stream-v1. File-tree order is ordinal POSIX-normalized relative-path
order. The optional tree digest hashes, for every entry, the eight-byte
big-endian path-byte length, UTF-8 path bytes, eight-byte big-endian file size,
and 32 raw file-digest bytes.

Duplicate groups require identical bytes, not names. Conflicting identities,
root aliases, missing roots, inaccessible entries, and scan failures remain
explicit contradictions. An inaccessible artifact has a null digest and does
not abort neighboring files.

## Resumable progress

--journal appends canonical JSONL progress. Large-file chunk progress has
state=partial, a byte offset, and no accepted SHA-256. Completed journal rows
are progress receipts only: every exact census re-hashes the current bytes,
checks pre/post file identity and size, and rejects mutation during hashing.
Truncated JSONL tails are ignored. Non-authoritative mtimes remain observable
receipt fields but are excluded from canonical byte identity. Git and directory
snapshots are rechecked after traversal; movement is an explicit contradiction,
never silently accepted as byte stability.

## Benchmark boundary

benchmark-registry.json freezes mandate/candidate/unresolved class, version,
split, harness path/content identity, data/license state, comparator boundary,
lineage admissibility, readiness, execution, subject, and completion
eligibility. Harness presence, downloaded data, synthetic tests, historical
sub-3B results, and borrowed-reference results never equal owned-model
completion. Completion requires exact owned checkpoint and result receipts at
the frozen official/comparable boundary.

## Public issue boundary

public-issue-census.json embeds the normalized raw live source snapshot and
binds every open issue body to exactly one of the eight durable dispositions.
Every row carries its recomputable record and compound-obligation hashes,
confidence, public-master blob/history evidence, and unresolved remainder.
Audited completed closures remain in a separately content-bound closed-outcome
snapshot instead of disappearing when the live open set changes. Open-state identity,
closed evidence-comment bytes, independently verified outcomes, and landed
implementation commits are content-bound and revalidated. Raw issue/comment prose is
stored as canonical Base64 so exact bytes survive without exposing executable-looking
operator-local paths; SHA-256 is always recomputed from the decoded UTF-8 bytes.

A closure proposal is invalid unless its commit is an ancestor of the bound
public master and its artifact, criterion, and verifier SHA-256 resolve through
immutable custody evidence, or one exact canonical issue preserves the complete
obligation hash. Age, inactivity, prose, labels, and mere commit/PR references
are never closure proof.

## Deterministic replay

From a clean checkout invoke:

    python -B scripts/ember_01_custody/census.py
      --root-spec manifests/ember-01-custody/root-spec.json
      --benchmark-registry manifests/ember-01-custody/benchmark-registry.json
      --issue-census manifests/ember-01-custody/public-issue-census.json
      --source-commit <40-hex-commit>
      --public-master-ref refs/remotes/origin/master
      --binding benchmark-root=<path>
      --binding local-execution-tree=<path>
      --output <receipt.json>
      --sidecar <receipt.sidecar.json>

Supply every required binding; roots with source_root_id use the source
repository binding. Exit zero means no validation error or contradiction. Exit
two means a canonical receipt was written with unresolved evidence. Exit one
means runtime failure and no completeness claim.

## Unified receipt

The output embeds the root/artifact census, complete benchmark registry,
complete public-issue census, validation arrays, source commit, and summary
counts for roots, artifacts, bytes, duplicates, access errors, contradictions,
benchmarks, and issues. canonical_manifest_sha256 binds the canonical
root-census JSON hash, benchmark-registry SHA-256, issue-census SHA-256, and
source commit. The bounded sidecar records the giant receipt byte hash, content-bound
execution ID, canonical identity, summary, validation state, and torn-snapshot contradictions.

After two unchanged runs, bind them without loading the giant JSON bodies:

    python -B scripts/ember_01_custody/compact_receipt.py
      --run-one-sidecar <run1.sidecar.json>
      --run-two-sidecar <run2.sidecar.json>
      --publication-sha <40-hex-sha>
      --output manifests/ember-01-custody/census-receipt.json

The compact checked receipt requires distinct execution IDs and full-receipt hashes,
identical canonical identities, an identical streaming raw-byte hash after replacing
only the execution IDs with a fixed sentinel, zero registry validation errors, and zero
torn-snapshot contradictions. It never replaces the underlying full rows.
