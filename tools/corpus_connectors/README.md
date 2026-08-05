# corpus_connectors

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

Minimal, receipted fetch CLIs for the corpus program (deliverable D4, charter
refs #590, #648). Six thin per-source connectors over one shared receipt
core, plus a resumable chunked-bulk transport engine (issue #1440) for
sources too large for the ordinary single-fetch cap. No GPU, no model
inference, no dedup/decontamination, no scheduling -- this package is
fetch-only.

## L3 / L4 / L5 contract statement

- **L3 (fetch-only):** every connector CLI performs exactly one honest thing --
  download bytes from a named public source and record where they came from.
  No external model authors, filters, ranks, scores, or selects any token in
  this package. Every written receipt carries this statement verbatim in its
  `l3_statement` field.
- **L4 (receipted provenance):** no fetch without a receipt. A fetch whose
  receipt write fails is defined as a FAILED fetch (fail-closed) -- any files
  it wrote are deleted before the CLI exits nonzero. Every receipt records
  the canonical source id/URL, a pinned revision where the source has one,
  a license plus the evidence for that license (never guessed), and a
  sha256 per downloaded file plus a manifest-level hash over all of them.
- **L5 (scope fence):** this package does NOT do dedup/decontamination
  (separate lanes), scheduling/daemons, an MCP server, or Kaggle credential
  provisioning. CLI first; a later lane can wrap these as an MCP server if
  the charter needs it.

## Layout

```
tools/corpus_connectors/
  README.md            # this file
  receipt.py           # shared: hashing, receipt schema, license/credential gates,
                        # download helper (512 MiB single-fetch cap), manifest.jsonl shim
  hf_fetch.py           # HuggingFace datasets/files
  arxiv_fetch.py        # arXiv API (Atom) metadata + per-paper license filter + PDF/source
  openreview_fetch.py   # OpenReview API v2 (anonymous read) metadata + license-clean PDFs
  kaggle_fetch.py        # Kaggle CLI wrapper -- refuses cleanly when credentials absent
  http_fetch.py          # plain HTTP(S) for named-source pulls (OpenStax/archive.org/NIST/etc.)
  chunked_download.py    # shared engine: resumable HTTP-Range chunked transport, its own
                          # declared byte budget, independent of receipt.py's 512 MiB cap
  bulk_fetch.py           # CLI over chunked_download.py, for dumps that exceed the single-fetch
                           # cap (Wikipedia/PMC/Stack Exchange/USPTO/... bulk packages)
  tests/                 # offline unit tests (no external network); one mocked fetch per
                          # single-shot connector, plus a real 127.0.0.1 Range-request fixture
                          # server (tests/_range_fixture.py) for chunked_download.py/bulk_fetch.py
```

## Dependency posture (per §6 of the frozen build spec)

The builder used only dependencies confirmed present in the build environment
at build time, or Python stdlib. Nothing was newly installed.

| Dependency | Status at build time | Connector behavior |
|---|---|---|
| `huggingface_hub` | present (1.22.0) | `hf_fetch.py` imports and uses it directly |
| `datasets` | present (4.1.1) | not used (huggingface_hub alone suffices for this scope) |
| `requests` | present (2.32.5) | not used (stdlib `urllib.request` used throughout for portability) |
| `feedparser` | **absent** | `arxiv_fetch.py` parses the Atom API response itself via `xml.etree.ElementTree` |
| `arxiv` (PyPI package) | **absent** | `arxiv_fetch.py` calls the public arXiv API directly via `urllib.request`, no wrapper package |
| `openreview` (PyPI package) | **absent** | `openreview_fetch.py` calls the OpenReview API v2 REST endpoint directly via `urllib.request` + stdlib `json` |
| `kaggle` (PyPI package) | present (import OK) | `kaggle_fetch.py` shells out to the `kaggle` console-script CLI via `subprocess` rather than importing the package's Python API, so a credential problem surfaces as this connector's own `BLOCKED` line instead of an exception raised inside the `kaggle` package at import/config time |
| `git-lfs` | present (3.5.1) | not needed by this package (no LFS-tracked pulls in this scope) |
| `curl` | present (8.9.0) | not used (stdlib `urllib.request` covers every HTTP need here) |

## Receipt schema (frozen, `corpus-connector-receipt-v1`)

```json
{
  "schema": "corpus-connector-receipt-v1",
  "source": "huggingface|kaggle|arxiv|openreview|http",
  "source_id": "canonical id (repo id / dataset slug / arXiv id set / venue id / URL)",
  "canonical_url": "https://...",
  "license": "SPDX-or-stated license string, per source-of-record, or UNVERIFIED",
  "license_evidence": "where the license was read (file/field/page), recorded at fetch time",
  "revision": "commit sha / version / null",
  "files": [{"path": "relative", "bytes": 0, "sha256": "hex"}],
  "total_bytes": 0,
  "sha256_manifest": "hash over sorted file hashes",
  "fetched_at": "ISO8601Z",
  "connector": {"name": "hf_fetch", "version": "v1"},
  "l3_statement": "fetch-only; no external model authored/filtered/ranked/scored/selected any token",
  "dest_root": "relative to the local data root",
  "notes": ""
}
```

Written to `<dest_root>/_manifests/<utc-ts>-<safe_source_id>.json`. License is
never guessed: absent/unclear = `"UNVERIFIED"` and the CLI exits nonzero
unless `--allow-unverified-license` is passed (which still records
`UNVERIFIED` -- the tranche is then excluded from training use until
resolved). Every CLI ends by printing exactly one line:

```
RECEIPT <manifest-path>      # success
BLOCKED <reason>             # refusal (missing creds, unverified license,
                              # hash mismatch, dest collision) -- nonzero exit
```

### Compatibility shim -- mapping onto the existing `manifest.jsonl` template

The pre-existing `<domain>/manifest.jsonl` files under the local data root
(e.g. `arxiv-abstracts/manifest.jsonl`, `courtlistener/manifest.jsonl`) use
one flat row per file:

```json
{"source_url": "...", "sha256": "...", "bytes": 0, "license": "...",
 "human_provenance_basis": "...", "fetched_ts": "...", "selection_rule": "..."}
```

`receipt.to_manifest_row()` maps every `Receipt` onto that template (one
legacy-shaped row per file in `receipt.files`) so a new connector pull
normalizes onto the existing template instead of introducing a parallel
schema. Field mapping:

| legacy field | source |
|---|---|
| `source_url` | `receipt.canonical_url` |
| `sha256`, `bytes` | per-file values |
| `license` | `receipt.license` |
| `human_provenance_basis` | `receipt.notes` if set, else a machine-fetched default that points at `license_evidence` for a human to audit |
| `fetched_ts` | `receipt.fetched_at` |
| `selection_rule` | `receipt.source_id` |

`receipt.append_manifest_rows()` appends those rows to
`<dest_root>/manifest.jsonl` in the same call that writes the connector's own
`_manifests/<ts>-<key>.json` receipt -- both writes are part of one
fail-closed commit (`receipt.commit_receipt()`): if either write fails, any
files this fetch attempt downloaded are deleted and the CLI exits BLOCKED.

## Per-CLI usage

### `hf_fetch.py` -- HuggingFace datasets/files

```
python hf_fetch.py REPO_ID [--revision R] [--include GLOB ...] [--dest DIR]
                   [--dataset|--model] [--allow-unverified-license]
```

Resolves `--revision` (default `main`) to a pinned commit SHA via the Hub
API, downloads via `huggingface_hub.snapshot_download`, and reads the license
from repo card metadata. `--dataset` (default) or `--model` selects
`repo_type`. `--dest` defaults to `./corpus-downloads/hf/<safe repo_id>`.

### `arxiv_fetch.py` -- arXiv API (Atom) metadata + content

```
python arxiv_fetch.py (--ids ID... | --query Q --max N) [--what meta|pdf|source]
                      [--dest DIR] [--license-filter cc-only|all]
                      [--allow-unverified-license]
```

Stdlib-only. Respects the API's politeness contract (<=1 request per 3s,
<=100 results per page). Per-paper license comes from the Atom
`<arxiv:license>` element: a `creativecommons.org` (or CC0) URL is a resolved
CC license; any other value (typically arXiv's own default
`nonexclusive-distrib` license) is a resolved, non-CC, KNOWN license -- not
`UNVERIFIED`; a missing element is `UNVERIFIED`. Under the default
`--license-filter cc-only`, `--what pdf|source` only downloads content for
CC-licensed papers (arXiv-perpetual and UNVERIFIED papers are excluded from
content fetch, per spec: "arXiv-perpetual license papers are metadata-only
unless filter widened"); `--license-filter all` widens this. `--what meta`
never downloads content; it writes one JSON listing of the returned entries.
One receipt per invocation: the top-level `license` field summarizes the
eligible set, per-paper detail is always recorded in `notes`.

### `bulk_fetch.py` -- resumable chunked-bulk transport (issue #1440)

```
python bulk_fetch.py URL --budget-bytes N [--chunk-size-bytes N]
                     [--disk-margin-bytes N] [--sha256 EXPECTED]
                     [--license STR --license-evidence STR]
                     [--dest DIR] [--allow-unverified-license] [--timeout N]
```

For bulk dumps that exceed `receipt.py`'s 512 MiB single-fetch cap (Wikipedia
XML dumps, PMC OA packages, Stack Exchange 7z dumps, USPTO bulk grants,
arXiv bulk packages, ...). Stdlib-only (`urllib.request`), fetched serially
as a sequence of HTTP Range requests via the `chunked_download.py` engine.
`--budget-bytes` is **required** -- the caller always states the total byte
budget up front; the fetch refuses to start, or to continue past a resume,
if the remote size would exceed it. This budget is entirely independent of
the 512 MiB cap: `chunked_download.py` never calls `receipt.download_url()`
and never widens `MAX_DOWNLOAD_BYTES` -- the ordinary single-fetch connectors
are untouched by this module.

**Resumable.** The first chunk request doubles as the Range-support probe:
any non-206 response (including a 200 that silently ignores the Range
header) is refused (`RangeNotSupportedError`) rather than treated as data --
accepting a 200 would silently re-read from byte 0 on every "chunk". Progress
is fsync'd to a `<file>.partial` and mirrored, chunk by chunk, into a
`<file>.bulkstate.json` sidecar. Re-running the identical command (same URL/
`--dest`/`--chunk-size-bytes`/`--budget-bytes`) against a destination with an
in-progress sidecar resumes automatically from the last durably-committed
chunk -- no separate `--resume` flag. On resume, every previously-committed
chunk's on-disk bytes are re-hashed against its recorded sha256 *before* any
new network request; a mismatch (external corruption/truncation of the
partial file) is `ChunkDigestMismatchError` -- a corrupted resume is refused,
never silently trusted or silently restarted. A `.partial` found with no
matching sidecar is also refused (`ResumeStateMismatchError`) rather than
guessed at.

**Fail-closed on every ambiguity**, each its own machine-readable
`BlockedError` subclass (ten in total, all defined in `chunked_download.py`):
`RangeNotSupportedError`, `ChunkFetchError` (unexpected HTTP status --
including a real 4xx/5xx, which `urllib.request.urlopen` raises as an
`HTTPError` rather than returning as a normal response; that is caught and
routed through the same status check, not left to leak out as a raw
`urllib.error.HTTPError`), `BudgetExceededError`, `DiskMarginError`,
`RemoteIdentityChangedError` (ETag/Last-Modified/total-size changed
mid-transfer), `ChunkLengthMismatchError` (a chunk delivered fewer bytes than
its own `Content-Range` promised -- this one condition covers a truncated
final chunk and any mid-file truncation uniformly, since the check is "bytes
received vs. bytes `Content-Range` promised for *this* response", not a
last-chunk special case), `ResumeStateMismatchError`,
`PartialFileSizeMismatchError`, `ChunkDigestMismatchError`,
`WholeFileDigestMismatchError`. None of these ever produce a partial
success: every refusal either writes zero bytes (the budget/disk-margin/
Range-unsupported checks all happen before any chunk bytes are written to
disk) or leaves the `.partial`+sidecar exactly at the last verified-good
chunk boundary for a later resume.

**The server-supplied `Content-Range` end is never trusted past what was
actually asked for.** `resp_end` is server-controlled; before it is allowed
to drive how many body bytes get read, `_fetch_one_chunk` checks
`resp_start <= resp_end <= min(requested_end, resp_total - 1)`. A server --
hostile or merely broken -- that answers a small requested range with a much
larger `Content-Range` is refused (`RangeNotSupportedError`) *before a
single byte of the oversized body is read*, mirroring `receipt.py`'s
`download_url()`: the ceiling is checked before the write, so overshoot is
bounded to one block (here, one chunk, never read at all once out of
bounds). This closed a real gap found in review (`ContentRangeBoundExploitTests`
in `tests/test_chunked_download.py` is the permanent regression coverage):
previously the oversized body was read and written in full, and only the
(real, but too-late) whole-file size check at the end of the transfer
caught it.

**Disk safety.** `shutil.disk_usage()` on the destination volume is checked
against `--budget-bytes` + `--disk-margin-bytes` (default 1 GiB margin)
before any network call, *and again before every individual chunk write* --
a multi-hour bulk pull can outlast the volume's free space partway through,
and that must surface as a clean `DiskMarginError` (leaving the `.partial`+
state resumable at exactly the last good chunk) rather than a raw `OSError`
out of `write()`/`fsync()` several chunks in.

**License + evidence**, exactly like `http_fetch.py`: `--license`/
`--license-evidence` must be supplied together or not at all (absent =
`UNVERIFIED`, gated by `--allow-unverified-license`).

**Per-chunk receipts.** On success, in addition to the standard
`corpus-connector-receipt-v1` receipt (`source: "http-bulk"`) and
`manifest.jsonl` row every connector produces, a
`corpus-bulk-chunk-manifest-v1` JSON is written to
`<dest>/_manifests/<ts>-<key>.chunks.json`: every chunk's index, byte
offsets, per-chunk sha256, and fetch timestamp, plus the whole-file sha256
and total byte count -- enough for a later auditor to verify the assembled
file's provenance chunk-by-chunk without re-downloading anything. The
standard receipt's `notes` field records the chunk manifest's relative path,
chunk count/size, budget, and whether this run resumed a prior attempt. The
ephemeral `.bulkstate.json` (whose only job is enabling resume) is deleted
on success; the chunk manifest is the permanent audit artifact.

### `openreview_fetch.py` -- OpenReview API v2, anonymous read

```
python openreview_fetch.py --venue VENUE_ID [--year Y] [--what meta|pdf]
                           [--dest DIR] [--allow-unverified-license]
```

Stdlib-only, queries `https://api2.openreview.net/notes` directly. A note's
`content.license` field (when present) is its license; absent = `UNVERIFIED`.
`--what pdf` fetches only license-clean (resolved-license) notes' PDFs; other
notes stay metadata-only. **Documented assumption, not live-verified at
build time:** the query-parameter names used for venue/year filtering
(`content.venueid`, `content.year`, `offset`, `limit`) are implemented per
the OpenReview API v2 docs as understood at build time; this connector is
NOT covered by the spec's optional `--live` smoke (that smoke is
`hf_fetch`-only) -- verify against a real venue before a production pull if
the venue's schema differs.

