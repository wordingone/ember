# HF custody sync (issue #1308)

Receipted, mirror-only sync of Workstream A's HF-custody inventory to the
`wordingone/ember-custody` Hugging Face dataset repo. Code lives under
`src/ember/data/hf_custody/`: `sync.py`, `receipts.py`, `pin.py`, `remint_hashes.py`.
Tests: `tests/test_hf_custody_sync.py`, `tests/test_remint_hashes.py`.

## 2026-08-02 root-cause note: the census hash was never content-based

The first live `--dry-run` against the real inventory refused all 8
`UPLOAD_ALLOWED` rows with `sha256_mismatch`. Root cause: the Workstream A
census's own `"sha256_filelist_manifest"` label named a **size-only,
content-blind** construction — it hashes relative paths and file sizes,
never a single byte of file content (`sync.compute_sizeonly_manifest`
reproduces it exactly; verified against rows 13 and 17's independently
recorded ingestion-receipt hashes, then against all 8 rows). Two
directories with identical file names and sizes but different content
would hash identically under that construction — it cannot be trusted as
an upload-integrity gate. `sync.compute_filelist_manifest` (hashes actual
file bytes) is the correct gate and is what this tool has always used for
verification; the census values were simply never comparable to it.

Resolution (operator ruling, `src/ember/data/hf_custody/remint_hashes.py`,
2026-08-02): every `UPLOAD_ALLOWED` row's `content_hash` in
`inventory-v1.jsonl` was re-minted from the size-only census value to
`compute_filelist_manifest`'s content-based value, ONLY after confirming
row-by-row that the OLD value really was produced by the size-only
construction (all 8 rows confirmed; see the remint receipt in
`state/hf-custody/remint-receipt-*.json`). The old size-only hash is
preserved on each row under `content_hash_sizeonly_census` — never
discarded, never trusted for integrity, kept for the historical record.
`hash_method` on these rows is now `sha256_content_manifest`
(`sync.SUPPORTED_HASH_METHOD`) rather than the old, now-ambiguous
`sha256_filelist_manifest` label, so the two constructions can never be
silently confused again. See each row's `hash_remint` note.

## Invariants (encoded in code, not just documented here)

- **Local files are authoritative.** Nothing in this package writes,
  deletes, or renames a byte under an inventory row's `local_canonical_path`.
- **Mirror-only.** The sync direction is always local -> hub. There is no
  code path that downloads hub content back onto disk or deletes local data.
- **Pinned-revision-only consumption.** A hub location is only ever safe to
  reference downstream (e.g. from a training job) as
  `hf://datasets/<repo>@<revision>`, where `<revision>` is always a real
  40-hex commit sha — never the unpinned/mutable `hf://datasets/<repo>` form,
  and never a commit URL or any other non-sha placeholder. This is enforced
  at THREE points, not just documented: `sync.upload_verified_row` hard-
  errors if `create_commit`'s returned `CommitInfo.oid` is missing or not a
  40-hex sha (no `commit_url` fallback); `receipts.append_receipt` refuses
  to write an `"uploaded"` receipt row whose `hf_revision` doesn't match
  `receipts.REVISION_RE`; and `pin.pinned_prefix` re-checks the same regex
  before emitting anything, in case a receipts file was ever written by
  something other than this package.
- **Withheld items are preserved, not dropped.** Rows whose `disposition`
  is `REQUIRES_OPERATOR_REVIEW`, `LOCAL_ONLY`, or `EXCLUDED` are always
  skipped, and the skip — with its reason — is written to the receipts
  stream exactly like an upload would be. A withheld row that never
  appears in the receipts is a bug, not a feature.
- **Deletion of a mirrored HF path is never automated.** There is no
  delete/remove call anywhere in this package. Removing something from the
  hub repo is a manual, deliberate, out-of-band operator action.
