# Issue #565 resident-colleague conservation

Status: `SUPERSEDED_NOT_PLANNED`

## Ruling

Issue #565's duplicate historical resident-colleague carrier is superseded by
canonical EMBER-03. Existing prompt, transcript, activity, goal, and spinner
components are implementation evidence; they do not prove that the complete
live A-E experience gate or responsive-session gate has executed.

## Lossless current-owner transfer

Canonical owner: [EMBER-03/#1117](https://github.com/wordingone/ember/issues/1117).

Accepted transfer: https://github.com/wordingone/ember/issues/1117#issuecomment-5224506525

The accepted transfer preserves:

1. **Always-visible input.** Keep the bottom-anchored, always-visible,
   focus-safe prompt with cursor and width-bounded behavior.
2. **Conversation spine.** Keep operator turns and streamed resident replies
   in one independently scrolling conversation transcript on the same rendered
   surface.
3. **Visible work.** Keep real edge-triggered work visible from canonical
   receipt, board, watchdog, goal, tool, and run events; keep the current
   objective and current step visible; forbid fabricated or demo activity.
4. **Reasoning/quiet forge.** Keep an honest quiet-forge or generation state. A
   spinner or one truthful status line is allowed; silent-screen success and
   synthetic ticks are forbidden.
5. **Experience gate.** Use the current installed binary at the operator's
   half-screen viewport; preserve exact 80x24 -> 40x24 -> 80x24 live
   resize/reflow and restoration, 190x85 readback, same-window field-exemplar
   comparison, stranger/independent judgment of at least 8, exact
   source/executable/session/journal/telemetry/frame custody, and a
   machine-minted receipt.
6. **Negative evidence.** Preserve malformed, stale, replayed, foreign,
   missing, interrupted, deletion, failure, wedge, and rollback negatives.
7. **Responsive-session gate.** Preserve at least three completed sessions, at
   least two prompt classes, and at least two current-public-build launches,
   with counted-session wedge or zombie failures excluded and disclosed.

The #561 dependency retains locked banner/input behavior, edge-triggered
watermark/coalescing, restart with zero replay, one planted new receipt
producing exactly one event, and bulk materialization producing one bounded
summary. It remains dependency evidence only, not #565 completion.

Accepted canonical substrate remains the #1117 transfers for same-window field
parity (#12), geometry/readback (#894), live telemetry identity (#140),
machine-minted operator sessions (#154), and durable goal/journal behavior
(#200). Those owners preserve the evidence law but do not execute #565's A-E
acceptance.

## Architecture and claim boundary

Current Ember Lab, Ember CLI, the goal store, activity journal, telemetry, and
receipt/custody paths remain the sole authority. This ruling creates no
parallel dashboard, daemon, launcher, scheduler, activity loop, or receipt
family.

`NO_NEW_PARALLEL_AUTHORITY`

No live A-E acceptance, session score, capability, training, checkpoint,
sufficient-pretraining, or milestone-completion credit is claimed.

## Rollback

Revert this conservation document and reopen #565 if the accepted public
transfer is not posted, is rejected, is removed, is narrowed, or becomes
detached from the canonical EMBER-03 certificate.
