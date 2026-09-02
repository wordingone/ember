# Deletion manifest — issue #488 first cleanup pass (evidence only)

Status: **evidence, not deletions.** Nothing in this document is deleted by
this PR. It is the reviewed input to a follow-up deletion PR (issue #488
acceptance criteria).

> **Historical record (scanned 2026-07-08).** Every path, count, and location below
> describes the tree as it stood on the scan date; the reference counts and zero-ref
> verdicts were measured against those locations and are deliberately not re-derived.
> The 2026-08-05 docs consolidation (#1441) later moved many of the listed `docs/`
> files into `docs/archive/`, `docs/charter/`, `docs/custody/`, `docs/design/`,
> `docs/ledgers/`, and `docs/ember-restart/` — resolve any listed name against
> `docs/DOCS-README.md`'s current layout.

Scope: `docs/` (205 tracked files) and `scripts/` (601 tracked files),
reference-scanned repo-wide; the untracked receipts on disk; and `.git`
pack-directory cleanliness. Produced 2026-07-08.

## Method

A textual reference scan: every tracked non-binary file's content (~1.1MB
total, 2,272 tracked files) was read into memory once; for each `docs/` or
`scripts/` candidate, every *other* tracked file was checked for the
candidate's basename (and, for longer stems, the filename without
extension). Any hit counts as "referenced" — this is deliberately
conservative in the direction of **under-proposing** deletions, never over.
Full raw results (806 rows: path, reference count, referencing-file sample,
last-commit metadata) are preserved in-session; this document reports the
categorized conclusions.

### Two things the raw scan gets wrong by construction — corrected before categorizing

1. **This repo's local git history is shallow (3 commits total, confirmed
   via `git rev-parse --is-shallow-repository` on both the main tree and
   this worktree).** One of those three commits (`a9d3337`) alone adds
   2,270 files in a single squash-shaped diff. Practical effect: `git log
   -1 -- <path>` returns 2026-07-08 for nearly every file in the repo,
   regardless of the file's true authoring age. **Last-commit date is not
   usable as staleness evidence in this repo right now** — this manifest
   does not use it as a deletion signal, and it should be logged as its own
   hygiene finding (below) rather than silently worked around.
