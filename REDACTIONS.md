# REDACTIONS.md

Disclosure ledger for path redactions performed against historical capture/receipt
artifacts already committed to this repository. Per issue #456: the payload value of
these files is the captured/receipted CONTENT, never the absolute local-machine path
strings incidentally embedded in that content. This document exists so the historical
record discloses its own edit rather than silently rewriting it.

Note on this document's own wording: it deliberately avoids reproducing the exact
leaked-path literals it describes (drive-letter, colon, separator, sensitive segment,
all adjacent) — spelling them out in prose instead — so this disclosure file itself
does not become a 119th instance of the thing it discloses.

## What changed (2026-07-08, issue #456)

`tools/repo-guard.sh`'s absolute-path check (`PATHPAT`, guard step 2) required exactly
one path separator after the drive letter. A real Windows path serialized through
`json.dumps()` or Python `repr()` doubles every backslash — a single separator on disk
becomes two literal backslash characters in the tracked JSON text — so the
single-separator character class silently missed every such occurrence; the doubled
form slipped straight past the guard. Separately, temp-workspace paths (drive letter,
then a `Windows` segment, then a `Temp` segment) were never in the checked term list at
all (only the `Users`, `M`, and `Downloads` segment names were), so that whole class of
leak was invisible to the automated check even in single-separator form.

A tree-wide sweep against the tracked master history (starting from the 57+2 files
reported in issue #456, extended by first-principles re-enumeration of the same leak
class) found 118 tracked files carrying one or both shapes:

- This machine's project-drive mount (drive letter, then an `M` segment, then the repo
  name) — the vast majority, in receipt/manifest JSON and a handful of source-code
  comments.
- The operator's home directory (drive letter, then a `Users` segment, then the account
  name) — 2 files.
- This harness's per-session scratch directory (drive letter, then `Windows`, then
  `Temp`, then a session-scoped subpath that also embeds the workspace/org token) — 38
  terminal-capture `.txt`/`.json` files under `docs/verification/receipts-20260706/`.

## What was redacted, and how

Every leaked path string was replaced in place with one of two neutral tokens:

- `<TEMP_WORKSPACE>` — for the local drive-mount and temp-workspace shapes. Where the
  remainder of the path is repo-structure-relative and non-identifying (e.g.
  `<TEMP_WORKSPACE>/ember/receipts/foo.json`), that remainder is kept for diagnostic
  value. Where the path is a terminal-capture display string with no further meaning
  beyond "some temp path was shown here" (the 38 `docs/verification/receipts-20260706/**`
  files), the entire path was replaced with the bare token, dropping the tail.
- `<USER_HOME>` — for the 2 files carrying the operator's home directory
  (`baseline/receipts/deepseek-dspark-resolution-2026-06-29.json`,
  `baseline/receipts/promotion-readiness-2026-06-29.json`); the account name itself is
  dropped, the repo-irrelevant remainder is kept.

No other byte in any redacted file was changed. Every touched `.json`/`.jsonl` file
was verified to still parse, and every non-path leaf value was verified byte-identical
to the pre-redaction blob via a recursive structural diff (parse old vs. new, compare
every scalar, assert every difference is exactly a path-token substitution).

## What was fixed instead of redacted (functional code, not receipt data)

Three files hardcode an absolute path as a real runtime dependency, not as inert
capture data — replacing the string with a placeholder token would have broken them.
These got a minimal functional fix instead of a text redaction:

- `scripts/research/muon_spectrum_probe.py` — `leg1_receipt_path` was a hardcoded
  local-drive absolute path used to open a real comparison receipt at runtime. Now
  computed repo-relatively via `Path(__file__).resolve().parents[2]`.
- `tools/ember-cli/src/core/frontend-shell.ts` and
  `tools/ember-cli/src/ink/rendering-pipeline.ts` — the `M9-DIAG-LIVE` debug
  instrumentation hardcoded a temp-workspace absolute path as its log file location.
  Now computed via `os.tmpdir()` + `path.join(...)`, which is both portable and no
  longer machine-identifying.

