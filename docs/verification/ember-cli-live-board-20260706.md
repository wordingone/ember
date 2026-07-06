# ember-cli live-verification board — 2026-07-06

Tracks issue #242 ("every feature is presumed BROKEN until live-demonstrated"). Default grade
for every enumerated row is **BROKEN**; a row is upgraded only when a captured-buffer receipt in
this pass shows the expected behavior actually happening.

Test article: `ember-cockpit-195.exe` (the binary the currently-deployed live cockpit process was
running at the time of this pass — confirmed by reading the running process's executable path,
without interacting with that process in any way). Model backend: a healthy local server
reachable at the configured `EMBER_MODEL_URL`, used for real inference turns throughout.

Harness: a ConPTY (`node-pty`) + headless-terminal (`@xterm/headless`) driver — launches the
binary at a controlled column/row size, feeds real keystrokes, and captures the rendered screen
buffer (post-ANSI-interpretation, i.e. what a real terminal would show), including live mid-session
resize. Never touched the operator's visible window or the already-running cockpit process; every
session in this pass was a separate process, in an isolated working directory, killed by this pass
when done.

## Inventory — full feature surface, with count

Source: `tools/ember-cli/src` on `master` (read-only). Enumerated by reading the command registry,
every file under `commands/`, the REPL's keyboard handler and the components it mounts, the CLI
entrypoint's argv dispatch, and `cli-subcommands.ts`.

**Total enumerated: 90 rows** across five layers:

| layer | count |
|---|---|
| Slash commands registered in source (`command-registry.ts`) | 5 |
| Slash-command source files that exist but are never wired into the live registry | 35 |
| CLI-level flags/subcommands actually wired into argv dispatch | 7 |
| CLI-level flags/subcommands defined/exported but never called from argv dispatch | 20 |
| Keybindings (REPL + status bar + prompt input) | 14 |
| UI affordances (welcome panel, status bar, prompt input, dropdown, renderer, layout engine, root layout) | 7 |
| Advertised-in-UI commands that don't exist anywhere in the registry | 2 |

(5 + 35 + 7 + 20 + 14 + 7 + 2 = 90)

### Slash commands — source-registered (command-registry.ts::getBuiltinCommands, exactly 5 factories)

`setCommandRegistryDeps` — the only seam that could add more builtins — is called **only** from
`command-registry.test.ts`; no production entrypoint (`main.ts` / `process-entry.ts` /
`session-init.ts`) calls it. Skill-dir/plugin/dynamic/MCP command sources all default to
`async () => []` with nothing found that populates them. So these 5 are the entire live-reachable
registry surface, regardless of how many other command files exist in the tree.

| command | code entry point | sub-verbs (source) | deployed-binary reachable? |
|---|---|---|---|
| `/goal` | `commands/goal.ts::createGoalCommand` | `/goal <text>` (create/edit), `/goal` (view), `/goal clear` | **NO — see BROKEN #1 below** |
| `/watch` | `commands/watch.ts::createWatchCommand` | `/watch [path]` | yes |
| `/model` | `commands/model.ts::createModelCommand` | `status`, `load`, `unload` | yes |
| `/observatory` (alias `obs`) | `commands/observatory.ts::createObservatoryCommand` | bare only | yes |
| `/finetune` (alias `ft`) | `commands/finetune.ts::createFinetuneCommand` | `start`,`stop <id>`,`pause <id>`,`resume <id>`,`adjust <id> <lr>` | yes |

### Dead/unreachable slash-command source files (35)

Fully implemented and unit-tested, but never wired into `getBuiltinCommands` — confirmed via a
repo-wide grep for `setCommandRegistryDeps` call sites (none outside the test file):

- `commands/stubs.ts` (23 entries, each explicitly `isHidden: true` / `isEnabled: () => false`,
  self-documented as "not yet enabled"): `force-snip`, `proactive`, `subscribe-pr`, `torch`,
  `buddy`, `peers`, `issue`, `bughunter`, `summary`, `share`, `ant-trace`, `autofix-pr`,
  `backfill-sessions`, `break-cache`, `ctx-viz`, `debug-tool-call`, `good-assistant`,
  `mock-limits`, `oauth-refresh`, `perf-issue`, `reset-limits` (×3 variants).
- 12 standalone command files with no registry wiring: `clear.ts` (`/clear`, aliases `reset`/`new`),
  `feedback.ts`, `usage.ts`, `copy.ts`, `config-tool.ts`, `tag.ts`, `commands/advisor.ts`,
  `commands/remote-control.ts`, `commands/bridge-kick.ts`, `commands/files.ts`,
  `commands/ultraplan.ts`, `commands/ultrareview.ts`.