2. **Zero textual reference is not the same as dead**, for two classes
   this repo actually contains:
   - Files discovered by directory-listing/glob rather than named in text
     — e.g. `ember_totality_spec.py`'s `discover_tests()` walks
     `os.listdir(HERE)` for `test_*.py`, and `FILENAME_ID` maps most probe
     filenames explicitly (those *are* caught by the scan), but generic
     `test_*.py`/`*_test.py` files elsewhere are typically pytest-discovered,
     not string-referenced. **32 zero-ref `scripts/` files matching
     `test_*.py`/`*_test.py`/`*_test.ts` were excluded from candidacy** on
     this basis.
   - One-shot experiment-arm driver scripts, invoked directly by an
     external MCP/CLI call (`train_start`-style) rather than imported or
     linked from another tracked file. Confirmed example:
     `src/ember/governance/scripts/w2_garm_runner.py` is zero-ref by this scan yet is the
     subject of the *same-day* tracked commit "W2 G-arm runner spec filed
     (#113)" — its coordination lives in a GitHub issue, not a tracked
     doc. Several multi-arm comparison families (`g1_r1w_*` / `g1_r2w_*`,
     `r2d_*`, `t2_r1_*` / `t4_r1_*`) are siblings in a designed arm
     comparison (control vs. grpo vs. mtp vs. sft, etc.), not sequential
     superseding versions — deleting one arm's driver would destroy the
     ability to reproduce that arm's receipt. These are **not proposed for
     deletion**; see the "flagged, not proposed" bucket below.
   - **3 board-receipt JSON files live under `scripts/ember_totality/
     receipts-totality/` and `receipts-parity/`**, outside the canonical
     `receipts/` tree, and were excluded from script-deletion candidacy
     entirely (they are receipts, not scripts — protected under GOVERNANCE
     §9 rule 2 if cited by the chain-verify mechanism). Their location is
     flagged as a separate structural finding, not a deletion.

## A. `docs/` — 205 tracked, 52 zero-reference

Of the 52, one (`docs/domains/governance/archive/pre-restart/index.md`) is a repo entry point — by nature
everything links *from* it, nothing links *to* it by filename; excluded as
a structural false positive, not proposed.

The remaining 51 were checked for self-declared supersession language
(`supersed|deprecat|obsolete|no longer used|replaced by`, case-insensitive)
against their own content. **Zero matched.** One near-miss is worth naming
because it shows the check working correctly: `docs/launch-target-
multimodal-reconciliation.md` contains the word "superseded" — but in
context it is describing a *different* fork condition ("the pre-staged
launch machinery targets a run the current goal has superseded") inside a
doc that self-identifies as an active "gating amendment... binds the
pretrain readiness gate." It is zero-ref and about supersession, but it is
not itself superseded — a clean illustration of why "mentions supersession"
and "is superseded" must not be conflated.

**Category: DELETE-CANDIDATE (docs) — none.** No doc met both the
zero-reference bar and a verifiable supersession story.

**Category: CONSOLIDATE-INTO-\<target\> (docs) — none identified.** A
version-suffix family check (`-v0`/`-v1`/`-v2`... stems appearing more than
once) across all 205 tracked docs and scripts found **no duplicate-stem
families** — every versioned spec file currently has exactly one edition on
disk. Rule 1 ("keep at most the live version + frozen prereg editions")
has no current violation to act on.

**Category: KEEP — zero-reference, no supersession story (flagged for
owner triage, not proposed):** 51 files. Representative clusters rather
than a flat dump, since most share an obvious grouping:

| Cluster | Count | Files |
|---|---|---|
| `docs/research/*-2026-06-10.md` same-day research notes | 6 | `bottleneck-conversion`, `cosmos3-read`, `exteroception`, `non-compute-accelerators`, `receipt-delta-analysis`, `d6-vram-pricing-note-20260706` |
| `docs/research/drafts/*` explicit draft status | 2 | `fp1-smaller-core-draft.md`, `wsl-9p-probe-draft.md` |
| `docs/verification/receipts-20260706/` July-6 verification bundle (raw terminal-snapshot artifacts + `_steplog.json`, tracked under `docs/` rather than `receipts/`) | 19 | `bisect/*.txt` (12), `resize-probe*/*.txt` (7), `chat-input-race-repro.md`, `drive-213x35/_steplog.json` |
| Companion narrative docs for the same bundle | 2 | `docs/domains/governance/verification/ember-cli-deploy-250-acceptance-20260706.md`, `docs/verification/ember-cli-live-board-20260706.md` |
| Single-file zero-ref docs, no family | 22 | `c-e2b-tie-diagnosis-20260705.md`, `c04-gate-time-playbook.md`, `c04-muon-ceiling-analysis.md`, `custody-disposition-20260708.md`, `design/c14-mechanism-dossier-20260703.md`, `doc-freshness-protocol.md`, `goal-coverage-matrix-20260705.md`, `growth-operator-compile-target-decision.md`, `paradigm-flip-register.md`, `research/floor-probes-20260611/bias_analysis.py`, `research/floor-probes-20260611/final_verdict.md`, `research/fp21b-132-scope-under-fp26.md`, `research/fp27-round1-prereg.md`, `research/fp29-kill-synthesis-reconciliation.md`, `research/p4-clean-corpus-map-v1.md`, `sp6b-replay-rig-v0.md`, `stage1-status.md`, `superpowers/plans/2026-06-16-stage1-first-words.md`, `launch-target-multimodal-reconciliation.md` (see note above — actively gating, do not propose) |

Note on the `docs/verification/receipts-20260706/` cluster (21 files
including its 2 companion docs): the raw artifacts and their narrative docs
are almost certainly mutually cross-referenced in prose without repeating
exact filenames (the scan only matches literal basenames) — this reads as
one cohesive, 2-day-old acceptance-verification bundle, not 21 independent
orphans. It is flagged as **one consolidation unit** for a future pass, and
also flagged structurally: raw per-terminal-snapshot evidence tracked under
`docs/` rather than `receipts/` is the same location-drift pattern as the
scripts-side finding above.

## B. `scripts/` — 601 tracked, 142 zero-reference raw → 107 after excluding false-positive classes

Excluded: 32 test-discovered (`test_*.py`/`*_test.py`/`*_test.ts`), 3
misplaced board-receipt JSON (see Method). Remaining 107 real candidates
were checked for self-declared supersession/proxy/placeholder language.

**Category: DELETE-CANDIDATE (scripts) — 1, high confidence:**

| File | Evidence |
|---|---|
| `scripts/fp33_e3_gemma_e2b_smoke.py` | Zero repo-wide references. Its own docstring self-identifies as a stand-in: *"PROXY (this run): Qwen/Qwen2.5-Coder-3B-Instruct... Establishes harness plumbing... until Gemma4 runs"* (blocked on a transformers-version gap). The sibling script `scripts/fp33_e3b_gemma_e2b_proper.py` (also zero-ref, same ticket) explicitly states in its own docstring: *"Ticket: FP33-E3-GEMMA-E2B-SMOKE (proper run, **supersedes E3-plumbing proxy**)"* and runs the real `google/gemma-4-E2B-it` model the proxy was standing in for. Superseded-by: `scripts/fp33_e3b_gemma_e2b_proper.py` (kept — it is the current, real-model evidence producer for the same ticket). |

No second case reached this bar. Every other zero-ref script either (a) is
a distinct arm in a designed multi-arm comparison (deleting it destroys
that arm's reproducibility, not "dead weight" — e.g. `g1_r1w_{a,base,
control,grpo}`, `g1_r2w_{base,control,grpo,mtp,sft}`, `r2d_{control,grpo,
mtp,sft,sft_dry}`, `t2_r1*`/`t4_r1*` variants), or (b) is a one-off
sweep-candidate driver with no internal claim of being superseded (`c04_
design_*` 5 files, `density_ab_*` 4 files, `fp3x_*` ~14 files), or (c) is
current/in-flight per external evidence (`w2_garm_runner.py`, confirmed
against issue #113 — see Method).

**Category: CONSOLIDATE-INTO-\<target\> (scripts) — none beyond the one
DELETE-CANDIDATE pair above**, which is really a 2-file consolidation
(delete the proxy, `fp33_e3b_gemma_e2b_proper.py` is the surviving target)
rather than a distinct case.

**Category: KEEP — zero-reference, no supersession story (flagged, not
proposed):** 106 files, clustered by naming family for reviewability:

| Cluster | Count |
|---|---|
| `c04_*` design/compile/harness sweep | 8 |
| `density_ab_*` ablation arms | 4 |
| `g1_r1w_*` / `g1_r2w_*` multi-arm eval drivers | 9 |
| `r2d_*` round-2 arm drivers | 5 |
| `t1_*` / `t2_*` / `t4_*` / `t5_*` sweep + selftest drivers | 24 |
| `fp2x_*` / `fp3x_*` / `fp4x_*` floor-probe drivers | ~19 |
| `w1_*` / `w2_*` / `w4_*` window-lane drivers and selftests | 9 |
| `ember_*_selftest.py` component selftests | 6 |
| Single-file, no family | remainder |

Full 107-path list (with the 1 DELETE-CANDIDATE marked) is preserved from
the scan and available on request; this table reports categorized counts
per issue #488's own instruction ("counts + rules, not per-file listing"
for the bulk of a triage) while still naming every file that IS proposed
for action, per file, above.

## B2. Directed addition — `tools/ember-cli/` (outside the docs/scripts scan scope)

Flagged by the feed485 lane, cross-checked against PR #491's review, and
independently re-verified here against a clean `public/master` snapshot
(taken post-#491-merge) before inclusion:

| File | Evidence |
|---|---|
| `tools/ember-cli/src/components/activity-pane.ts` | Fully-formed component (relative-time formatting, glyphs, `watchActivityLog`). Zero imports anywhere in the tracked tree — the only repo-wide text hit for its own filename is its own header comment. No test file (compare its replacement, which has `activity-feed-pane.test.ts`). Its data source, `state/activity/activity-<date>.jsonl`, does have a writer — `scripts/lib/activity_log.py`'s `emit()` — but `emit()` is called only from two test files (`test_activity_pty_smoke.py`, `test_board_runner_emit.py`); no production code path ever calls it, and no `activity-*.jsonl` file has ever existed on disk. **Superseded by** `services/activity-feed.ts` + `components/activity-feed-pane.ts` (merged the same day, PR #491), which read a different, actually-wired data source (`state/activity-ledger.jsonl`). This is a second confirmed instance of issue #485's named "keyframed flame" pattern — a fully-formed rendering surface wired to a data source nothing in production ever populates. #485 quotes the constitution directly on this exact failure mode: *"a keyframed flame is a fabricated receipt in visual form."* |

## C. Untracked receipts on disk — measured 5,262 (issue cited ~1,637)

Measured against the **main tree** (the primary checkout, not an isolated
worktree — a fresh worktree checkout only ever contains tracked files, so
untracked receipts are invisible there by construction). `receipts/` on disk: 6,201
files; tracked: 939; untracked: 5,262. The issue's own count (~1,637) was a
snapshot from earlier the same day — the untracked figure has grown ~3.2×
since, entirely from one source:

| Bucket | Files | Evidence | Proposed disposition |
|---|---|---|---|
| `receipts/ember-m10-surface3/**/.avir/plugins/marketplaces/claude-plugins-official/` | 5,232 (12 × 436, byte-identical clone repeated 12 times across 12 sandbox timestamp runs) | Not receipt evidence at all — a full third-party plugin-marketplace repo clone, incidentally captured inside a sandboxed test-harness "home directory" snapshot. Zero references from any board probe, doc, or claim. Not gitignored (no `.gitignore` pattern covers `receipts/ember-m10-surface3/` today, confirmed). | **DELETE** (not annex — this was never receipt content; it is test-fixture leakage that happened to land under `receipts/`). Recommend also gitignoring the pattern so it stops silently regrowing. |
| `receipts/ember-m10-surface3/**` other captured paths (`scratch-*`, nested `.avir/projects/`) | 23 (git-ignored, invisible to plain `git status`; found via `--ignored`) plus one entire additional snapshot directory (`2026-06-28T05-30-45-Z/`) already excluded by an existing ignore rule | Same sandbox-snapshot source as above. | **DELETE** alongside the bucket above (already gitignored, so no `.gitignore` change needed for this slice — just disk cleanup). |
| `receipts/.rung2-event-cache/*.pt`, `receipts/.p5_dryrun_tmp/*.pt` | 4 | Dot-prefixed, self-named "cache"/"tmp" — torch tensor intermediates from the active rung2/p5 tracks, dated today. Not receipts by naming or by content (raw tensors, no JSON receipt schema). | **DELETE** once the owning run confirms it no longer needs the cache (these are working-directory scratch, not evidence — recommend the producing scripts write these outside `receipts/` entirely, or gitignore the two directories). |
| `receipts/ember-d3-native-loop/*.json` | 2 | Genuine JSON receipts, created same day as this scan (2026-07-08). Uncited so far, but far too new to judge against the 30-day annex threshold. | **KEEP — pending.** Revisit at the next quarterly sweep; do not annex or delete anything under 30 days old. |

**Total m10-surface3 sandbox-snapshot footprint alone: 5,255 files — 99.9%
of the untracked total**, none of it evidence, all of it safely disk-only
cleanup (no citations exist to break).

## D. `.git` orphaned temp packs

`.git/objects/pack/` contains 4 files matching `tmp_pack_*` (not
`pack-<sha>.pack` — these are never git's final pack name and are never
referenced by any `.idx`, ref, or the pack index; git leaves them behind
only when a `repack`/`gc`/`fetch` is interrupted):

| File | Size | Date |
|---|---|---|
| `tmp_pack_8BAQE2` | 1,659,126,952 B | Jul 2 |
| `tmp_pack_WrGzYH` | 1,767,785,640 B | Jul 3 |
| `tmp_pack_EjjwV5` | 894,697,484 B | Jul 5 |
| `tmp_pack_XQiOsU` | 1,283,325,964 B | Jul 8 |

**Total ≈5.6 GB reclaimable, zero risk** — these are guaranteed-orphaned
scratch, not tracked content, so they don't even require a reviewed PR to
remove (they aren't part of any commit, branch, or working tree); flagged
here per issue #488's explicit "prune `.git` tmp packs" instruction, dated
across four separate interrupted operations spanning a week — itself a
signal that whatever is running `repack`/`gc`/`fetch` concurrently across
this repo's many worktrees is being killed mid-operation repeatedly and
worth a separate look.

## Summary

| Item | Count |
|---|---|
| DELETE-CANDIDATE, docs | 0 |
| DELETE-CANDIDATE, scripts | 1 (`fp33_e3_gemma_e2b_smoke.py`, superseded by `fp33_e3b_gemma_e2b_proper.py`) |
| DELETE-CANDIDATE, `tools/ember-cli/` (directed addition, B2) | 1 (`activity-pane.ts`, superseded by `activity-feed.ts` + `activity-feed-pane.ts`, PR #491; second confirmed instance of issue #485's "keyframed flame" pattern) |
| CONSOLIDATE-INTO-\<target\>, docs/scripts | 0 distinct (the 1 delete above is itself a 2-file consolidation) |
| KEEP — zero-ref, flagged for owner triage, not proposed (docs) | 51 |
| KEEP — zero-ref, flagged for owner triage, not proposed (scripts) | 106 |
| Untracked receipts proposed for DELETE (disk cleanup, zero citations) | 5,259 (5,255 m10-surface3 + 4 cache/tmp) |
| Untracked receipts KEEP-pending (too new to judge) | 2 |
| `.git` orphaned tmp packs, reclaimable | 4 files, ≈5.6 GB |
| Structural findings (location drift, not deletions) | 2 — board-receipt JSON tracked under `scripts/ember_totality/` instead of `receipts/`; raw verification artifacts tracked under `docs/verification/receipts-20260706/` instead of `receipts/` |

Everything in the DELETE/CONSOLIDATE rows above is evidence for the
follow-up deletion PR only — nothing is deleted here.
