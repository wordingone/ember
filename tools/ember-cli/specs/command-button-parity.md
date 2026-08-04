<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Command-button parity — every registered slash command is clickable

Status: CURRENT

Issue: #1370

Consumer: `tools/ember-cli/src/services/command-buttons.ts`, `tools/ember-cli/src/components/command-bar-pane.ts`

## Operator mandate this node implements

"all commands should have clickable button equivalents like 'start' 'pause' etc. this includes
all slash commands" (2026-08-03). Before this node the cockpit had exactly four mouse-reachable
operations — the LIVE RUN controls `[START] [PAUSE] [RESUME] [RESTART]` — and every other
operation in the registry (`/verify`, `/custody`, `/model`, `/benchmark`, `/train`, `/spine`, …)
was keyboard-only through the prompt.

## The class-kill

The failure this node forecloses is not "some commands lack buttons" but "buttons are a second
list of commands". A hand-maintained button list drifts from the registry the moment a command
is added, renamed, or removed, and the drift is invisible until an operator hunts for a button
that was never written. So the button set is DERIVED, never declared:

`services/command-buttons.ts::buildCommandButtons(commands)` takes the same
`RegistryCommand[]` that `services/slash-dispatch.ts` dispatches against and
`services/slash-dropdown.ts` filters, and emits one `CommandButton` per entry, in registry order,
de-duplicated by name (first occurrence wins — the same precedence `getCommands` applies when a
dynamic command collides with a builtin). Registering a command is the ONLY action required to
give it a button. Nothing in the component or the screen names a command.

## Contract: `services/command-buttons.ts` (pure)

`CommandButton` carries `name`, the `[/name]` label, `enabled` (from `cmd.isEnabled()`),
`needsArgument`, the `argumentHint`, and a `disabledReason`. An `isEnabled()` that THROWS
yields a disabled button carrying the thrown message rather than taking the cockpit render
down — an availability probe reaching a missing file or unset env var is routine, not fatal.

`commandButtonActivation(button)` decides what a click MEANS, and can return exactly three
things:

| result | when | text |
|---|---|---|
| `dispatch` | enabled, no required arguments | `/name` |
| `prefill` | enabled, `argumentHint` declared | `/name ` (trailing space) |
| `rejected` | `isEnabled()` false or threw | the named reason |

The type has no fourth member and no notion of focus. A click is therefore structurally
incapable of producing anything but text to run or text to compose, which is what makes
"buttons never steal typing focus" an invariant of the type rather than a convention a caller
must remember.

### Required arguments are declared on the command, not inferred

`RegistryCommand.argumentHint` (types/command-types.ts) is the single declaration that a bare
`/name` invocation can only be a usage error. `commands/admit.ts` and `commands/designate.ts`
declare it from the SAME constant their `USAGE` line renders, so the hint and the error text
cannot drift. Commands whose bare form does real work (`/model` → status, `/benchmark` → table,
`/verify` → start, `/train` → preflight) leave it unset and dispatch directly on click.

Skills declare the same thing as `argument-hint:` frontmatter, and `skill-framework.ts` carries it
from `parseSkillFrontmatterFields` through `createSkillCommand` onto the command. Parsing a hint
and dropping it before the command object is the failure mode here: it is invisible until a
skill's button fires a bare invocation that could only be a usage error, which is why the
`#1370 — argument-hint frontmatter reaches the registered command` test asserts the resulting
BUTTON CLASSIFICATION (`prefill`), not merely that the field parsed.

## Contract: `components/command-bar-pane.ts`

Renders the button model above the composer, using the affordance the run controls established:
`[...]` shape, green enabled, gray disabled, inverse on hover. Disabled buttons KEEP their click
handler on purpose — the activation returns `rejected` with a reason that renders on the notice
row, so clicking an unavailable command says why instead of behaving like a dead pixel.

### Width and height legibility (DONE-bar acceptance)

- `packCommandBarRows` greedily packs cells into rows of the true content width and NEVER splits
  a label; every row gets at least one whole label even when that label alone exceeds the pane.
  This is the same rule `layoutControlRows` applies to the run controls, for the same reason: the
  layout engine declares `flexWrap` but never implements it, so an over-wide row would otherwise
  be raw-clipped by the enclosing `overflow:"hidden"` box with no marker at all.
- `commandBarPages(buttons, width, maxRows)` bounds the bar's height by PAGING, never by dropping:
  the buttons are split into pages that each fit the row budget, and every page carries a pager
  cell whose own width is reserved inside the budget. The pager is clickable and WRAPS from the
  last page to the first, so every registered command is reachable by mouse at every width in a
  bounded number of clicks. Its caption degrades from `+N more` to a single `›` glyph when the
  pane is too narrow to afford the caption, so no width can produce a page the operator cannot
  leave. `commandBarLayout` is the first page of that split.
  - "Hidden commands remain reachable by typing `/`" is NOT an acceptable fallback and was the
    #1370 review's blocking finding: keyboard-only reachability is the state this issue exists to
    end, so a marker with no click handler fails acceptance no matter how honestly it discloses
    the count. Enforced by `screens/width-sweep-probe.test.ts`, which mounts the real screen at
    40x24 / 60x20 / 80x24 / 100x30 / 140x40 and reaches every command in the LIVE registry using
    real SGR mouse clicks only.
- `commandBarMaxRows(terminalRows)` spends 3 rows at ≥40 rows, 2 at ≥24, and 1 below that: the
  bar is chrome competing with the transcript and never crowds a short terminal.

## Contract: `screens/repl.ts` wiring

- `dispatch` is executed through the SAME `OperatorInjector` the operator pipe uses, so a click
  inherits its keyboard-priority gate: with half-typed text in the composer or a turn in flight
  the command is QUEUED, never injected over what is being typed.
- `prefill` writes `/name ` into an EMPTY composer only; with text already present the usage
  line is surfaced on the notice row instead. A button click is never allowed to destroy typing.
- The bar is suppressed while the slash palette is open — the palette owns those rows and is
  itself a command surface; both at once would be two competing command lists on screen.
- The screen's command-button state (`hoveredCommand`, `commandBarNotice`, the page index) is
  disjoint from the operator surface's `paneFocused` / `focusedControlIndex`. No activation branch
  writes either, so the keyboard path is unchanged by construction.
- The notice row is cleared the moment the operator acts on it — on the next keystroke and on
  submit. A notice describes a command the operator was ABOUT to run; once they have moved on it
  is stale, and it costs a permanent row of chrome to keep saying something untrue.
- The page index is stored WITH the layout signature it was chosen under (pane width, row budget,
  registry command names). A resize or a registry change produces a different signature and the
  index is discarded rather than clamped, so the bar reopens at the first page instead of on a
  page whose commands no longer exist.

## Acceptance

1. Every command in a registry renders a button — asserted against the registry, not a fixture
   list, including a registry mutated at test time (an added command gains a button with no
   change to component or screen).
2. A click on an argument-free command dispatches `/name` through the real injector path.
3. A click on an `argumentHint` command composes `/name ` and dispatches nothing.
4. A prefill click with text already in the composer preserves that text.
5. A click on a disabled command surfaces its reason and dispatches nothing.
6. No activation result can carry focus; the screen's focus state is untouched by every branch.
7. Width sweep: at every tested width no label is split or unmarked-clipped, the row budget is
   honoured, and EVERY registered command is reachable by mouse — directly or through the pager —
   proved by real clicks against the real screen, not by a layout assertion.
8. A skill declaring `argument-hint:` produces a button that composes rather than dispatches.