The `REMOTE_SAFE_COMMANDS` allowlist in `command-registry.ts` (`session`, `exit`, `clear`, `help`,
`theme`, `color`, `vim`, `cost`, `usage`, `copy`, `btw`, `feedback`, `plan`, `keybindings`,
`statusline`, `stickers`, `mobile`) names **zero** commands that overlap with the 5 actually-live
builtins — it is filtering a set that doesn't exist in the live registry.

### CLI-level entrypoints (from `entrypoints/process-entry.ts` argv dispatch + `cli-subcommands.ts`)

7 wired / 20 unwired (source-audited only in this pass, not live-invoked with real argv — flagged
as a follow-up below):

| wired (7) | unwired / dead (20) |
|---|---|
| `--help`/`-h`, `--version`/`-v`/`-V` (+`--json`), `--diag-crash`, `--diag-startup`/`--diagnostics`, `--dump-system-prompt`, `--mcp` (+`--debug`/`--verbose`), `-p`/`--print` | `--chrome-mcp`, `--chrome-native-host`, `--computer-use-mcp`, `--daemon-worker` (flags, no dispatch handler); `ps`, `logs`, `attach`, `kill`, `daemon`, `bridge`, `sync`, `rc`, `remote-control`, `new`, `list`, `reply`, `environment-runner`, `self-hosted-runner` (subcommand strings, no dispatch code anywhere); `auth`, `update`, `agents`, `auto-mode`, `plugin`, `install` (exported in `cli-subcommands.ts`, never imported outside their own test file) |

No `--resume` flag, no `/resume` command, and no `session` CLI subcommand exist anywhere in
source — `session` appears only as a string literal inside the (already-dead)
`REMOTE_SAFE_COMMANDS`/`BRIDGE_SAFE_COMMANDS` constants. `--init` has no CLI surface either (there
is an internal `init()` called automatically during startup in `session-init.ts`, unrelated to the
`/init` command the welcome screen advertises).

### Keybindings (14)