- **Fail-closed on unverifiable eligibility.** Before any upload, the whole
  run refuses to start if any `UPLOAD_ALLOWED` row is missing the fields
  needed to verify it (`content_hash`, `hash_method`, `hash_status`), or
  declares a `hash_method`/`hash_status` this tool can't verify against a
  freshly recomputed local manifest. See `sync.validate_eligible_rows_verifiable`.
- **Whole-run verification, two phases, never interleaved with uploads.**
  `sync.verify_all_eligible_rows` recomputes and checks EVERY eligible
  row's local per-file sha256 manifest against its declared `content_hash`,
  and checks the whole eligible set for `path_in_repo` basename collisions,
  BEFORE the first `create_commit` call of the run. If any row mismatches,
  is missing its directory, contains a refused symlink, or collides with
  another row's `path_in_repo`, the run raises `InventoryRefusal` and NO
  row is uploaded — not just the offending one. (Earlier revisions of this
  tool refused per-row and could upload rows 1..k before catching a bad
  row k+1; that behavior is gone.)
- **A refused symlink aborts verification.** `sync.compute_filelist_manifest`
  raises if it encounters a symlink anywhere in the walk; this always
  surfaces as a whole-run refusal (previous bullet), never a silent skip or
  a silent follow-and-hash.
- **Upload fileset is a subset of the verified fileset.** Verification
  hashes every file under a row's directory, including dotfiles and `.git*`
  paths (this keeps the verification set comparable to whatever produced
  the census's `content_hash`). `sync._build_commit_operations` additionally
  filters the row's data files through
  `filter_repo_objects(..., ignore_patterns=sync.UPLOAD_IGNORE_PATTERNS)`,
  which excludes dotfiles, `.git*` paths, AND (issue #1313 rework)
  `sync.HF_UPLOAD_FOLDER_DEFAULT_IGNORE_PATTERNS` — the
  `.git`+`.cache/huggingface` pattern family `huggingface_hub`'s own
  `upload_folder` always appended on top of any caller-supplied
  `ignore_patterns`. The old `upload_folder`-based implementation got that
  union for free; `create_commit` (the N1 fix's single-commit path) has no
  such implicit behavior, so `UPLOAD_IGNORE_PATTERNS` now unions the two
  explicitly — `test_hf_default_ignore_patterns_is_subset_of_installed_
  library` pins the inlined constant against whatever the installed
  `huggingface_hub` version actually enforces, so a future hub version
  widening its own denylist fails that test loudly instead of silently
  under-filtering. This matters for rows like the census's row 14
  (`ember-corpus-v1-lane-285`), an active git worktree whose `.git` pointer
  file contains an absolute local filesystem path that must never be
  published, and for any row containing a stray
  `.cache/huggingface/` directory from local tooling.
- **Row-scoped publication conditions via `publish_note`, one commit
  (issue #1313/N1).** An inventory row may carry an optional `publish_note`
  field. When present at `--execute` time, its text is uploaded as a
  `README.md` inside the row's `path_in_repo` — generated in memory, never
  written to the local directory — and the row's receipt records
  `readme_uploaded: true`. The README is one more `CommitOperationAdd` in
  the SAME `create_commit` call as the row's data files, not a second,
  trailing commit: a README failure now fails the row's whole commit
  instead of leaving previously-committed data published without its
  label, and a consumer resolving the row's pinned `hf_revision` always
  sees the README alongside the data whenever `readme_uploaded` is true.
  This is how a scoped ruling (e.g. "UPLOAD_ALLOWED but must carry a label
  stating X is not included") gets enforced by the tool instead of trusted
  to operator memory.
- **Receipts are appended per-outcome, immediately.** `sync.sync()` accepts
  an `on_outcome` callback invoked the instant each row's outcome is known
  — skips first, then each verified row's dry-run/upload/error outcome, in
  order. If an upload raises mid-loop (network failure, invalid revision,
  etc.), that row's `"error"` outcome is still passed to `on_outcome`
  before the exception propagates, so receipts for every row processed so
  far — including the failing one — are never lost. A whole-run refusal
  (`InventoryRefusal`, raised before the loop even starts) is receipted
  separately by `main()` as a single `status: "run_refused"` row.
- **Dry-run by default.** A real upload requires `--execute` (and not
  `--dry-run`). In dry-run, zero `huggingface_hub` calls are made — see
  `sync.upload_verified_row`'s `execute` branch.

## Known, accepted limitation: TOCTOU between verify and upload

`verify_all_eligible_rows` reads and hashes every eligible row's files, and
`create_commit` independently re-reads the same directory later in the same
process. For a mutable path (row 14 is an active git worktree), bytes could
in principle change in the window between verification and upload, producing
an `"uploaded"` receipt whose `manifest_sha256` no longer exactly describes
the uploaded bytes. This tool assumes a **single operator, single concurrent
run** — nothing else is expected to be writing into a row's
`local_canonical_path` while a sync is in flight. That assumption is
considered acceptable for this workstream and is not further hardened here
(e.g. no file locking); if the assumption stops holding, re-verifying
immediately before each row's upload would close the window.

## Running it

```
python -m ember.data.hf_custody.sync \
    --inventory <path-to-hf-custody-inventory>.jsonl \
    --repo-id wordingone/ember-custody \
    --receipts-path receipts/hf-custody/sync-<ts>.jsonl
    # dry-run: prints one JSON receipt line per row, uploads nothing

python -m ember.data.hf_custody.sync \
    --inventory <path-to-hf-custody-inventory>.jsonl \
    --repo-id wordingone/ember-custody \
    --execute \
    --receipts-path receipts/hf-custody/sync-<ts>.jsonl
    # real run: verifies EVERY eligible row first (whole-run fail-closed),
    # then uploads only if all of them pass

python -m ember.data.hf_custody.pin --receipts receipts/hf-custody/sync-<ts>.jsonl
    # prints hf://datasets/<repo>@<revision> for every completed upload
```

## Receipt schema

One JSON object per line, append-only (`src/ember/data/hf_custody/receipts.py`),
appended immediately as each row's outcome is produced:

| field | meaning |
|---|---|
| `ts` | UTC timestamp shared by the whole sync run |
| `inventory_row_id` | 1-based line number in the inventory JSONL (matches inventory-summary.md's "row N" references); `null` only for a run-level `run_refused` row |
| `local_path` | the row's `local_canonical_path` |
| `disposition` | the row's disposition as read from the inventory |
| `status` | `uploaded` \| `dry_run` \| `skipped` \| `error` \| `run_refused` |
| `reason` | set for every non-`uploaded` row; `null` on a completed upload |
| `files_count`, `bytes` | recomputed from the local directory, not trusted from the inventory row |
| `manifest_sha256` | freshly recomputed local combined sha256 (matches the inventory's `content_hash` on a verified row) |
| `hf_repo` | target dataset repo id, `null` for a skip |
| `hf_revision` | the created commit sha — this is the pin; ALWAYS either `null` or a 40-hex sha matching `receipts.REVISION_RE`, never a URL; only set when `status == "uploaded"` |
| `commit_message` | names the inventory row and manifest sha |
| `path_in_repo` | destination path inside the dataset repo |
| `readme_uploaded` | `true` iff a `publish_note` README.md was uploaded alongside this row's data |
| `sha_convention` | `"bytes on disk as-is (binary read, no line-ending normalization)"` |

## Eligibility verification

Only rows with `hash_method == sync.SUPPORTED_HASH_METHOD` (currently
`"sha256_content_manifest"`) and `hash_status == "complete"` can be
verified by this tool today (this is the same set of 8 rows the
Workstream A census marked `UPLOAD_ALLOWED` in `inventory-v1.jsonl` — rows
1, 3, 4, 5, 6, 13, 14, 17; see `inventory-summary.md` — all re-minted to
this hash_method on 2026-08-02). Rows hashed with
`sample_first_largest_newest_sha256` (the `deferred-bulk` rows:
courtlistener, corpus-cache, specialist-v2-65536) are never
`UPLOAD_ALLOWED` in the current inventory; if one ever were, this tool
would refuse the whole run rather than upload it unverified.

`sync.compute_filelist_manifest` follows a similar convention to
`scripts/manifest_sha.py` (sort by relative path, hash each file's bytes
as-is, combine into a single digest over sorted `"<relpath>\t<sha256>\t
<size_bytes>\n"` lines), but it is a distinct, independent implementation —
recursive and all-file rather than flat and `*.bin`-only. It is now
confirmed (2026-08-02) to be a genuinely DIFFERENT construction from the
census's original size-only hash, not merely an unverified guess at the
same one — see the root-cause note above. A mismatch always fails closed
(refuses the row/run).

## `sync.compute_sizeonly_manifest` — the census's original construction

Reproduces the Workstream A census's original `"sha256_filelist_manifest"`
construction exactly: `os.walk(root, followlinks=False)`, dotfiles/dotdirs
included with no exclusions, POSIX-style (forward-slash) relative paths,
sorted by plain Python ordinal string comparison, then a single
`hashlib.sha256()` object updated per file (in that sorted order) with
`relpath.encode("utf-8") + b"\x00" + str(size_bytes).encode("utf-8") +
b"\n"`. **This is a structure-only check, never an integrity check** — it
never reads a file's content, so two directories with identical file names
and sizes but different bytes hash identically under it. It exists ONLY
for historical verification (`remint_hashes.py` uses it to confirm a row's
old `content_hash` really was size-only before touching anything) and is
never used as this tool's actual upload-integrity gate — `sync_row`/
`verify_all_eligible_rows` only ever call `compute_filelist_manifest`.

## `remint_hashes.py` — one-time inventory hash re-mint (record of what ran)

```
python -m ember.data.hf_custody.remint_hashes \
    --inventory <path-to-hf-custody-inventory>.jsonl
    # dry preview: for every UPLOAD_ALLOWED row, confirms the size-only
    # recompute matches the existing content_hash, prints + writes a
    # remint receipt JSON, touches nothing on disk

python -m ember.data.hf_custody.remint_hashes \
    --inventory <path-to-hf-custody-inventory>.jsonl \
    --write
    # actually rewrites the inventory: on a size-only MATCH, moves the old
    # content_hash to content_hash_sizeonly_census, writes the new
    # content-based content_hash, sets hash_method to
    # sync.SUPPORTED_HASH_METHOD, adds a hash_remint note. On a size-only
    # MISMATCH, that row is left completely byte-for-byte unchanged and
    # reported — a mismatch means disk drifted since the census and needs
    # a fresh eligibility look, not a guess.
```

Non-`UPLOAD_ALLOWED` rows are never read or modified. Run against the real
`inventory-v1.jsonl` on 2026-08-02: all 8 eligible rows' size-only
recomputes matched their census values exactly (`rows_reminted: 8,
rows_skipped_no_match: 0`); every row was re-minted. See
`state/hf-custody/remint-receipt-*.json` for the full per-row record.

## Row 14 (`ember-corpus-v1-lane-285`) special case

The operator ruling for row 14 is `UPLOAD_ALLOWED`, scoped to the row's
actual on-disk index/manifest/pointer files (no bulk shard bytes live in
that directory), conditioned on publishing a README label stating that the
`code_github_clean` source referenced inside the manifests is
license-unverified and its bytes are NOT included. That condition is
implemented generically, not hardcoded to row 14: the inventory row carries
a `publish_note` field with exactly that text, and any row with a
`publish_note` gets the README treatment (see the invariants section
above). Row 14 is also a live git worktree, so its `.git` pointer file
(containing an absolute local path) is hashed for verification but excluded
from the actual upload by `UPLOAD_IGNORE_PATTERNS`.
