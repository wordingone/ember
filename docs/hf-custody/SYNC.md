# HF custody sync (issue #1308)

Receipted, mirror-only sync of Workstream A's HF-custody inventory to the
`wordingone/ember-custody` Hugging Face dataset repo. Code lives under
`scripts/hf_custody/`: `sync.py`, `receipts.py`, `pin.py`. Tests:
`tests/test_hf_custody_sync.py`.

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
  errors if `upload_folder`'s returned `CommitInfo.oid` is missing or not a
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
  BEFORE the first `upload_folder` call of the run. If any row mismatches,
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
  the census's `content_hash`). The actual `upload_folder` call additionally
  passes `ignore_patterns=sync.UPLOAD_IGNORE_PATTERNS`, which excludes
  dotfiles and `.git*` paths from what's actually published — this matters
  for rows like the census's row 14 (`ember-corpus-v1-lane-285`), an active
  git worktree whose `.git` pointer file contains an absolute local
  filesystem path that must never be published.
- **Row-scoped publication conditions via `publish_note`.** An inventory
  row may carry an optional `publish_note` field. When present at
  `--execute` time, its text is uploaded as a `README.md` inside the row's
  `path_in_repo` — generated in memory, never written to the local
  directory — and the row's receipt records `readme_uploaded: true`. This
  is how a scoped ruling (e.g. "UPLOAD_ALLOWED but must carry a label
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
`upload_folder` independently re-reads the same directory later in the same
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
python -m scripts.hf_custody.sync \
    --inventory <path-to-hf-custody-inventory>.jsonl \
    --repo-id wordingone/ember-custody \
    --receipts-path receipts/hf-custody/sync-<ts>.jsonl
    # dry-run: prints one JSON receipt line per row, uploads nothing

python -m scripts.hf_custody.sync \
    --inventory <path-to-hf-custody-inventory>.jsonl \
    --repo-id wordingone/ember-custody \
    --execute \
    --receipts-path receipts/hf-custody/sync-<ts>.jsonl
    # real run: verifies EVERY eligible row first (whole-run fail-closed),
    # then uploads only if all of them pass

python -m scripts.hf_custody.pin --receipts receipts/hf-custody/sync-<ts>.jsonl
    # prints hf://datasets/<repo>@<revision> for every completed upload
```

## Receipt schema

One JSON object per line, append-only (`scripts/hf_custody/receipts.py`),
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

Only rows with `hash_method == "sha256_filelist_manifest"` and
`hash_status == "complete"` can be verified by this tool today (this is the
same set of 8 rows the Workstream A census marked `UPLOAD_ALLOWED` in
`inventory-v1.jsonl` as of 2026-08-02 — rows 1, 3, 4, 5, 6, 13, 14, 17; see
`inventory-summary.md`). Rows hashed with `sample_first_largest_newest_sha256`
(the `deferred-bulk` rows: courtlistener, corpus-cache, specialist-v2-65536)
are never `UPLOAD_ALLOWED` in the current inventory; if one ever were, this
tool would refuse the whole run rather than upload it unverified.

`sync.compute_filelist_manifest` follows a similar convention to
`scripts/manifest_sha.py` (sort by relative path, hash each file's bytes
as-is, combine into a single digest over sorted `"<relpath>\t<sha256>\t
<size_bytes>\n"` lines), but it is a distinct, independent implementation —
recursive and all-file rather than flat and `*.bin`-only. Whether it is
byte-for-byte comparable to whatever tool actually produced a given
inventory row's `content_hash` is not verified from this repo. A mismatch
always fails closed (refuses the row/run), so any algorithmic drift is safe
in that direction, but a false-positive refusal on an otherwise-good row is
possible in principle and would need investigating against the original
census tooling rather than worked around here.

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
