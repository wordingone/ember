# Board canonicality v1 (R3, ember01plan F4/F5/F6/A3)

2026-07-22. This document is the full rule text for the canonical
totality-board receipt, its append-only adjudication index, duplicate-epoch
detection, and mechanical freshness -- the machinery
`scripts/ember_totality/board_index.py` implements and `scripts/gen_readme_status.py`
and `scripts/ember_totality/ember_totality_spec.py` wire into. Frozen spec:
`fspec-R3-1436-20260722T213546Z`. Not SHA-pinned in GOAL.md's
`conservation_hashes.governing_surfaces_sha256` -- it is a process/tooling
spec, not a completion-bar surface.

## 0. The fracture this closes

Twin 2026-07-11 board receipts, ~18 minutes apart, different counts,
different locations:

- `ember-totality-20260711T102112Z.json` in
  `scripts/ember_totality/receipts-totality/` (11-GREEN / 29.7%) -- cited by
  README.md's board block.
- `ember-totality-20260711T103912Z.json` tracked only at `receipts/`
  (12-GREEN / 32.4%) -- NOT what README cited, but load-bearing for C-FED
  GREEN (the `rows[C-FED].reason` of at least one receipt cites this exact
  path as federation-design evidence).

`scripts/gen_readme_status.py`'s old selection rule, "newest lexicographic
filename in one glob'd directory", is location-blind (it never looked at
`receipts/`), index-blind (no record of which receipt is the adjudicated
one), and freshness-blind (no way to say a cited receipt predates the tree it
describes). That selection rule IS the fracture mechanism.

## 1. Canonical directory decision (frozen, do not revisit)