### `kaggle_fetch.py` -- Kaggle CLI wrapper

```
python kaggle_fetch.py DATASET_SLUG [--dest DIR] [--allow-unverified-license]
```

Checks for credentials (env vars `KAGGLE_USERNAME`/`KAGGLE_KEY`, or
`~/.kaggle/kaggle.json` / `$KAGGLE_CONFIG_DIR/kaggle.json` existence-only --
this connector never reads or logs credential contents) BEFORE touching the
`kaggle` CLI at all; if absent, prints a single `BLOCKED` line and exits
nonzero -- no account creation, no prompts. License is read via
`kaggle datasets metadata` (parses the written `dataset-metadata.json`'s
`licenses[].name`); content via `kaggle datasets download`, both invoked as
subprocesses.

### `http_fetch.py` -- plain HTTP(S) for named-source pulls

```
python http_fetch.py URL [--sha256 EXPECTED] [--license STR --license-evidence STR]
                     [--dest DIR] [--allow-unverified-license]
```

Stdlib-only. License is a human/lead judgment about the named source (a
calling spec supplies it) -- this tool never guesses it from the URL or
response headers. **Implementation choice:** `--license`/`--license-evidence`
are optional (not hard-required), because the frozen receipt schema already
has a uniform "absent/unclear = `UNVERIFIED`, gated by
`--allow-unverified-license`" rule (§2) -- reusing that one gate across every
connector (including `bulk_fetch.py`, added later) is simpler than a one-off
required-argument shape for just this CLI. If one of the pair is given without the other, the CLI refuses
(`BLOCKED`) rather than guessing which was meant. `--sha256 EXPECTED`
verifies the download and deletes the partial file on mismatch.