| keybinding | entry point | expected behavior |
|---|---|---|
| Enter | `screens/repl.ts` | Submit prompt, or complete the highlighted slash-dropdown selection |
| Tab (no shift) | `screens/repl.ts` | Accept the current ghost prompt-suggestion |
| Shift+Tab | `components/status-bar.ts` (`StatusLine`'s own input handler) | Cycle permission mode |
| Esc | `components/status-bar.ts` → `interrupt.interrupt()` | Advertised as "esc to interrupt" |
| Ctrl+T | `components/status-bar.ts` | Toggle task-panel visibility |
| Ctrl+C | `screens/repl.ts` | Abort in-flight request, else exit |
| Ctrl+E | `screens/repl.ts` (inline comment: "handled by main") | Open external editor |
| Backspace/Delete | `screens/repl.ts` | Drop last input character |
| Up/Down arrow | `screens/repl.ts` | Navigate the slash-command dropdown (only while open) |
| Ctrl+S | `components/prompt-input.ts` (`usePromptInput`'s own handler, also mounted) | Stash input text |
| Alt+P | `components/prompt-input.ts` | Open model picker |
| Alt+O | `components/prompt-input.ts` | Toggle "fast mode" hint |
| Ctrl+G | `components/prompt-input.ts` | Open external editor (second, separate implementation) |
| Esc (while stashed) | `components/prompt-input.ts` | Restore stashed text |

### UI affordances (7)

Welcome/homescreen panel, status bar, prompt input row, slash-command dropdown, transcript
message renderer, the pure-TS flexbox layout engine, and the REPL's root layout tree
(`screens/repl.ts`'s render — column root, transcript `flexGrow:1`, prompt+status pinned below).

### Advertised-but-nonexistent commands (2)

The welcome screen's own onboarding tips render `Run /init to create an EMBER.md file...` and its
recent-activity feed footer renders `/resume for more` — **neither `/init` nor `/resume` is a
registered command** (confirmed above: only goal/watch/model/observatory/finetune exist in
source, and goal isn't even in the deployed binary). Typing either into the live REPL hits the
"Unknown command" fallback.

## Grading — current-state live pass (deployed binary, primary viewport 213×35)

Receipts: `receipts-20260706/drive-213x35/` (21 numbered steps + steplog), `receipts-20260706/resize-probe*/`, `receipts-20260706/chat-repro/` (ad hoc follow-ups referenced inline below).

### VERIFIED-LIVE (12)

1. **Welcome/homescreen panel** — renders correctly at launch at 100×30, 213×35, and 140×50: bordered panel, fireball art, identity block, tips/recent-activity feeds, width reflows to the live terminal column count. (`bisect/welcome-*-*.txt`, `drive-213x35/01-welcome.txt`)
2. **`/watch` (turn on)** — `watching state/ember-telemetry.jsonl` (`drive-213x35/11-watch_on.txt`)
3. **`/observatory`** — real (if empty) timeline output: `no activity yet` (`drive-213x35/10-observatory.txt`)
4. **`/model status`** — returns a status line (see BROKEN #6 for the accuracy caveat)
5. **`/model unload`** (external-model config) — `external model (EMBER_MODEL_URL) — not managed, nothing to unload`, matches source exactly (`drive-213x35/14-model_unload_external_noop.txt`)
6. **`/finetune start`** — parses, validates, and emits a control-channel JSONL line (`drive-213x35/15-finetune_start.txt`)
7. **Unknown-command fallback** — correct message + accurate available-command list (`drive-213x35/16-unknown_command.txt`) — this is also what revealed BROKEN #1
8. **Ctrl+T task-panel toggle** — status-bar hint text flips `ctrl+t to show tasks` → `ctrl+t to hide tasks` (`drive-213x35/19-ctrl_t_taskpanel.txt`)
9. **Shift+Tab permission cycle** — status-bar text flips `⏵⏵ bypass permissions on` → `○ regular mode` (`drive-213x35/17-18`) — see BROKEN #13 for the state-machine caveat
10. **Slash-command text entry / character input** — every keystroke sequence typed and echoed correctly across the whole pass
11. **Plain-chat turn, keystroke-by-keystroke** — a 2-character message typed one character at a time (with a real gap between characters, not one synchronous burst) round-tripped correctly: echoed as a `You` transcript row, spinner shown (receipt: ad hoc repro, not in the numbered step log — see BROKEN #8 for the burst-input failure mode this rules out as the general case)
12. **`/model`, `/watch`, `/observatory`, `/finetune` command dispatch in general** — all four correctly route through `tryDispatchSlashCommand` to their real implementations

### BROKEN (17)

1. **`/goal` is entirely absent from the deployed binary.** Typing `/goal` returns `Unknown command: /goal` / `Available: /finetune, /model, /observatory, /watch` (`drive-213x35/05,06,08,09`) — despite being fully implemented and registered in the current `master` source. The deployed `ember-cockpit-195.exe` predates the #211 goal-mode registry wiring. This matches the project's own task ledger, which still lists "Live acceptance leg (b): compiled-binary goal-mode session test" as pending.
2. **Slash-command autocomplete dropdown never renders live.** Typing `/` (which the pure logic (`shouldShowSlashDropdown`) should recognize, opening a menu of all 4 available commands) produces **no dropdown box anywhere on screen** — only the literal `/` character in the input row (`drive-213x35/02-slash_dropdown_open.txt`, `03-slash_dropdown_filter_go.txt`).
3. **Live window resize is severely broken, on all four dated binaries tested (see bisect below).** Resizing an already-running session from 213×35 to 100×30 leaves stale, mid-word-clipped content in rows 0–4 (reproducing the original #114 symptom exactly: `"Run /init to create an EMBER.md file with"` cut off mid-word) and **blanks every row below that, including the prompt and status bar, which do not reappear** — not even after resizing back to the original 213×35 (`receipts-20260706/resize-probe/`, `resize-probe-raw/`). This is worse than the originally reported symptom and reproduces live on the exact binary the operator is currently running.
4. **Esc-to-interrupt is a no-op.** Advertised in the status bar (`esc to interrupt`), wired to `handleInterrupt = useCallback(() => {}, [])` in `screens/repl.ts` — an empty function. Live test during idle showed no visible effect (consistent with, though not a full proof of, the no-op wiring).
5. **`/watch` can never be turned off via its own documented mechanism.** Calling it twice with no arguments returns the same `watching ...` message both times (`drive-213x35/11,12`) — never `watch off`. Source cause: the three preceding `if` branches in `commands/watch.ts` are jointly exhaustive over `(isWatching, path)`, making the final "toggle off" branch dead code.
6. **`/model status` misreports state.** It reads a module-level variable that defaults to `"unloaded"` and is only ever set by `registerManagedModel`, which no boot path in this codebase calls — so it will report `"unloaded"` even while a real external model is actively serving.
7. **`/model load`/`unload` process-lifecycle actions are stubbed even outside external mode.** The injected `killPid` in `commands/model.ts` is an empty function body with only a comment ("Real impl would use process.kill…"); the injected `spawnModel` returns a hardcoded fake `{pid: 0}`. (Not directly exercisable live in this pass since the test config is always external — flagged from source.)
8. **A full input line + Enter delivered as a single synchronous write is silently dropped.** Writing `"Reply with exactly the single word: PONG\r"` in one call produced **no** echoed user message, no spinner, and no error — total silence. Splitting the exact same text and the Enter keypress into two separate writes (with the identical content) submits and round-trips correctly. This is a genuine input-handling race, not a harness artifact (confirmed by the working split-write control test).
9. **Ctrl+E "open editor" is a no-op** in `screens/repl.ts` (inline comment: "handled by main"; body is empty).
10. **Alt+P "open model picker" is a no-op** — `usePromptInput()` is called with no `onModelPickerOpen` dependency in `screens/repl.ts`, so there is nothing to open.
11. **Alt+O "toggle fast mode" has no visible effect anywhere.** The `FastModeHint` class's state is never read by anything in the render tree.
12. **Ctrl+G "open editor" (prompt-input.ts's separate implementation) is also a no-op**, for the same reason as #10.
13. **Three independent, unreconciled permission-mode state machines coexist.** `screens/repl.ts` has its own 3-state cycle (`bypass`/`interactive`/`swarm-worker`) wired to the status bar, but collapses the display to only two strings (`bypass` vs `regular`) — so a user cycling through all three states can never visually tell `interactive` and `swarm-worker` apart. `components/prompt-input.ts` has a completely separate 3-state cycle (`bypass`/`regular`/`plan`) that is constructed (`usePromptInput()` is called in `repl.ts`) but never rendered anywhere.
14. **`/init` does not exist**, despite being advertised in the welcome screen's own onboarding tips.
15. **`/resume` does not exist**, despite being advertised in the welcome screen's own recent-activity footer.
16. **35 slash-command source files are fully built and unit-tested but unreachable from any live session** (see inventory table above).
17. **20 CLI-level flags/subcommands are defined/exported/listed in help text but have zero dispatch call sites** (see inventory table above) — audited from source only; not live-invoked with real argv in this pass.

### DORMANT (1)

- **Live model-metrics meter in the status bar never appeared** in any capture in this pass, despite `EMBER_MODEL_URL` pointing at a confirmed-healthy model server throughout. Not root-caused in this pass (would need a dedicated look at `services/model-metrics-poller.ts`); flagged for follow-up rather than graded BROKEN outright since the absence could be a poller-timing issue rather than a structural gap.

## Regression bisect — issue #114

Four dated binaries in `wt-cockpit` (`ember-cockpit-new.exe`, `-172.exe`, `-187.exe`, `-195.exe`,
spanning 2026-07-05 14:23–18:08) were each launched fresh at three fixed geometries (100×30,
213×35, 140×50) and their welcome-screen captures diffed byte-for-byte.

**Launch-time verdict: no regression.** All four binaries produce **byte-identical** welcome-screen
renders at all three geometries — width correctly reflows to the live terminal size in every case
(`receipts-20260706/bisect/`, `bisect-manifest.json`).

**This result does not hold once a session is resized live**, which the launch-fresh method above
cannot detect (it only measures "rendered once at a fixed final size," never "resized while
running" — the actual operator scenario). Re-testing all four binaries with an identical
live-resize probe (213×35 → 100×30, mid-session) reproduces the **same severe defect on all
four**: stale mid-word-clipped content plus total loss of the prompt/status bar (BROKEN #3 above).

**Verdict: the resize-repaint defect is not a regression introduced between these four builds — it
is present, identically, across the entire tested range** (2026-07-05 14:23 through 18:08). Either
none of these four builds include a working resize-repaint path, or the repaint pipeline has a bug
that the layout-engine-level "root-freeze" fix (`ink/layout-engine.ts`, confirmed in current
`master` source to correctly recompute both width and height from the live terminal size on every
call) does not reach — the actual terminal write-out on a resize event is a separate code path
from the layout calculation, and this pass did not have time to isolate exactly which one is at
fault. A true first-bad-build bisect would need binaries older than "new" (2026-07-05 14:23),
which were not available in this pass.

## Coverage gaps / follow-ups

- CLI-level entrypoints (7 wired / 20 dead) were source-audited only, not live-invoked with real
  argv in a ConPTY session in this pass.
- Only `ember-cockpit-195.exe` got the full current-state feature drive; the other three bisect
  binaries were only compared on welcome-screen render and the live-resize probe, not the full
  command/keybinding sequence.
- 100×30 and 140×50 did not get the full 21-step feature-drive sequence (only 213×35, the
  operator's primary viewport, did) — welcome-screen rendering at those two sizes was covered by
  the bisect pass.
- The model-metrics status-bar meter's absence (DORMANT, above) was not root-caused.
- The resize-repaint defect's exact code-path cause (layout calculation vs. terminal write-out /
  diffing) was not isolated to a specific file or line.
