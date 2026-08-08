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

## Closed manifest fields

The exact top-level fields are `schema_version`, `label`, `target`,
`source_commit`, `source_status_sha256`, `policy`, `entries`, `top_level`,
`summary`, and `manifest_sha256`.  `entries` is an exact relative-file
inventory; `top_level` is a deterministic per-directory projection; the
self-hash excludes only `manifest_sha256`.  `policy.read_only` and
`policy.reparse_refused` must both be true.

This boundary preserves the existing Ember Lab/repo-guard authority.  It adds
no cleanup daemon, launcher, receipt family, or parallel deletion authority.
