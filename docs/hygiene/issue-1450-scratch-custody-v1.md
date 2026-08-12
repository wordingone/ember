<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Issue #1450 scratch custody census v1

This is a read-only, CPU/file-only boundary for the repository `scratch/`
surface.  It does not delete, move, rename, or rewrite any run output.  The
producer is `tools/scratch_custody.py`; its output contains only logical
relative paths, byte counts, SHA-256 digests, Git source identity, and a closed
policy projection.  Machine paths are execution inputs and are never written
to the manifest.

## Production command

From a clean checkout, choose a caller-owned output path outside `scratch/` and
run:

```text
python -B tools/scratch_custody.py census --root <repo-root> --output <manifest> --label issue-1450 --max-bytes <bounded-cap> --max-files <bounded-count>
python -B tools/scratch_custody.py guard --root <repo-root> --manifest <manifest>
python -B tools/scratch_custody.py disposition --manifest <manifest> --annotations <annotations> --output <disposition>
python -B tools/scratch_custody.py disposition-guard --manifest <manifest> --disposition <disposition>
```

`census` refuses symlinks/reparse points, path aliases, unreadable files,
unknown filesystem entry types, and byte/file caps before publishing a
manifest.  `guard` reopens the same root, requires a real Git source commit,
recomputes every file digest and summary, and refuses any changed, missing,
extra, duplicate, or malformed row.  An existing output is never overwritten.

The commit-level authority guard scans tracked bytes as before; untracked
`scratch/` run products are intentionally outside that commit scan and must be
covered by this separate custody guard before they are treated as evidence.
Tracked files under `scratch/` remain in the normal guard surface.

The cap is a safety bound for this census operation, not permission to remove
or relocate data.  The first run is therefore an inventory-only result: no
cleanup, data movement, acquisition, model, training, GPU, or result claim is
made.  Any later disposition must cite this manifest and a separately reviewed
deletion/annex plan.

`disposition` projects every `top_level` row into an exact set-equal custody
table.  Missing annotations become `producer=UNKNOWN`,
`issue_or_run=UNKNOWN`, `identical_copy=UNRESOLVED`, and an empty reference
list.  Supplied annotations have a closed schema and cannot name a path outside
the census. Manifest and disposition rows are admitted only in lexicographic
path order, and reference lists are canonical sorted unique arrays. Every
generated row is `KEEP_UNRESOLVED`; `disposition-guard`
reopens the manifest and refuses missing, duplicate, foreign, drifted, or
`MOVE_READY` rows.  The disposition therefore does not grant move or deletion
authority.  It records the unresolved work required before a separately
reviewed relocation or deletion proposal could be considered.
Every disposition also carries the repository receipt-floor fields:
`ticket=ISSUE-1450-SCRATCH-DISPOSITION`, a timezone-aware `ts`, the canonical
binary `sha_convention`, and the constitutional `invariant_sha256`.  These
fields are inside `disposition_sha256`; removing or altering one is therefore
both a receipt-floor failure and a disposition self-hash failure.
The public disposition also carries the scanned source commit, source-status
digest, and exact total file/byte counts; its manifest self-hash binds the
full raw inventory, which may remain in restricted custody when an exact deep
filename is prohibited by repository policy.

## Closed manifest fields

The exact top-level fields are `schema_version`, `authority`, `label`, `target`,
`source_commit`, `source_status_sha256`, `policy`, `entries`, `top_level`,
`summary`, and `manifest_sha256`.  `entries` is an exact relative-file
inventory; `top_level` is a deterministic per-directory projection; the
self-hash excludes only `manifest_sha256`.  `policy.read_only` and
`policy.reparse_refused` must both be true.

Both census and disposition documents bind exactly one `EMBER-02` /
`EMBER-02A` authority tuple and the live next-executed-outcome string.  A
missing, foreign, or altered authority tuple is refused before acceptance.

This boundary preserves the existing Ember Lab/repo-guard authority.  It adds
no cleanup daemon, launcher, receipt family, or parallel deletion authority.
