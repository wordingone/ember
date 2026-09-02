<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Process-select run control — click-first SELECT PROCESS → START

Status: CURRENT

Issue: #1475 (operator directive 2026-08-05)

Consumer: `tools/ember-cli/src/services/process-select.ts`
Consumer: `src/ember/infrastructure/tools/ember-cli/src/components/start-parameters.ts`
Consumer: `tools/ember-cli/src/services/operator-control-notice.ts`

## Operator mandate this node implements

"all ember-operations although should be do-able via both typed commands, should first and
foremost be proven explicitly via clicking on the buttons, and progressing through dialogues"
(2026-08-05). The prescribed flow, verbatim in structure: SELECT PROCESS sits at the top of the
LIVE RUN panel directly under the state line (the gray "run control" caption it replaces);
clicking it toggles a dropdown dialog at the button; picking a process arms and highlights
START; clicking START "automatically run and process any pre-requisite checks and tests as
needed", then runs the selected job.

## The class-kill

Two failure classes are foreclosed by construction rather than convention:

1. **A second dispatch path.** START never calls into training, launch, or command code.
   `startActivation` produces the SAME activation values `commandButtonActivation` produces for
   the armed command (byte-identical dispatch text), and the screen routes it through the one
   existing spine: `handleCommandButton` → `OperatorInjector` → `submitPrompt` →
   `tryDispatchSlashCommand`. A click and a typed slash command are the same event by the time
   dispatch happens — pinned by the membrane e2e, which proves one registered execute fires for
   both entries in one session.
2. **A second process list.** The dropdown's membership is DERIVED from the same
   `RegistryCommand[]` the palette and command bar consume — `processCommands` /
   `subordinateCommands` partition on the registry's own group ids ({launch, more} = process).
   Registering a command is the only act that adds a menu entry; nothing here names commands.

## Contract: `services/process-select.ts` (pure)

The selection machine has exactly three stages: `unarmed` (no selection; START renders inert and
`startActivation` returns a named rejection), `armed` (a process is selected; START renders
green bold-inverse and activation yields the process command's own activation), and `confirm`
(the armed process has an outstanding membrane offer; START renders yellow `[CONFIRM START]`
and activation yields exactly `/<process> confirm <offerId>`). No stage dispatches without a
selection; repeated toggles and re-selections are idempotent; deselection disarms.

The /train membrane is preserved, not bypassed: the confirm stage reads the offer through a
read-only accessor bound to the membrane's own offer store (never transcript scraping), and
spending still happens only through the dispatched `/train confirm <id>` line. Offer and
refusal text stay visible; prerequisite checks run through the process's own command path and
are never re-implemented or skipped by the button.

Menu layout reuses `resolveCommandBarPage` row-budget tiers; the pane counts the select and
menu rows in its fixed chrome so chart cards stay truthful; controls wrap and never truncate at
any supported width.

Live fail-closed control refusals are projected through the existing operator receipt path and
`operator-control-notice.ts`. Repeated copies of the same refusal collapse into one live line
that retains its receipt path; a distinct refusal replaces that live line rather than relabeling
stale scrollback. The notice is presentation-only and cannot dispatch, steer, retry, or create a
second execution authority.

## Keyboard path and workaround

The pointer is the primary path, but START is not pointer-only. After selecting a process, press
`Tab` from an empty prompt with no completion showing. Focus enters the LIVE RUN controls at the
first enabled control, which is START while the selected run is idle. Press `Enter or Space` to
activate that same START action. If `/train` produces an offer, `[CONFIRM START]` remains the
focused action; `Enter or Space` activates its confirmation dialog through the same control
handler as a click. `Escape` returns focus to the prompt without dispatching.

The keyboard-only workaround is the slash-command spelling shown by the membrane: type `/train`
and press Enter to request the offer, then type `/train confirm <offerId>` using the exact visible
offer id and press Enter. Both pointer START and typed input enter the same `OperatorInjector` and
registered command handler; neither is a second launch authority. The behavioral regression is
`src/screens/repl-process-select-membrane.test.ts`, test
`click-START and typed /name invoke the SAME registered handler, same session`; keyboard traversal
and Enter/Space activation are separately pinned by
`src/screens/repl-keyboard-operator-controls.test.ts`.

## Acceptance

1. The directive flow renders exactly: SELECT PROCESS under the state line, dropdown at the
   button, selection arms START, START executes prerequisites via the process's own command
   path (preflight + offer for /train).
2. Click-START and the typed slash command reach one registered execute through one spine —
   proven end-to-end with a probe command and with the real /train membrane (preflight once,
   offer visible, confirm dispatches the exact line, consumer runs once).
3. Width sweep 26–60 columns: no label truncates; narrow widths wrap whole labels.
4. Repeated fail-closed refusals collapse into one live receipt-attributed notice while distinct
   refusals remain distinguishable and stale scrollback is not rewritten.
