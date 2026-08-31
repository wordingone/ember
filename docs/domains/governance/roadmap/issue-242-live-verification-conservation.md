# Issue #242 live-verification conservation

Status: `SUPERSEDED_NOT_PLANNED`

## Ruling

Issue #242's historical live-verification tracker is superseded by the current
EMBER-03 operator-surface program. The historical tracker may retire only after
the accepted public transfer lands; the complete inventory, installed-binary
evidence, board, drift, parity, and rollback obligations remain current.

## Lossless current-owner transfer

Canonical owner: [EMBER-03/#1117](https://github.com/wordingone/ember/issues/1117).

Accepted transfer: https://github.com/wordingone/ember/issues/1117#issuecomment-5224505314

The accepted transfer preserves every still-valid obligation from #242 and
parity-baseline comment 4894707407:

1. **Enumerated inventory, not sampling.** Derive the complete current-public
   Ember CLI feature surface from production registries and wiring and publish
   its exact count: every slash command; every keyboard binding including mode,
   task, and interrupt controls; input, status, transcript, welcome, resize,
   permissions, diagnostics, themes, errors/degraded states, session management,
   resume/init, goal mode, and every Ember-specific goal, governed-training,
   observatory, lifecycle, telemetry, and homescreen surface. Removed or renamed
   historical controls remain provenance, not current inventory rows. Preserve
   the historical board's 90-row baseline and its `5/35/7/20/14/7/2` category
   distribution as dated provenance only; regenerate the inventory and count
   whenever the deployed feature surface changes.
2. **Fail-closed initial state.** Every enumerated row defaults to `BROKEN`
   until current installed-binary evidence proves otherwise. Unit tests, source
   presence, self-report, synthetic renderer calls, predicted behavior, and
   historical binaries cannot produce `VERIFIED-LIVE`.
3. **Real user-path evidence.** Each feature is driven through the compiled
   current-public Ember CLI in an isolated Windows ConPTY/focus-safe harness,
   never the operator's active window. Each row binds source and executable
   identity, command/input events, observed behavior, timestamp, and screenshot
   or recording at three viewport widths. The operator's half-split left pane
   is primary and every feature includes a live-resize probe where applicable.
   Existing current-source resize and half-screen receipts establish the
   required evidence shape for their exact interactions only; they do not
   establish universal inventory verification.
4. **Canonical board.** A checked-in board maps every inventory row to exactly
   one of `VERIFIED-LIVE` with receipt path, `BROKEN` with an open issue, `STUB`,
   or `DORMANT`. The stated count equals the enumerated inventory; every row has
   either qualifying evidence or an open repair owner; malformed, missing,
   stale, foreign-source, or deleted evidence fails closed. Red rows
   continuously feed the work queue.
5. **Deployment drift.** Re-verification runs after every deployed-binary
   change and binds the installed executable, not merely the source tree. A
   source-level fix whose deployed binary remains broken stays `BROKEN`.
6. **Parity is the floor.** Each feature has a behavior-level side-by-side
   comparison with the current field-standard TUI exemplar. Preserve explicit
   coverage for command breadth; bordered input/autocomplete/paste affordance;
   status model/context/cost/duration/rate-limit truth; formatted and bounded
   transcript/tool rendering; spinners; task progress/TTL/adaptive height;
   plan/fast/effort/vim modes; both-axis resize and virtual scroll; keybinding
   customization; typed errors/rate-limit degradation; resume/rewind/export/
   fork/rename; themes; permission dialogs; and diagnostics.
7. **Ember-specific surfaces use the same bar.** Goal continuation, governed
   training control, cognitive/learning observability, model lifecycle and kill
   receipts, live telemetry, and organism homescreen feeds receive no credit
   without the same installed, current-source, receipt-bound live evidence.
8. **Evidence and rollback.** Preserve negative, interruption, wedge, focus,
   resize, malformed/foreign, deletion, and rollback evidence. A receipt proves
   only the exact interaction it binds and cannot grant training, checkpoint,
   model-quality, capability, sufficient-pretraining, parity, or milestone
   credit to adjacent features.

Canonical ownership remains consistent with accepted EMBER-03/#1117 transfers
for field parity (#12), installed operator/graph surfaces (#894), live telemetry
(#140), operator sessions (#154), and automation/journal behavior (#200). Those
transfers are substrate and do not independently complete this full feature
census.

## Architecture and claim boundary

The current Ember Lab control plane and the existing Ember CLI
input/render/journal/telemetry/custody paths remain the sole authorities. This
ruling creates no parallel feature registry, renderer, harness authority,
receipt family, launcher, dashboard, or policy.

`NO_NEW_PARALLEL_AUTHORITY`

The 2026-07-06 command counts, grades, named old issues, and deployed baseline
are historical measurements only. This transfer does not claim that the
live-verification program, its receipts, feature parity, training, checkpoint,
model quality, capability, sufficient pretraining, or milestone completion
already exists.

## Rollback

Revert this conservation document and reopen #242 if the accepted public
transfer is not posted, is rejected, is removed, is narrowed, or becomes
detached from the canonical EMBER-03 certificate.
