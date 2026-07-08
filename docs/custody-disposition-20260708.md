# Custody disposition record — permanently-absent cited receipts (#415 ruling item 8)

This file is the permanent, dated record for every currently-cited receipt path this repo will
**never restore to disk**. It exists per the #415 DESIGN RULING's item 8 ("Honest residue... STAY
`cited_missing`; they get a dated disposition note in docs — not receipt edits — receipts are
append-only") and per PR #432's Disclosure 1, which deferred exactly this note for its 3 withheld
files. Nothing in this file edits, deletes, or backdates any receipt. It is a citation registry:
read it before treating any path below as a fresh custody violation to chase.

- Governing issue: [#415](https://github.com/wordingone/ember/issues/415) — 4-bucket enumeration
  (a=relocation, b=genuinely-lost, c=never-existed, d=extraction-artifact) + DESIGN RULING.
- Governing PR: [#432](https://github.com/wordingone/ember/pull/432) — landed 13 of 16
  git-recoverable receipts, withheld 3, disclosed the resulting C(-1) regression.
- Current probe verdict (this worktree, fresh checkout of `public/master` @ `5077a06`, run
  2026-07-08):

  ```
  RED C-CUSTODY: 15 custody violation(s) detected; untracked=0 unparseable=0 cited_missing=15
  pattern=45 relocated=4 documented_absent=0 annex_attested=10 pending_landing=0
  ```

  Sidecar: `scripts/ember_totality/receipts-custody/custody-20260708T103129Z.json`. All 15 rows
  below are read directly from that sidecar's `failures.cited_missing` array — this note accounts
  for all 15, not a sample.

## How to read this note

Each row is one cited-but-absent path. Every row carries: the disposition **class**, the
**evidence** for that class (git log, on-disk diff, or a prior receipt), and the **standing rule**
for anyone who cites this path again. A citation of a disposed path in a *new* receipt is a defect
in that new receipt, not in this one — see the closing section.

---

## Class 1 — BARRED-AT-HEAD-BY-CONTENT-RAIL (3 rows)

These 3 are the files PR #432 verified as git-recoverable (bucket b) and then explicitly withheld.
Their content trips repo-guard's operator-name/local-path rail (pre-dates the public-workbench
era). Per PR #432 Disclosure 1: no carve-out, no edited/redacted substitute (would violate
append-only/zero-edits), no annex-attestation row, no backdated sidecar. Restoration is
**permanently declined**. The blobs remain recoverable from git history only — never from HEAD.

| # | Cited path | Historical commit | Blob sha (`git ls-tree`) |
|---|---|---|---|
| 1 | `receipts/ceff-closure-gate9-shatter-bf16ns5-20260623T132000Z.json` | `6c9b3d74c35b010ea69516d8240de9c634b613a4` | `8489cadb200ec407edd091e057907de5fcba68bc` |
| 2 | `receipts/ceff-shatter-REPUDIATED-20260623T170000Z.json` | `4e1f32541e28bccc4899ac7b88b6f7ead41e6ad7` | `aff104aa698269d4b1333337a459ae13f92f3c6c` |
| 3 | `receipts/governor-repair-080-20260702T180248Z.json` | `530c5b3123d62e7f00e9dc9f640d764aae7efb1a` | `6fa6edb1d783e833c6f599b30c9f02031e5d0e1c` |

