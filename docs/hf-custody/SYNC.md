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
  `hf://datasets/<repo>@<revision>` — never the unpinned/mutable
  `hf://datasets/<repo>` form. `pin.py` refuses to emit anything else; see
  its module docstring.
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
- **Per-row sha verification before upload.** For each eligible row, the
  local directory's per-file sha256 manifest is recomputed
  (`sync.compute_filelist_manifest`, same algorithm as `scripts/manifest_sha.py`)
  and compared against the row's own `content_hash`. A mismatch refuses
  *that row* (recorded as `status: "refused"`) without aborting the rest
  of the run.
- **Dry-run by default.** A real upload requires `--execute` (and not
  `--dry-run`). In dry-run, zero `huggingface_hub` calls are made — see
  `sync.sync_row`'s `execute` branch.

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
    # real run: uploads only UPLOAD_ALLOWED rows whose local manifest matches

python -m scripts.hf_custody.pin --receipts receipts/hf-custody/sync-<ts>.jsonl
    # prints hf://datasets/<repo>@<revision> for every completed upload
```

## Receipt schema

One JSON object per line, append-only (`scripts/hf_custody/receipts.py`):

| field | meaning |
|---|---|
| `ts` | UTC timestamp shared by the whole sync run |
| `inventory_row_id` | 1-based line number in the inventory JSONL (matches inventory-summary.md's "row N" references) |
| `local_path` | the row's `local_canonical_path` |
| `disposition` | the row's disposition as read from the inventory |
| `status` | `uploaded` \| `dry_run` \| `skipped` \| `refused` |
| `reason` | set for every non-`uploaded` row; `null` on a completed upload |
| `files_count`, `bytes` | recomputed from the local directory, not trusted from the inventory row |
| `manifest_sha256` | freshly recomputed local combined sha256 (matches the inventory's `content_hash` on a verified row) |
| `hf_repo` | target dataset repo id, `null` for a skip |
| `hf_revision` | the created commit sha — this is the pin; `null` unless `status == "uploaded"` |
| `commit_message` | names the inventory row and manifest sha |
| `path_in_repo` | destination path inside the dataset repo |
| `sha_convention` | `"bytes on disk as-is (binary read, no line-ending normalization)"` |

## Eligibility verification

Only rows with `hash_method == "sha256_filelist_manifest"` and
`hash_status == "complete"` can be verified by this tool today (this is the
same set of 6 rows the Workstream A census marked `UPLOAD_ALLOWED` — see
`inventory-summary.md`). Rows hashed with `sample_first_largest_newest_sha256`
(the `deferred-bulk` rows: courtlistener, corpus-cache, specialist-v2-65536)
are never `UPLOAD_ALLOWED` in the current inventory; if one ever were, this
tool would refuse the whole run rather than upload it unverified.
