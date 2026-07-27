# Ember CLI Prompt Input Border Design

## Status

Approved under delegated operator authority on 2026-07-25. This design is the
narrow current-master successor to stale PR #806 for issue #243.

## Problem

At public master `9835eb53cb22eeebdfc3c69445a8a8c123e8772c`,
`PromptInput` renders a dim horizontal rule, the prompt row, and another dim
rule. The real `StatusLine` is a separate sibling in `screens/repl.ts`. The
operator therefore does not receive a closed input affordance and the status
row is not attached to the input region.

Issue #243 requires:

- a rounded, closed input region spanning the available main-column width;
- the prompt glyph and input text inside it;
- the status/mode row anchored to it;
- correct live resize behavior; and
- a LIVE receipt from the compiled binary.

## Scope

### Included

- Replace the two dim rules with the existing design-system rounded panel
  border.
- Keep transient notifications and the processing shimmer outside the border.
- Keep the stash notice, input row, queue preview, overflow row, and real
  `StatusLine` inside the border.
- Preserve the current input state, cursor, suggestion, queue, keybinding, and
  transcript behavior.
- Recompute the horizontal input viewport after subtracting the two border
  columns, two padding columns, and the two-column prompt prefix.
- Verify element structure, real terminal paint, and the compiled-binary
  80-to-40-to-80 resize sequence.

### Excluded

- PR #806's compact tool-result digest.
- PR #806's stale issue-#242 prose.
- Any reusable `InputPanel` extraction.
- Any change to model, training, telemetry, transcript, or operator-surface
  behavior.
- Issue closure before the compiled-binary LIVE receipt is public.

## Component Contract

`PromptInputProps` gains:

```ts
statusLine?: React.ReactNode;
```

`screens/repl.ts` constructs the existing `StatusLine` exactly as it does on
current master and supplies it through this prop. The separate sibling
`StatusLine` is removed. `showStatusLine: false` remains at the REPL call site
so the legacy internal permission-only line does not duplicate the real status
component.

The returned tree has this order:

```text
notification(s)          outside
processing shimmer       outside
rounded input box        inside:
  stash notice
  prompt/input row
  queue preview rows
  queue overflow row
  real StatusLine
```

The rounded box uses the existing `PANEL_BORDER_STYLE` and the existing primary
interaction color. It has `paddingX: 1`, `width` equal to the supplied
main-column width, `flexDirection: "column"`, and remains under the existing
non-shrinking outer `PromptInput` container.

## Width and Resize Semantics

The content-width calculation is explicit and testable:

```ts
const boxOverhead = 2 /* border */ + 2 /* paddingX */;
const promptOverhead = 2; // glyph plus separating space
const availableCols = Math.max(0, width - boxOverhead - promptOverhead);
```

`computeInputViewport` continues to own cursor-following windowing. A width
below the combined overhead yields an empty text viewport, never a negative
slice. At the required narrow width of 40 columns, `availableCols` must remain
strictly positive. The real paint test must prove all four rounded corners and
both vertical edges remain present at 80, 40, and restored 80 columns.

## Verification

### Focused deterministic tests

- `prompt-input.test.ts` proves the rounded box replaces the two rule rows.
- Notifications and shimmer are outside the bordered node.
- Stash, input, queue, overflow, and supplied `statusLine` are inside it in
  order.
- The box consumes the supplied width.
- Width 40 leaves a positive input viewport and a long input remains
  cursor-windowed.
- Existing cursor, suggestion, queue, and text behavior remains green.

### Real paint test

Mount `PromptInput` through the production reconciler/rendering pipeline at
80, then 40, then 80 columns. Assert the reconstructed terminal rows contain a
closed rounded border, vertical edges, prompt content, and the supplied status
row at every width. Assert the 40-column content span is positive.

### LIVE compiled-binary receipt

After committing clean source, build `tools/ember-cli/src/ember.exe` with the
repository build command. Launch that exact binary in Windows ConPTY at the
operator geometry, capture its raw output bytes, resize 80-to-40-to-80, and
capture each stage separately.

The public receipt must bind:

- exact source commit;
- exact compiled-binary SHA-256;
- exact dimensions for each stage;
- raw output byte files, including escape sequences;
- reconstructed terminal-frame files;
- per-stage proof of all rounded corner and vertical-edge glyphs;
- a strictly positive 40-column content viewport; and
- the capture command and ConPTY implementation.

A component render, screenshot description, or self-declared JSON field is not
a LIVE receipt. Issue #243 stays open until the compiled-binary bytes and their
hashes are attached publicly.

## Failure Behavior

- A missing or malformed status element cannot create a second status row; the
  REPL supplies exactly one existing `StatusLine`.
- Width arithmetic clamps at zero and never throws or produces a negative
  slice.
- A compiled capture missing any stage, raw-byte file, binary hash, corner,
  edge, or positive narrow viewport fails receipt generation.
- No issue closure or visual-capability claim follows from unit tests alone.
