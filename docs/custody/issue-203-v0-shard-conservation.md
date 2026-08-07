<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Issue 203: v0 shard-conservation crosswalk

Status: `LOSSLESS_CONSOLIDATION / DEPRECATED_ABSORBED`

This is an append-only historical-to-current crosswalk for issue #203. It does
not recreate the removed v0 mechanism, claim that the old bytes are available,
or grant model, training, benchmark, or capability credit.

## Bound public evidence

The crosswalk is bound to public master
`7af65b0a4b98fd3bd34196bc86e6509e393acb6f`.

The historical shard receipt is
`receipts/token-shards-v0-20260611T170047Z.json`. Its current Git blob is the
only public byte carrier for the v0 shard facts. The receipt records
`v0-00025.bin` as SHA-256
`d2bc5c37a48a33ec40bc3358a9a84f11dda0c19ab82d37e09606c2d202ed106f`, with
`266982358` tokens, and records a 26-shard stream with
`6977868758` total stream tokens. The receipt also states
`shard_dir: "../shards-v0"`, so the packed shard files are not in this
checkout.

The receipt's `provenance_restoration_20260714` says that the shard bytes are
unchanged but the raw corpus and packed shard data are not present locally.
Consequently the receipt hashes preserve identity claims only; they cannot
reconstruct or re-quantify the missing bytes. No current public tree entry is
`v0-00025.bin` or any of the 26 packed v0 shard files.

## Complete #203 obligation map

The original issue has four obligations. Each is retained here rather than
silently dropped:

1. Characterize the repeated-text/document class. The historical reports and
   comments remain preserved as intent and evidence pointers, but the exact
   v0-00025 bytes are unavailable, so a fresh characterization is not claimed.
2. Quantify self-duplication across all 26 shards. The receipt preserves the
   shard names, hashes, and token counts, but no public consumer can recompute
   13-gram recurrence without the exact shard bytes. No replacement estimate is
   substituted.
3. Select rebuild, drop, or accept-with-disclosure. The current disposition is
   `DEPRECATED_ABSORBED`: the removed v0 admission path is not a current
   executable route; the historical loss and non-recoverability are disclosed
   here. Any future cure decision must use newly acquired, independently
   hashed bytes and must not relabel the old receipt.
4. Preserve W1/cross-rung comparability. The obligation survives as a custody
   reopening condition owned by EMBER-01. It is not asserted satisfied by the
   receipt alone, and no historical v0 result is promoted to a current rung.

## Historical-to-current crosswalk

| Historical #203 mechanism | Current status | Current owner and binding |
| --- | --- | --- |
| v0 token-shard admission and `shards-v0` files | `REMOVED` from current Ember Lab admission | Current custody spine: EMBER-01 / issue #1115, `docs/custody/ember-01-custody-README.md` |
| v0-00025 recurrence characterization | `SUPERSEDED` as an executable path; obligation retained | EMBER-01 reopening rule `EMBER-01.REOPEN.001`; exact bytes must be restored before recomputation |
| 26-shard self-duplication quantification | `SUPERSEDED` as an executable path; obligation retained | EMBER-01 receipt/root census and future exact-byte re-verification |
| rebuild/drop/accept-with-disclosure decision | `DEPRECATED_ABSORBED` | This disclosure plus EMBER-01.REOPEN.001; no current admission decision is inferred |
| W1/cross-rung comparability | `CURRENT` as a preserved obligation, not a completed result | EMBER-01 current custody/benchmark spine; any unique uncustodied artifact reopens EMBER-01 |

The current Ember Lab primitives reused by this transfer are the exact-byte
token-shard receipt, SHA-256 field binding, `text_lab_corpus.validate_authority_index`
preflight semantics, the EMBER-01 custody census, and the public certificate's
`EMBER-01.REOPEN.001` rule. They are one existing authority family; this file
does not create a second corpus, shard, receipt, benchmark, or launcher owner.

## Lossless transfer and reopening

The surviving owner is issue #1115 (EMBER-01 custody/identity spine), whose
public certificate is `docs/roadmap/certificates/EMBER-01.md`. The transfer is
append-only and lossless: #203's byte identity, 26-shard scope, recurrence
question, cure choice, disclosure boundary, and W1 comparability obligation
remain named above. If exact v0 bytes or a consumer that bypasses the current
identity manifest is later found, `EMBER-01.REOPEN.001` is the required route;
the owner must reopen and re-verify rather than silently edit this historical
finding.

This crosswalk therefore supports a closure proposal for #203 as
`SUPERSEDED / DEPRECATED_ABSORBED` with zero scope loss. It does not close the
issue itself and makes no claim that the old data, a rebuilt corpus, a model,
or a benchmark result is available.

## Authority and conflict scan

- The receipt and historical comments are preserved; no historical hash is
  rewritten.
- Current `assemble_v1.py` performs exact shard SHA verification and whole-
  document deduplication, but it is not a v0 13-gram recurrence producer and
  is not claimed to be one.
- Current `text_lab_corpus.py` keeps candidate inputs in fail-closed
  `PREFLIGHT_ONLY` / `UNRESOLVED_CANDIDATE` states; this crosswalk does not
  promote them.
- No parallel corpus authority, receipt family, tokenizer authority,
  launcher, or benchmark owner is introduced.

`NO_NEW_PARALLEL_AUTHORITY`: all future byte custody, admission, and
comparability decisions remain under the existing EMBER-01/issue-1115 spine.

## Reproduction boundary

From a clean checkout at the bound master, a reviewer can verify the receipt
path, its 26 shard rows, the v0-00025 SHA/token count, and the absence of the
packed shard paths. A reviewer cannot reproduce the historical recurrence
measurement without the missing exact shard bytes; that limitation is an
explicit result, not an unresolved claim hidden by this document.
