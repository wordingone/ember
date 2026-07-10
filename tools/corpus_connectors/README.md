# corpus_connectors

Minimal, receipted fetch CLIs for the corpus program (deliverable D4, charter
refs #590, #648). Five thin per-source connectors over one shared receipt
core. No GPU, no model inference, no dedup/decontamination, no scheduling --
this package is fetch-only.

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
                        # download helper, manifest.jsonl compatibility shim
  hf_fetch.py           # HuggingFace datasets/files
  arxiv_fetch.py        # arXiv API (Atom) metadata + per-paper license filter + PDF/source
  openreview_fetch.py   # OpenReview API v2 (anonymous read) metadata + license-clean PDFs
  kaggle_fetch.py        # Kaggle CLI wrapper -- refuses cleanly when credentials absent
  http_fetch.py          # plain HTTP(S) for named-source pulls (OpenStax/archive.org/NIST/etc.)
  tests/                 # offline unit tests + one mocked fetch per CLI (no network)
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
`--allow-unverified-license`" rule (§2) -- reusing that one gate across all
five connectors is simpler than a one-off required-argument shape for just
this CLI. If one of the pair is given without the other, the CLI refuses
(`BLOCKED`) rather than guessing which was meant. `--sha256 EXPECTED`
verifies the download and deletes the partial file on mismatch.

## Tests

`tests/` -- offline, no network: `test_receipt.py` covers the shared core
(schema shape, hashing, the manifest-compatibility shim, license/credential
gates, the download helper, and fail-closed behavior on a receipt-write
failure); one `test_<connector>_fetch.py` per CLI mocks that connector's
external calls (HfApi/snapshot_download; a canned arXiv Atom XML payload; a
canned OpenReview JSON payload; a fake `kaggle` CLI subprocess runner; a fake
`urlopen`) and exercises both the success (`RECEIPT`) and refusal
(`BLOCKED`) paths. Run with either:

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
- **No overwrite / no force flag.** None of the five CLIs accept a
  destination-overwrite override; a pre-existing file/dir at the resolved
  destination is always a `BLOCKED dest collision`. Re-running a pull against
  a fresh `--dest` (or after clearing the prior one) is the intended flow.