## What was intentionally left untouched (guard-excluded, not a leak)

Four test files deliberately embed a leaked-path-shaped literal as adversarial input,
specifically to prove the app's own sanitization/redaction/clipping/shortening logic
strips or shortens exactly this shape. Redacting the fixture string to a placeholder
token would make the assertion it exists to test vacuous (e.g. an assertion that a
certain org-token substring is absent from the sanitizer's output is meaningless if the
input never contained that substring to begin with; a path-shortening test needs a
genuinely multi-segment absolute path to shorten). These are excluded by name from
`repo-guard.sh`'s path check (see `PATHPAT_EXCLUDE` in `tools/repo-guard.sh`), the same
mechanism the guard already used to exclude itself:

- `scripts/test_w1b_continuation.py`
- `tools/ember-cli/src/core/monitor-render.test.ts`
- `tools/ember-cli/src/components/homescreen-mock1-parity.test.ts`
- `tools/ember-cli/src/components/logo-homescreen.test.ts`

**Amendment (2026-07-08):** the exclusion mechanism was sound from the start, but the
literal content of these four fixtures was not -- they carried the real drive-mount
letter, the real org token, and the real sibling-project name, not just a shape that
happened to match the pattern. Fixed by synthesizing same-shape-but-fake values (fake
drive letter, fake org token, fake project name) in place of the real ones, updating
every assertion that keyed on the specific literal so the tests stay meaningful. Traced
each function under test first (`corpus_identity_for_receipt`,
`build_shard_corpus_verification_block`, `repo_relative_path`, `stripRawInternals`,
`clipToWidth`, `shortenDataRootForDisplay`) to confirm none hardcodes a literal check
against the real values -- this was purely a fixture-content issue, not a source-level
leak. `logo-homescreen.test.ts` was not part of the original ~59-file enumeration: it
landed on `master` via an unrelated, concurrently-merged PR (#303, path-shortening for
the cockpit `Data:` line) after this branch forked, and was caught fresh by this PR's
own guard fix once the branch was brought current with `master`.

`tools/ember-cli/src/entrypoints/session-init.ts` hardcodes the standard Windows
command-interpreter path (drive letter, `Windows`, `System32`, `cmd.exe`) as the
`COMSPEC` fallback — this is a universal, non-identifying Windows system path (every
Windows install has this exact file at this exact location), not a leak, and needed no
change. The guard's new Windows-Temp arm is deliberately scoped to require the `Temp`
segment specifically so this legitimate path never false-positives.

## Guard fix

`tools/repo-guard.sh`'s `PATHPAT` (step 2) separator class changed from exactly-one to
one-or-more, and gained a case-insensitive `Windows` + `Temp` alternative scoped to
require both segments. Probe-verified in a throwaway sandbox (never against this tree)
with paired pass/block fixtures covering single-separator, doubled-separator
(JSON/repr), and Windows-Temp shapes; the pre-fix regex was reproduced from git history
and run against the identical fixture set to confirm it missed exactly the cases this
fix now catches.

## Hash-pinned frozen artifacts (paths-check exclusions, 2026-07-09, issue #537)

The C2 CHK audit requires byte-exact hash-match of frozen-rows artifacts (the external
held-out task data pinned BEFORE the candidate runs). Redacting path strings inside
these artifacts breaks the sha256 pin; re-pinning breaks the frozen-before law. These
files are restored byte-exact from quarantine, containing absolute Windows project-drive
paths (`drive-letter, colon, backslash, M, backslash, ember` and backslash-escaped forms)
that would normally trigger the `PATHPAT` guard. They are excluded from the paths check
by explicit enumeration in `PATHPAT_EXCLUDE` in `tools/repo-guard.sh`. The operator-name
check still covers these files in full.

- `receipts/ember-d3-native-loop/d3-gym-fresh-rows-offset20-len12-20260708T221652Z.json`
  (sha256: `9acd3496991193c93b9b770322805b5b8769e5e1c77ab54e06a1bc1ebcff35a0`)
  — frozen D3-Gym rows, cited by `d3-native-loop-20260708T221708Z.json`'s
  `fresh_rows_sha256` field; C2 hardening mandates byte-exact match.
  Contains: absolute project-drive paths (build-time anchors in execution context).

