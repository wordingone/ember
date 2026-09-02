# #1719/#1581 GitHub multi-repository license-partition design

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- design_only: true -->

Date: 2026-08-17 PT
Source authority: issues #1719 and #1581 at Ember commit
`28bbe0ff912a7e7a12ab34c0acdba8959caa2a92`.

## Decision and non-claims

Add a closed GitHub archive partition/extraction receipt before tranche admission.  The
receipt must join every admitted regular-file byte string to exactly one source repository,
the archive's own commit identity, the original connector-file hash, and that repository's
frozen SPDX value.  Heterogeneous repository licenses remain separate partitions; they must
not be represented by the current `license_spdx: list[str]` form, because that form means a
conjunction applying to one content tree.

This design does not reacquire GitHub data, infer a license from filenames or license text,
normalize source bytes, admit a row, mint a successor, move corpus custody, or make a
training/model claim.  Production and tests remain unchanged until this document is reviewed.

## Frozen inputs and observed shape

The only executable inputs are the existing connector receipts and payloads below.  A future
implementation must require both the receipt path and exact receipt SHA-256, then reopen the
receipt and every listed archive under its recorded `dest_root`.

| Route | Frozen connector receipt | Receipt SHA-256 | Archives / selected repos | Reopened bytes |
| --- | --- | --- | ---: | ---: |
| F-train-2 | `_manifests/20260815T003818Z-topic-cuda.json` | `0AA4C56EF987A0C815524295860B4EDF6BCEA40A1BC965444C0189881D3373E1` | 57 / 57 | 1,979,962,837 |
| H-train-2 | `_manifests/20260815T004426Z-topic-testing.json` | `228C83CC519CECC938378A75CD2F275EF1807E29DB1C5D9C7612F5F0F10219A8` | 21 / 21 | 463,935,857 |
| H-heldout-1 | `_manifests/20260815T014809Z-topic-debugging.json` | `3941C788649975B10F529402C71D3B1FB6F4A781D904C6A036E6D7056CA65A3E` | 123 / 123 | 1,084,925,250 |

The three receipt hashes, `sha256_manifest` values, archive sizes, and archive SHA-256 values
recomputed successfully.  `notes.selected` maps bijectively to the payload names using the
connector's exact `safe_key(full_name) + ".tar.gz"` rule.  Its 201 scalar license values are all
in the receipt's frozen allow-set: F is 38 Apache-2.0, 13 MIT, 6 BSD-3-Clause; H-train is 4
Apache-2.0 and 17 MIT; H-heldout is 31 Apache-2.0, 89 MIT, 2 BSD-3-Clause, and 1 CC-BY-4.0.

Every archive has one lowercase 40-hex commit in the tar global-PAX `comment`; no receipt
currently carries that revision.  Root license artifacts are not uniform: twelve repositories
use forms such as `LICENSE-APACHE`, `LICENSE-MIT`, `LICENCE`, `LICENCE.md`, or `MIT-LICENSE`, and
some carry multiple root licenses.  Twenty-seven archives contain link members.  Therefore
neither a single `LICENSE` lookup nor the current aggregate connector adapter is sufficient.

The connector's frozen license authority is explicit:
`GitHub Search API per-repo license.spdx_id (LICENSE-file detection), filtered to allow-set`.
The partitioner may promote only the scalar `notes.selected[*].license` values already bound by
the connector receipt digest.  Root license files may be hashed as supplemental observations,
but filename or text inspection must never mint or override SPDX authority.

`K-train-1` and `K-train-2` contain no payload or `_manifests` receipt.  The K
route is schema-covered but non-executable: it must refuse until an independently governed
connector receipt and custody root satisfy this same contract.  Reacquisition is out of scope.

## Closed producer contract

Proposed producer: `tools/ember-restart-3b/mint_github_license_partition.py`.

Its plan is a closed list of cases with exactly:

- `source_id`, `connector_slot`, `split`, and `domain`;
- absolute `connector_receipt_path` plus exact `connector_receipt_sha256`;
- exact output path, which must not already exist; and
- expected connector identity (`github_fetch`, `v1`) and expected source topic.

For each case the producer must:

1. Reopen and hash the receipt bytes before parsing.  Require the exact
   `corpus-connector-receipt-v1` shape, connector identity, source ID, evidence string, closed
   notes shape, allowed-license list, file list, total bytes, and `sha256_manifest`.
2. Require a bijection between `notes.selected` and receipt files using the connector's literal
   `safe_key` algorithm.  Reject missing/extra entries, repeated repository names or URLs,
   repeated file paths, and two repository names that collapse to one safe key.
3. For each archive, stream the same compressed bytes through SHA-256 and `tarfile` parsing in
   one pass.  Drain to EOF and require the resulting size/hash to equal the receipt entry.  Do
   not hash one path and later parse a reopened path.
4. Require one top-level tar root and one identical lowercase 40-hex global-PAX `comment` across
   the archive members that carry it.  That value is `source_revision`; callers cannot supply
   or override it.
5. Reject NUL, absolute/drive, empty, `.`, or `..` path segments and duplicate exact member
   paths.  Directories and links are not training bytes.  Record directories, symlinks,
   hardlinks, and other non-regular members in a closed exclusion list with exact tar path,
   member type, and link target where applicable.  Never follow or materialize a link.
6. Stream every regular member's raw bytes unchanged into a content-addressed output blob
   `blobs/sha256/<first-two>/<sha256>`, using create-new semantics.  Reopen and hash each staged
   blob before publication.  Original POSIX member paths remain receipt data only, avoiding
   Windows path rewriting or case-fold collisions.