**Canonical = `scripts/ember_totality/receipts-totality/`.** It is already
the runner's only write target (`ember_totality_spec.py`'s `RECEIPTS_DIR`),
already excluded from custody/working-set scans, and already the
chain-verify domain (`receipt_chain_verify.py`, issue #467). Every other
tracked location -- `receipts/`, `receipts-parity/`, and anything else that
turns up -- is NONCANONICAL for board receipts: classified, kept, never
current, never deleted.

## 1a. Authority-conservation location exception (C-prime, fadv-1912)

The board-of-record for the 2026-07-11 epoch is the historical
`receipts/ember-totality-20260711T103912Z.json` (12-GREEN), a
pre-EMBER-02-binding measurement tracked at `receipts/` with
`goal_id=None`. Copying its bytes into the canonical directory would make
it a CHANGED artifact under `verify_authority_conservation.py` leg-4
(`check_changed_artifact_bindings`), which then requires
`goal_id='EMBER-02'` + the EMBER-02 `next_executed_outcome` on it -- a
binding a historical measurement cannot truthfully carry, and adding it
would also break byte-identity with the C-FED evidence original. So NO
copy is made.

Resolution (C-prime): the board-of-record is indexed as a `board` row IN
PLACE at its `receipts/` path. The EMBER-02 authority binding rides the
`BOARD-INDEX.jsonl` row (validated by leg-4's added-line `.jsonl` branch,
each added line satisfying `valid_binding`), never the receipt bytes.
Consequently `current_board()` intentionally applies NO directory filter:
it returns the newest non-superseded `board` row regardless of
`location_class`. The canonical directory of section 1 remains the
runner's write target for FUTURE bound board receipts; this exception is
self-extinguishing -- the first post-A fresh run writes a bound canonical
receipt whose `board` row supersedes this in-place historical one. This
section overrides the copy-based phrasing where sections 1, 3 (D1), and 6
assume a canonical-dir copy.

## 2. Index schema -- `scripts/ember_totality/receipts-totality/BOARD-INDEX.jsonl`

Append-only, LF-only, UTF-8, one JSON object per line; existing lines are
never edited or reordered -- a wrong row is corrected by a later row (the
repo's errata convention). Three row types:

```json
{"row_type":"board","ts":"<YYYYMMDDTHHMMSSZ>","path":"scripts/ember_totality/receipts-totality/ember-totality-<ts>.json","sha256":"<hex64>","indexed_ts":"<ISO8601Z>","basis":{"governing_commit":"<sha|UNKNOWN>","goal_sha256":"<hex|UNKNOWN>","conditions_spec_sha256":"<hex|UNKNOWN>","probe_set_sha256":"<hex|UNKNOWN>","receipts_head_commit":"<sha|UNKNOWN>","subject_identity_sha256":null,"subject_identity_source":"PRE-A1: no current-subject surface landed (R2)"},"summary":{"green":11,"red":24,"unevaluable":2,"pct_green":29.7}}
{"row_type":"noncanonical","ts":"<ts>","path":"receipts/ember-totality-<ts>.json","sha256":"<hex64>","indexed_ts":"<ISO8601Z>","location_class":"receipts|receipts-parity|other","kept_because":"<free text>","byte_twin_of":"<canonical path or null>"}
{"row_type":"supersession","old":{"path":"...","sha256":"<hex64>"},"new":{"path":"...","sha256":"<hex64>"},"reason":"<free text>","ts":"<ISO8601Z>","authority":"<ruling source>"}
```

Backfill is idempotent, keyed on `(row_type, path, sha256)` -- re-running
appends nothing already present. Historical receipts predating the index get
`basis` fields stamped `"UNKNOWN"` -- they can never be FRESH (there is no
live basis to compare a pre-index receipt against). Only git-TRACKED files
may appear as `board` or `noncanonical` rows (the #535 tracked-at-HEAD
principle, `c_custody_twin_resolution_test.py`); untracked on-disk files are
reported by `classify` as `UNLANDED` but never written to the index.

## 3. Duplicate-epoch rules (D1/D2/D3)

`board_index.duplicate_epochs(index)` returns RED findings, three frozen
rules:

- **D1** -- same basename tracked in more than one location, byte-identical
  -> NOT red; requires a `noncanonical` row with `byte_twin_of` set
  (location-twin, adjudicated by classification). D1 covers any FUTURE
  byte-twin created in the canonical dir; the 2026-07-11 board-of-record
  makes no such twin -- it is referenced in place per section 1a.
- **D2** -- same basename, differing sha256 across locations -> RED unless a
  `supersession` row covers the pair.
- **D3** -- two `board` rows whose complete basis dicts are equal and
  non-UNKNOWN (a re-run with nothing changed, i.e. one board epoch
  re-executed) -> RED unless a `supersession` row names the survivor.
  Historical (pre-index, all-UNKNOWN-basis) rows are excluded from D3 by
  construction -- an UNKNOWN basis can never equal another UNKNOWN basis for
  this rule's purposes.

`board_index.current_board(index)` -- the newest-ts `board` row not on the
`old` side of any supersession row -- is fail-closed: it raises
`BoardIndexError` if `duplicate_epochs` is non-empty or the index is
missing/empty. `gen_readme_status.py` never catches this to fall back to the
old newest-glob rule; it surfaces the exact finding as a `SystemExit`.

### The one pre-ruled 2026-07-11 twin adjudication

Encoded in `board_index.py` (`_PRE_RULED_SUPERSESSION_*` constants) and
appended by `backfill`, not decided by the builder or any later reader: the
2026-07-11 twin is a same-morning re-run 18 minutes apart; `...103912Z` is
the board-of-record (the newer, more-complete run); `...102112Z` remained
README-cited only because the old selection was location-blind. Both
receipts are preserved unmodified -- nothing about this adjudication deletes,
renames, or edits either file.

## 4. Freshness basis and the four triggers

`board_index.collect_basis(repo_root)` snapshots five fields NOW:
`governing_commit` (`git rev-parse HEAD`), `goal_sha256` (GOAL.md bytes),
`conditions_spec_sha256` (docs/spec/conditions-v1.md bytes),
`probe_set_sha256` (sha256 over every git-tracked `*.py` directly under
`scripts/ember_totality/`), `receipts_head_commit` (`git log -1 --format=%H
-- receipts/`), plus `subject_identity_sha256`/`subject_identity_source`
(disarmed, see section 5).

`board_index.freshness(row, repo_root)` compares a board row's stored basis
against a live `collect_basis(repo_root)` call and maps onto four named
freshness triggers from the board-completion plan:

| Trigger | Basis field(s) |
|---|---|
| condition code | `probe_set_sha256`, `conditions_spec_sha256` |
| governing hashes | `goal_sha256` |
| subject identity | `subject_identity_sha256` (compared only when both sides are non-null) |
| evidence-index head | `receipts_head_commit` |

`governing_commit` itself is NOT a freshness trigger (an unrelated commit
elsewhere in the tree must not spuriously mark a board STALE) -- it is
carried in the basis purely for the README's Binding line. Any `UNKNOWN` in
the row's own basis forces `STALE` with `changed=["basis:UNKNOWN_PRE_INDEX"]`
-- a historical, pre-index board can never read FRESH, which is the honest
answer until a fresh board run happens under the live index (section 6).

## 5. Subject-identity trigger: disarmed-with-disclosure

`board_index.SUBJECT_IDENTITY_PATHS = []` until the R2 current-subject
artifact lands (see the A1/A2 boundary, `fspec-R3-1436` section 9). Every
basis snapshot carries `subject_identity_sha256: null` and
`subject_identity_source: "PRE-A1: no current-subject surface landed (R2)"` -- this is a disclosed absence, not a silently-skipped check. When
the R2 machine-readable current-subject block lands, adding its
repo-relative path to `SUBJECT_IDENTITY_PATHS` is the one-line integration;
no other change to `board_index.py` is required.

## 6. Classify-without-deletion (absolute)

No code path in `board_index.py` ever deletes, moves, renames, or rewrites a
tracked receipt. `classify(repo_root)` only reads (`git ls-files` + file
hashes); `backfill` only appends to `BOARD-INDEX.jsonl`. The
`receipts/ember-totality-20260711T103912Z.json` C-FED evidence file, in
particular, stays exactly where it is, forever -- `classify` reports it as a
kept, load-bearing `board` row referenced in place (section 1a), never a deletion candidate.

## 7. Re-arm rule and the A1/A2 dependency boundary

The fresh board run under the live index is NOT part of the R3 build -- per
the board-completion plan, a fresh run happens only after the A-items land,
re-armed per tier boundary thereafter (section 11d of the plan). R3 lands the
infrastructure; README honestly renders the historical board-of-record marked
STALE until that post-A fresh run.

Never touched by `board_index.py` or its callers: `CONTINUITY.md` (the R1
workstream), GOAL.md's authority/goal/boundary objects (only the two
`conservation_hashes` entries for README.md and conditions-v1.md change, and
only because those two files' bytes changed), any current-subject/
checkpoint-identity machinery (the R2 workstream), `docs/receipt-supersessions.jsonl`,
and C-INV/C-CUSTODY probe logic. `docs/receipt-supersessions.jsonl`'s
supersession machinery is STAMP-COVERAGE accounting for C-INV
(laundering-guarded, issue #625) -- semantically distinct from board-of-record
adjudication; the two are never merged or cross-read.