## Tests

`tests/` -- offline, no external network: `test_receipt.py` covers the shared
core (schema shape, hashing, the manifest-compatibility shim, license/credential
gates, the download helper, and fail-closed behavior on a receipt-write
failure); one `test_<connector>_fetch.py` per single-shot CLI mocks that
connector's external calls (HfApi/snapshot_download; a canned arXiv Atom XML
payload; a canned OpenReview JSON payload; a fake `kaggle` CLI subprocess
runner; a fake `urlopen`) and exercises both the success (`RECEIPT`) and
refusal (`BLOCKED`) paths.

`test_chunked_download.py`/`test_bulk_fetch.py` use a different, stronger
strategy: `tests/_range_fixture.py` runs a real `http.server` bound to
`127.0.0.1` on an OS-assigned ephemeral port (loopback only -- no external
network, but real `urllib.request`/`http.client` wire behavior: actual
`Range`/`Content-Range`/`ETag` headers, actual socket framing). This matters
here specifically because the failure modes this connector must detect --
a server that silently ignores `Range` and returns 200, a response body cut
short of what its own `Content-Range`/`Content-Length` promised, a
mid-transfer `ETag` flip -- are wire-level phenomena a hand-rolled fake
response object can only approximate; a real server exercises the actual
header-parsing and short-read-detection code paths. Interruption (for the
resume tests) is injected client-side via `_range_fixture.flaky_opener()`,
which wraps the real `urllib.request.urlopen` and lets the first N real
requests through before raising `ConnectionError` -- the server itself stays
simple and fully healthy throughout, matching how a real interruption
(client/network drop, not server misbehavior) actually happens. The resume
test asserts against the fixture server's own request log that the two
chunks completed before interruption are never re-requested after resume.
Run with either:

```
python -m pytest tests/
python -m unittest discover -s tests
```

No `--live` flag exists in this test suite (CI stays network-free, per spec
§4). The spec's one OPTIONAL live smoke (an `hf_fetch` pull of a <1MB public
file, asserting a valid receipt) is not implemented as an automated test
target in this PR -- it is documented here as the intended shape for a
follow-up manual/CI-gated smoke, since running it live was out of scope for
this offline-only build pass.

## Implementation notes / design choices not fully pinned by the frozen spec

The frozen spec (§1-§5) fixes the package shape, the receipt schema, and the
per-CLI contracts; a few concrete choices were left to the builder and are
recorded here for audit:

- **`--dest` defaults.** Every connector defaults `--dest` to a relative
  `./corpus-downloads/<source>/<safe key>` path when omitted, rather than
  requiring the flag. Real pulls should always pass `--dest` explicitly to
  point at the actual local data root (e.g. a sibling `ember-data/raw/...`
  directory) -- the default exists only so each CLI is runnably standalone.
- **One receipt per CLI invocation, even for multi-item pulls.** The frozen
  schema has a single `license` field per receipt. `arxiv_fetch.py` and
  `openreview_fetch.py` can return many papers/notes in one run; rather than
  emit one receipt per item (which would violate "prints exactly one
  `RECEIPT` line"), each emits ONE receipt per invocation whose top-level
  `license` is a best-effort summary (a single shared license string, or a
  `cc-mixed`/`mixed (see notes)` label) and whose `notes` field always
  carries the full per-item license breakdown.
- **arXiv per-paper license classification** (`arxiv_fetch.ArxivEntry`):
  a `creativecommons.org`/CC0 URL is CC; any other present value is the
  named, resolved `"arXiv perpetual, non-exclusive license"` (not
  `UNVERIFIED`); a missing `<arxiv:license>` element is `UNVERIFIED`. This
  reflects the spec's own framing ("arXiv-perpetual license papers are
  metadata-only unless filter widened") that the perpetual license is a
  KNOWN quantity, not an unresolved one.
- **No overwrite / no force flag.** None of the CLIs accept a
  destination-overwrite override; a pre-existing *final* file/dir at the
  resolved destination is always a `BLOCKED dest collision`. Re-running a
  pull against a fresh `--dest` (or after clearing the prior one) is the
  intended flow. `bulk_fetch.py` is the one deliberate exception to "a prior
  run's leftovers are always a collision": an in-progress `.bulkstate.json` +
  `.partial` pair at the destination is not a collision but a resume point --
  see its own section above.
- **`bulk_fetch.py`'s `source` field is `"http-bulk"`, not `"http"`.** Even
  though it is HTTP(S) under the hood, resumable chunked transfer has
  materially different operational properties (sidecars, multi-request,
  budget-gated) than `http_fetch.py`'s single-shot pull; a distinct `source`
  value lets any downstream consumer/dashboard filter or reason about the two
  separately without parsing `connector.name`. `receipt.py`'s `source` field
  is a free string, not a closed enum, so this is additive and non-breaking.
- **Per-chunk audit trail lives in its own JSON, not in the frozen receipt.**
  The frozen `corpus-connector-receipt-v1` schema's `notes` field is prose
  everywhere else in this package (human-readable summaries, license
  breakdowns); stuffing a potentially-thousand-entry chunk list into it would
  both violate that convention and make `notes` unreadable. Instead
  `bulk_fetch.py` writes a separate `corpus-bulk-chunk-manifest-v1` JSON
  under `_manifests/` (parallel to the receipt's own manifest JSON) and
  records only its relative path plus a one-line summary in `notes` --
  matching how this package already normalizes new structured data onto its
  own artifact rather than overloading an existing field (see the
  `manifest.jsonl` compatibility shim above).
- **Chunk size default (64 MiB) and disk margin default (1 GiB) are builder
  judgment, not spec-pinned.** Both are overridable per-invocation
  (`--chunk-size-bytes`, `--disk-margin-bytes`); 64 MiB keeps a 50 GiB wave
  fetch to roughly 800 chunks (each individually resumable, each its own
  fsync'd durability point) without an excessive number of HTTP round trips.
- **Resume is automatic, not flag-gated.** A `--resume` flag was considered
  and rejected: the sidecar state file already unambiguously records whether
  a resumable attempt exists for this exact URL/dest/chunk_size/budget
  combination, and any mismatch on those fields is refused
  (`ResumeStateMismatchError`) rather than silently reinterpreted -- an
  explicit flag would only add a way to forget to pass it.
