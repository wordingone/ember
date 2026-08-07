# Issue #894 historical-to-current conservation

Status: `SUPERSEDED_DUPLICATE_CURRENT_EMBER_03`

## Ruling

Issue #894 was opened against an older cockpit state in which the right-side training graphs appeared absent and the installed window required manual placement. Current master contains the graph-pane implementation and its source/build acceptance work. The remaining live installed-window, telemetry-truth, interaction, geometry, and screenshot clauses are not discarded; they are accepted by the canonical open EMBER-03 owner in the append-only transfer linked below.

This closes only the duplicate historical issue surface. It does not claim that live training telemetry currently exists or that the installed-binary acceptance campaign has completed.

## Completed implementation surface retained

The historical issue comments record the landed production-shaped correction and tests for:

- contained responsive metric cards with stable metric-family colors;
- bounded chart height and bounded history/render work;
- honest source-unbound/idle/stale/offline presentation;
- plain mouse-operable run controls with keyboard accessibility and no mnemonic direct-letter action dispatch;
- exact executable build evidence from the then-current source.

Those facts remain implementation evidence only. They are not substituted for a current installed-window receipt.

## Lossless current-owner transfer

Canonical owner: [EMBER-03/#1117](https://github.com/wordingone/ember/issues/1117).

Accepted transfer: https://github.com/wordingone/ember/issues/1117#issuecomment-5221636867

The accepted transfer preserves every unresolved clause from #894:

1. exact source/binary/telemetry/terminal identity;
2. operator-confirmed launch geometry and one-window/no-dead-shell readback;
3. current-source chart wiring and honest missing/stale/offline states;
4. bounded responsive cards, including single-column half-screen behavior, colors, labels, scale context, and bounded redraw/history;
5. real clickable and hover-visible controls, keyboard accessibility, removal of mnemonic dispatch, and stable terminal rendering without old-frame scrollback substitution;
6. installed-binary screenshot and content-addressed verification receipt;
7. no inference from UI rendering to training, checkpoint, benchmark, model capability, or milestone completion.

## Architecture and claim boundary

The current Ember CLI telemetry and operator surface remain the only UI authority. Ember Lab remains the current runtime authority. No retired runtime name or path is restored and no second dashboard, launcher, daemon, telemetry path, or receipt family is created.

`NO_NEW_PARALLEL_AUTHORITY`

No GPU run, training run, checkpoint, benchmark, capability, sufficient-pretraining, or milestone-completion claim follows from this conservation ruling.

## Rollback

Revert the conservation commit and reopen #894 if the accepted transfer is removed or narrowed.
