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

Three test files deliberately embed a leaked-path-shaped literal as adversarial input,
specifically to prove the app's own sanitization/redaction/clipping logic strips
exactly this shape. Redacting the fixture string would make the assertion it exists to
test vacuous (e.g. an assertion that a certain org-token substring is absent from the
sanitizer's output is meaningless if the input never contained that substring to begin
with). These are excluded by name from `repo-guard.sh`'s path check (see
`PATHPAT_EXCLUDE` in `tools/repo-guard.sh`), the same mechanism the guard already used
to exclude itself:

- `scripts/test_w1b_continuation.py`
- `tools/ember-cli/src/core/monitor-render.test.ts`
- `tools/ember-cli/src/components/homescreen-mock1-parity.test.ts`

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

## History note

Git history retains the pre-redaction blobs (the redacted commits are new commits, not
a rewrite of history). Un-rewriting history to also purge these blobs is out of scope
per issue #456 — this continues the existing dated risk-acceptance on historical blob
content, same as prior redaction passes (#455 and earlier).