**Ruling (unchanged from PR #432):** barred from HEAD by the operator-name/local-path rail;
recoverable-in-principle via `git show <sha>:<path>` for forensic/audit purposes only; never
lands on `public/master`. This note is their permanent record.

**Correction to PR #432's count reasoning:** the PR text states governor-repair-080 "is a withheld
direct-restoration target that nothing else cites, so it doesn't appear in this count." That
parenthetical is factually wrong, and this note corrects it rather than repeating it. A direct
citer exists and pre-dates PR #432: `receipts/c9-cadence/code-vs-docs-20260702T180521Z.json`
(landed via commit `716c96c`, merged PR #379, 2026-07-07 — one day before PR #432). That citer is
exactly why `governor-repair-080` legitimately re-appears in the current 15-row
`cited_missing` list; its presence is not an anomaly.

---

## Class 2 — CROSS-TREE LINEAGE, NON-CANONICAL (2 rows)

PR #432 characterized these two as "newer citations that appeared after the enumeration snapshot
... unrelated to this PR's scope." That framing undersells what they are. Both paths **do** have
git blobs — but only on commits that are provably **not ancestors of `public/master`**
(`git merge-base --is-ancestor <sha> public/master` returns non-ancestor for both, verified in
this session), reachable only through the `goalforge` remote/lane lineage fetched into this
worktree (`goalforge/definitive-goal-20260701` and assorted `lane/*` branches).

| # | Cited path | Non-ancestor commit(s) | Confirmed NOT on `public/master` |
|---|---|---|---|
| 4 | `receipts/cgrow-superseded/cgrow-receipt-20260628T061735Z.json` | `fa49af42c9541a064980e68421acb28db2550a1e`, `d5d02a34b0b6837bc8a68746c8b8d20d3d36314e` | yes |
| 5 | `receipts/stale-figure-adjudication-20260702T151929Z.json` | `83ac6bfc8b2fda788a3180dd146cd5c57228f8dc` | yes |

**Evidence for the "non-canonical" ruling, not just "absent":** commit `fa49af4`'s own message
discloses the standing policy that governs this class: *"the pre-gate historical receipts whose
original content carries cross-tree lineage (receipts never edited — LOCAL-ONLY under the
off-site backup discipline)."* The `goalforge` tree is a related-but-distinct lineage from
`public/master` (standing discipline: `wordingone/ember` is the single source-of-truth tree);
content that exists only on that separate lineage is deliberately not merged into the canonical
public repo.

**Ruling:** restoration from a non-canonical, cross-tree lineage is out of scope for #415/#432 —
not because the content doesn't exist, but because merging it would violate the single-tree
custody discipline these citations already presuppose. These stay `cited_missing` on
`public/master` by design, and this note is their record rather than a future restoration PR.

---

## Class 3 — MIS-ROOTED CITATION, ZERO-TRACE (2 rows)

The citation's own extraction is wrong (a known `_extract_citations` defect class from the #415
enumeration: `receipts/` matched as a substring inside a longer real directory name, dropping the
true prefix). Unlike the 16-row extraction-artifact bucket already cured elsewhere, correcting the
root here does **not** reveal a real file — the correctly-rooted path never existed either.

| # | Cited path | What the citing receipt's own field actually says | Verified absent (0 git hits, not on disk) |
|---|---|---|---|
| 6 | `receipts/nck-event-mail-mail_arrived-15038-20260612T210139Z.json` | `state/nck-event-receipts/nck-event-mail-mail_arrived-...json` | yes, both roots |
| 7 | `receipts/wheel/wheel-real-20260618T143007Z.json` | `official-wheel-runner/wheel/receipts/wheel/wheel-real-20260618T143007Z.json` | yes, both roots (no `official-wheel-runner/` directory exists anywhere in the tree) |

Citers: `receipts/c10-resident-live-20260612T213002Z.json`,
`receipts/c10-resident-live-20260612T213133Z.json` (row 6);
`receipts/ember-mvp/cycle-official-runner-bound-20260618/cycle-20260617T000000Z-0001.json` (row 7).

**Ruling:** stays `cited_missing` permanently. The mis-rooting is a citer-side defect (flag for
whoever next touches those 3 citing receipts' generators), but no disk artifact exists at any
candidate root, so there is nothing to restore.

---

## Class 4 — DECLARED-BUT-UNVERIFIED OBSERVATION CHAIN (7 rows)

This class is **refined beyond the #415 enumeration's original account** by a receipt that landed
after that enumeration and before this note: `receipts/ember-preloop-resident-gate/reference-uiux-ax-observation-VOID-20260707T112100Z.json`
(filed 2026-07-07, citing issue #349 / PR #348). Where the #415 comment said "no trace anywhere...
a different, real observation event exists... this cited attempt is a separate, never-landed
run," the VOID receipt did the actual forensic work and found something more precise.

| # | Cited path |
|---|---|
| 8 | `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-adapter-trace.log` |
| 9 | `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-meta.json` |
| 10 | `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-process-after.json` |
| 11 | `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-stub-server-log.jsonl` |
| 12 | `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z-terminal-transcript-clean.txt` |
| 13 | `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z.json` |
| 14 | `receipts/ember-preloop-resident-gate/reference-cli-full-parity-harness-gate-20260622T141500Z.json` |

**VOID receipt's finding, rows 8-13:** the on-disk file with the matching timestamp is
`receipts/ember-preloop-resident-gate/reference-uiux-ax-observation-20260622T151722Z.json` (no
`real-` prefix; sha256 `09cc93b9a40aa91e894f1ce36a312fb11cf43707e3152577c5e7e5c3458fd80e`,
re-verified byte-identical in this session). That file's own `evidence_files` section cites its 5
sidecars under the `real-`-prefixed basenames (rows 8-12) — none of which were ever written to
disk. The near-name candidates that **do** exist (same basenames, no `real-` prefix) were
independently re-hashed by the VOID receipt: **5/5 hash mismatches** against the receipt's own
claimed sha256 values. This rules out the cheap fix (strip the stray `real-` prefix and point at
the near-name file) — the content at the corrected name is demonstrably *different* from what the
receipt claims, not just differently-named. Row 13 (the main file, cited under the `real-` prefix
by three other receipts: `docs/goal-archive-v1-full.md`,
`receipts/ember-preloop-resident-gate/full-parity-harness-gate-20260622T152000Z-final.json`,
`receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-final.json`) was
never written under that claimed identity at all. **Disposition: VOID via supersession** (receipt
on file, dated 2026-07-07) — the original unprefixed file is untouched on disk, nothing deleted or
edited, per issue #349's disposition discipline.

**Row 14 — same defect signature, not yet formally voided.** `reference-cli-full-parity-harness-gate-20260622T141500Z.json`
is cited but the on-disk file at that timestamp is
`receipts/ember-preloop-resident-gate/full-parity-harness-gate-20260622T141500Z.json` (no
`reference-cli-` prefix). That file's *own* `out_path` field self-declares
`receipts\ember-preloop-resident-gate\reference-cli-full-parity-harness-gate-20260622T141500Z.json`
— a name it was never actually saved under. Two downstream receipts
(`full-parity-harness-gate-20260622T154500Z-blocked.json`,
`resident-training-gate-20260622T145000Z-full-parity-reconciled.json`) then cite that same
never-written prefixed name, propagating it. This is the identical
self-declared-`out_path`-vs-actual-saved-filename defect as rows 8-13, one file over in the same
directory and the same 2026-06-22 chain — but no VOID receipt has been filed for it yet.

**Ruling:** rows 8-13 are disposed (VOID, receipt on file — this note cites it, does not
duplicate it). Row 14 stays `cited_missing` and is flagged here for the cure lane to void under
the identical mechanism (issue #349 / PR #348 precedent) rather than treated as a fresh mystery.

---

## Class 5 — UNCONFIRMED CLI TARGET (1 row)

| # | Cited path |
|---|---|
| 15 | `receipts/ember-c-scale/w2-heldout-decontam-20260707T055843Z.json` |

Appears only as a `--decontam-receipt` command-line argument value inside 4 real receipts
(`receipts/ember-c-scale/w1-certification-check-20260707T114707Z.json`,
`receipts/ember-c-scale/w1-collapse-control-20260707T110256Z.json`,
`receipts/ember-c-scale/w1-collapse-control-20260707T135344Z.json`,
`receipts/ember-c-scale/w1-launch-receipt-20260707T110231Z.json`). Zero git history, zero
spend-annex row, not on disk. The value is a recorded launch parameter, not a file any run is
independently confirmed to have produced.

**Ruling:** stays `cited_missing`. Not a citation-extraction defect (the string is exactly what
the citing receipts recorded) — the open question is whether the W2 held-out decontam run that
would produce this file ever completed. That is a W2-track question, not a custody question; this
note records the citation's disposition (permanently absent pending that run), not the run itself.

---

## Reconciliation with the current probe emit

`untracked=0 unparseable=0 cited_missing=15 pattern=45 relocated=4 documented_absent=0
annex_attested=10 pending_landing=0` — all 15 `cited_missing` rows are accounted for above (3 + 2
+ 2 + 7 + 1 = 15). `relocated=4` and `annex_attested=10` correspond to PR #432's bucket (a)
relocations and the annex-attested subset of bucket (b); neither bucket is re-litigated here since
neither is `cited_missing`. No row in this note's enumeration is unexplained.

## What a future reader must do before citing any path in this note

1. **Check this note first.** If a path you are about to cite (or investigate as a "new" custody
   violation) appears in one of the 5 classes above, it is disposed — read the ruling before
   opening a new investigation.
2. **A citation of a disposed path in a NEW receipt is a defect in the citing document**, not a
   reopening of this disposition. File it against the citer, not against this note or against
   `test_c_custody.py`.
3. **This note never overrides a later VOID/supersession receipt.** If a path here is
   subsequently voided by its own dated receipt (as rows 8-13 already were, one day before this
   note), the VOID receipt is authoritative for that path; this note's job is to point to it, not
   to duplicate or freeze its reasoning.
4. **Nothing here is edited if a class turns out to be wrong.** A correction to this note's
   classification is a new dated note (or a dated amendment section appended here), never a
   silent edit — matching the append-only discipline every receipt in this repo already follows.
