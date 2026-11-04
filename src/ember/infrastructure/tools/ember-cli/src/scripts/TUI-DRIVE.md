<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# tui-drive: drive the real terminal UI like a person at a keyboard

Runs a program in a pty inside a background daemon, so you can type, press keys and read the rendered
screen with one Bash command each. It never touches the operator's real mouse or keyboard.

    T="bun run <worktree>/src/ember/infrastructure/tools/ember-cli/src/scripts/tui-drive.ts"

| command | what it does |
|---|---|
| `$T start --name S --cwd DIR [--cols 120 --rows 40] [--env K=V ...] [--ttl MIN] -- cmd args...` | launch; state in `A:/ember-wt/tui-sessions/S/` |
| `$T send S --text "hi" [--enter]` | type characters (`\n` = Enter) |
| `$T send S --keys "enter"` | keys: `enter esc tab shift+tab up down left right home end pageup pagedown backspace delete space f1..f12 ctrl+<letter> alt+<char>`; separate with space or `\|`; `down*3` repeats |
| `$T screen S [--all]` | rendered screen as plain text + `[... cursor row= col= child= idle=ms]` footer; `--all` includes scrollback |
| `$T wait S --for REGEX [--timeout 120]` | exit 0 when the screen matches (prints it); 1 timeout (prints last screen); 3 child exited / session gone |
| `$T log S [--bytes N]` | raw output tail (escape codes included) |
| `$T stop S` | kill the process tree, append a kill receipt, write `stopped.json` (records the PID) |
| `$T list` | sessions and state: running / child-exited / stopped / daemon-dead |

`screen` waits for output to go quiet (~120 ms) first, so you read a whole frame, not a half-painted one.
`idle=` in the footer is time since the last output: small means the UI is still changing.

## Driving ember-cli (open-weights)

Start a plain shell, set env in it, and type the launch command. (Passing `cmd /c "..."` through `start`
mangles quoting; programs with simple args are fine directly.) Redirect stderr: the app writes
diagnostics to stderr, which otherwise scribble over the Ink screen.

    W=A:/ember-wt/ow-tui-harness
    $T start --name e --cwd $W --cols 150 --rows 50 -- cmd.exe
    $T send e --text "set EMBER_HOME=A:/ember-wt/tui-home& set EMBER_SOURCE_ROOT=$W& set EMBER_CLI_HEADLESS_CAPTURE=1& bun run src/ember/infrastructure/tools/ember-cli/src/entrypoints/main.ts --open-weights 2>A:\ember-wt\tui-sessions\e-stderr.txt" --enter
    $T wait e --for "❯" --timeout 60
    $T send e --text "What is 17 plus 25? Answer with just the number." --enter
    $T wait e --for "● 42" --timeout 120        # replies are lines starting with "●"; the model loads on first prompt
    $T screen e
    $T stop e                                   # ALWAYS: also reaps llama-server (child of the tree)

Set `EMBER_CLI_HEADLESS_CAPTURE=1` for any instrument run so you do not write the operator's heartbeat/feed state.

## Rules and gotchas

- Always `stop` your sessions. Orphans keep a model in VRAM. A daemon self-stops after 120 min without requests (`--ttl`).
- Type first, then wait for an effect; do not assume a keystroke landed. Check with `screen`.
- Wait for a distinctive regex (`--for` is a JS regex, multiline `^`/`$` work), never sleep a guess.
- A dead child is reported (`child=exited exit=N`); `send` then fails with exit 2. Last screen stays readable via `screen`.
- Daemon is launched with `node --experimental-strip-types` (node-pty input does not work under bun); `node` must be on PATH.
- `stop` appends a JSON kill receipt (before the kill) to the file named by env `TUI_DRIVE_KILL_RECEIPTS`; export it to your fleet's kill-receipts JSONL. Unset = no receipt, with a note on stderr.
- The UI is wide: use `--cols 150 --rows 50` for the ember cockpit; at 120x40 the layout overflows.
- Session names: `A-Za-z0-9_.-`. Never reuse a name that is still running.