7. Canonically sort per-file records by their exact UTF-8 tar path and compute a repository
   content root.  Canonically sort repository records by `source_repo` and compute the batch
   partition root.  Publish the staging directory with a no-replace rename only after a full
   independent reopen validation; on failure, publish nothing.

No generic normalization is permitted.  Equal byte strings may share a content-addressed blob,
but every source-path record remains distinct.

## Immutable receipt shape

`ember-github-license-partition-receipt-v1` contains the source connector receipt path/digest,
connector identity, source/split/domain, output blob root, and ordered `repositories`.
Each repository record contains exactly:

- `source_repo` (`owner/name`) and exact frozen `source_url`;
- `source_revision` derived from global PAX metadata;
- `archive_path`, `archive_bytes`, and `archive_sha256` copied only after byte revalidation;
- `declared_spdx` copied from the joined selected-note entry;
- `license_authority` containing the connector receipt digest, selected-note ordinal, canonical
  selected-note digest, and the exact connector evidence string;
- optional `root_license_observations`, each with exact tar path, bytes, and SHA-256, explicitly
  marked non-authoritative;
- ordered `files`, each containing exact tar path, bytes, SHA-256, blob-relative path,
  `source_repo`, `source_revision`, `archive_sha256`, and `declared_spdx`;
- ordered `excluded_members`; and
- `repository_content_root_sha256` over the canonical repository record excluding that root.

The top level carries `partition_root_sha256`, total repository/file/blob-byte counts, producer
path/hash, source commit, `model_mediated: false`, `borrowed_labels: false`, and result
`VERIFIED`.  All digests use SHA-256 over canonical UTF-8 JSON with sorted keys and compact
separators; lists retain the explicit order above.

The producer hash is a live input-identity boundary, not descriptive metadata.  The authority
reopener requires each receipt's `producer_sha256` to equal the current
`mint_github_license_partition.py` bytes.  Therefore any future producer edit intentionally
invalidates every existing partition receipt for admission and requires a fresh governed remint;
no compatibility fallback or historical-code substitution is permitted.

## Authority-index integration

Add a mutually exclusive partition route rather than weakening the current homogeneous route.
An admitted authority row using this route carries `license_partition_receipt` and
`license_partition_sha256`; it does not carry a synthetic aggregate `license_spdx` scalar or
conjunctive list.  Its L4 receipt uses a new closed generator/verifier pair and binds the
partition root as the row content identity.  `validate_authority_index` must reopen the
partition receipt, rederive every repository/file join and both roots, and prove that every
partition SPDX value is in the row's existing allow-set.

The authority-index schema must express the homogeneous and partition alternatives as disjoint
closed objects.  Existing rows and `adapt_connector_receipt` retain their current meaning and
byte behavior.  A sorted set of licenses may appear only as a non-authoritative summary in a
successor receipt, never in `license_spdx`.

The first real downstream consumer is
`src/ember/infrastructure/tools/ember-restart-3b/mint_issue1719_tranche_admission.py::_apply_cases`.  It must consume the
partition receipt by path+digest and place the partition alternative into the targeted F/H row.
The first canonical downstream validator remains
`text_lab_corpus.validate_authority_index`; `train.py` receives no new bypass.

## Required refusal matrix

- receipt, notes, archive, member bytes, staged blob, partition record, or root digest changes;
- source archive mutation/truncation during streaming, output collision, concurrent publisher,
  or any replace-existing attempt;
- aggregate `mixed (see notes)` used without exact per-repository partitioning;
- absent, non-scalar, unknown, disallowed, `NOASSERTION`, or mismatched per-repository SPDX;
- selected/file count mismatch, unknown repository, URL mismatch, safe-key collision, duplicate
  member path, or extra/missing custody archive;
- absent, malformed, multiple, or conflicting archive revision identities;
- absolute/traversing/NUL member path, link materialization, or an unrecorded special member;
- swapping equal-sized archives, repository metadata, revisions, file records, or SPDX values
  across partitions; and
- any K case without a frozen connector receipt and payload custody.

## TDD and execution plan after review

1. Add production-shaped RED fixtures for one two-repository mixed-license receipt plus the full
   race/tamper/unlicensed/mixed-unknown/swap matrix above.
2. Implement and focused-test the standalone partition producer and independent receipt
   reopener, using fixture tarballs only.
3. Replay the producer read-only against F-train-2, H-train-2, and H-heldout-1 into a fresh
   governed output root; compare the resulting 57/21/123 partition counts and exact input
   hashes.  K must produce a refusal receipt, not an empty admission.
4. Add the disjoint authority-index schema/validator alternative and focused negative tests.
5. Extend `mint_issue1719_tranche_admission.py` to consume exact partition receipt identities;
   run its focused suite, the complete text-lab authority suite, schema guards, compile, diff
   check, and an independent exact-head review.

Only after those gates may a separate no-overwrite successor mint be proposed.  A design,
source patch, or partition receipt alone earns no tranche admission, training, issue closure, or
model-result credit.

## Corpus custody sizing and credential safety

Genuine governed corpus payloads of every modality are exempt from the ordinary B: reserve
floor.  This exemption changes neither the established A: nor B: caps: acquisition and replay
must still refuse before actually filling B: and must preserve a small operating margin for
receipts, verification, and safe host operation.  Rebuildable caches and non-corpus artifacts
do not inherit the corpus exemption.

GitHub authentication material is never an observable artifact.  No workflow may invoke
`gh auth token`, `gh-safe auth token`, or any command whose output is a credential.
Authenticated Git operations, when separately authorized, must use `gh auth setup-git` or the
configured credential helper without printing the secret.