- `receipts/ember-d3-native-loop/d3-broader-multifamily-fresh-rows-reconstructed.json`
  (sha256: `51734926408c137a912194fb9142b11a3d485ee9987530a4813e4a9bea488111`)
  — frozen D3-Gym rows reconstructed from prior curation; cited by
  `receipts/ember-d3-native-loop/d3-broader-multifamily-loop-leg2/d3-generalized-candidate-receipt.json`
  as a pinned frozen-rows artifact; C2 hardening mandates byte-exact match.
  Contains: absolute project-drive paths (dataset/benchmark receipt references).

## EMBER-01 completion evidence pack (2026-08-04, issue #1401)

The completion evidence pack under `receipts/ember-01-completion/evidence-pack-v1/`
and the launch-authority artifacts under `receipts/ember-02-launch-authority/` are
machine-emitted receipts copied into the repository verbatim, so the same path-leak
class applies to them. Two were redacted; two are hash-pinned and were excluded
instead. Both dispositions are recorded here.

**Redacted (token substitution, no other byte changed):**

- `receipts/ember-01-completion/evidence-pack-v1/verify-run-receipt-20260804.json`
  — one `worktree_path` value carrying the operator's home directory (drive letter,
  a `Users` segment, the account name) replaced with `<USER_HOME>`; the
  repo-irrelevant remainder is kept, matching the two `<USER_HOME>` files above.
- `receipts/ember-02-launch-authority/sha-binding-map.json` — project-drive paths
  (drive letter, an `M` segment, the repo name) replaced with `<TEMP_WORKSPACE>`,
  keeping the repo-relative remainder. Four entries (`input_authority_sha256`,
  `seat_sha256`, `subject_manifest_sha256`, `tokenizer_sha256`) point into a private
  operator workspace outside this repository, whose directory name is itself
  developer-local context; those paths are elided entirely rather than tokenized with
  their tail. The sha256 each entry annotates is unchanged and remains the binding.

**Hash-pinned frozen artifacts (paths-check exclusions, not redacted):**

Same ruling class as the 2026-07-09 C2 restore above — byte-exact sha256 is
load-bearing, redaction breaks the pin, and re-pinning breaks the frozen-before law.
Enumerated individually in `PATHPAT_EXCLUDE` in `tools/repo-guard.sh`. The
operator-name checks still cover both files in full.

- `receipts/ember-02-launch-authority/certificate.json`
  (sha256: `54882a9a831685e2552fbfce79e4bd35cad0fedb974a6048e16bf7b40ede606e`)
  — the SPINE_CERTIFIED declaration. This digest is its identity: it is cited by
  `declaration-ledger.jsonl` and by `run-spec.json`, and issue #1401 acceptance
  clause 4 requires a stranger to reproduce it from the committed bytes. Contains:
  one `completion_receipt_path` carrying the operator home directory, and
  `execution_scope` custody/artifact roots carrying the project drive.

- `receipts/ember-02-launch-authority/run-spec.json`
  (sha256: `d336f3f79e2116ac9362d5952cb69180c24f6300415c7f8c3089358b6db983a9`)
  — the certified run-spec bound to that certificate. Its `requested_scope` roots are
  compared literally against the certificate's `execution_scope`; redacting one side
  of that comparison and not the other would make a consistent pair read as a
  mismatch. Contains: project-drive custody root, artifact root, and runner-receipt
  path.

The two nine-leg completion receipts in the pack needed no disposition here — they
carry no absolute paths at all. They are, however, enumerated in
`tools/frozen-receipt-exceptions.json` for a different gate (the receipt schema
floor), for the same underlying reason: their sha256 values are cited elsewhere.

## History note

Git history retains the pre-redaction blobs (the redacted commits are new commits, not
a rewrite of history). Un-rewriting history to also purge these blobs is out of scope
per issue #456 — this continues the existing dated risk-acceptance on historical blob
content, same as prior redaction passes (#455 and earlier).
