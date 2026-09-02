<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Issue #1450 scratch reference/duplicate advisory scan v1

This is a second, separate read-only tool layered on top of
`tools/scratch_custody.py`'s census: `tools/scratch_reference_scan.py`. It
answers two of the census's open questions with real evidence instead of
`UNKNOWN`/`UNRESOLVED` placeholders, and it changes no authority: every
disposition row it feeds into `scratch_custody.py disposition` is still
`KEEP_UNRESOLVED`, and `identical_copy` still cannot express
"found a duplicate, therefore safe to delete" — that value does not exist in
the schema (see `scratch_custody.py`'s `_validate_annotation`), deliberately.

## What it computes

1. **`references`** — for each top-level `scratch/` entry, every tracked
   repository file whose text contains the entry's bare name (`name_hits`) or
   its literal `scratch/<name>` path (`path_hits`), unioned. Self-referential
   hits (the census/disposition/reference-scan receipts themselves, which by
   construction mention every entry name) are excluded so they cannot inflate
   the count.

2. **`duplicate-check`** — a whole-tree content hash (sorted relative path +
   bytes, streamed) for a caller-named pair, proving `PROVEN_IDENTICAL` or
   `PROVEN_DIFFERENT`.

## Why `references` is a floor, not a ceiling

`path_hits` (the precise `scratch/<name>` string) is not sufficient on its
own. `src/ember/governance/scripts/cpu_offload_adamw.py` builds its default optimizer-state
directory as `_REPO / "scratch" / "rung2-optstate"` — three separate path
segments joined at runtime — so the literal substring `scratch/rung2-optstate`
never appears in its source. Only `name_hits` (the bare directory name)
catches it. `rung2-optstate` is the single largest entry in the live census
(25.7 GiB); a scan that trusted `path_hits` alone, or that trusted an absence
of hits as proof of absence of a consumer, would have called it unreferenced
and wrong. Every entry this tool reports empty `references` for has had grep
find nothing — not had a human confirm nothing is there. Manual reading of
each `name_hits` file is still required before any entry is adjudicated.

## Live findings, 2026-08-12

Run against the live main working tree at commit
`1e843d23c02c6299e1286ba188a8129d7f2fc317` (the manifest this scan is bound
to is not committed — see below):

- **27 / 82** top-level entries have at least one tracked-repository
  reference (54.4 GiB of the 89.9 GiB census). **55 / 82** (35.5 GiB) show
  zero references from either signal — floor, not proof of safety, per above.
- `rung2-optstate` (25.7 GiB, the largest entry) is referenced by
  `src/ember/governance/scripts/cpu_offload_adamw.py`'s default optimizer-state path — a live,
  executable consumer, not a historical mention. This alone rules out moving
  it without either updating that script or re-pointing it at the new
  location first.
- `w1-control` (9.9 GiB) has 17 referencing tracked files; `corpus-cache`
  (15.8 GiB) has 2; `seed-export-v5` has 6. All require per-reference reading
  before any of them can be adjudicated, not just a reference count.
- The two same-size-class `screen792-*` directories the issue asked about
  are **not** duplicates: `screen792-quality-rerun-20260714T202752` (1,932
  files) and `screen792-live-20260714T2220Z` (1,931 files) — different file
  counts, different whole-tree SHA-256
  (`ccdb6bf1…362e5a` vs `5651fecd…10f822`). Recorded as `identical_copy:
  PROVEN_DIFFERENT` for both in the current disposition.
- Even the "zero references" 35.5 GiB is not yet a mover's list: this scan
  only sees tracked-repository text. A consumer external to this repository
  (a local script, a running process, an operator's own notes) would not
  appear here at all, and there is no way for a repository-scoped scan to
  rule that out.

## What this does not authorize

No byte moves, no disposition leaves `KEEP_UNRESOLVED`, no drive headroom is
reclaimed by this scan. Moving `scratch/`'s referenced ~54 GiB requires
reading each reference and either updating it to the new location or proving
it is historical-only; moving any of the unreferenced ~35 GiB still requires
the producer/issue-or-run identification the census schema already asks for
and this scan does not supply. Both remain open work.

## Reproduction

```text
python -B tools/scratch_custody.py census --root <repo-root> --output <manifest> --label <label> --max-bytes <cap> --max-files <cap>
python -B tools/scratch_reference_scan.py references --root <repo-root> --manifest <manifest> --output <references>
python -B tools/scratch_reference_scan.py duplicate-check --root <repo-root> --a <name> --b <name> [--output <receipt>]
```

The manifest this scan's live findings are bound to is not committed, matching
`issue-1450-scratch-custody-v1.md`'s existing convention (full per-file
inventories of `scratch/` stay in restricted/local custody; only the
top-level disposition and this scan's aggregate findings are tracked). The
disposition is: `receipts/issue-1450/live-scratch-disposition-v2-20260812.json`.
