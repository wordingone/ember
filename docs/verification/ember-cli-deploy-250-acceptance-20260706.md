# ember-cli deploy-gap acceptance battery — issue #250 (2026-07-06)

Closes the receipted-build-and-live-verify leg of #250: the deployed operator cockpit binary
predated #227 (goal continuation wiring), #238 (ink/repl port), #256 (re-port), and #258
(circuit breaker + endpoint disclosure). This report builds a fresh binary from current
`public/master` and live-verifies the gap that made #250 real, before any swap. **This lane
builds and tests only — the kill-then-launch swap of the live cockpit is a separate,
announce-first step, not performed here, and no running process was touched at any point.**

## Build receipt

- Source: `public/master` @ `23a1ab90d0f4d1005918aa320ad1e01b040e0d55` ("fix: model-client retry
  circuit breaker + startup endpoint disclosure (#258)") — fresh `git fetch public master` +
  `git worktree add` immediately before building, no local edits.
- Build command: `bun run build` (`tools/ember-cli/src/package.json`'s own script — `bun build
  ./entrypoints/main.ts --compile --outfile ember.exe`), preceded by `bun install`.
- Toolchain: `bun 1.3.12`, Windows x64.
- Output: `ember.exe`, 118,905,344 bytes.
- `sha256`: `690357f58361b23268375896763e9d012259555fe2626882a47e8738d4b693dc`
- Built (UTC): `2026-07-06T16:58:28Z`.
- `bun install` / `bun build` — both exit 0, no warnings.

## Harness

A ConPTY (`node-pty`) driver in an isolated scratch project (not part of this repo, not
committed): spawns the fresh binary in a dedicated per-test working directory with a
controlled column/row size, writes real keystrokes, and captures the raw output stream
(ANSI-stripped for assertions, raw capture kept as evidence). Every session was a separate,
short-lived process with its own isolated `EMBER_HOME`; none ever pointed at a live model
endpoint or a reserved port, and none ever touched the running cockpit process. Exit was
verified by exact PID via WMI/PowerShell (`Get-CimInstance Win32_Process -Filter
"ProcessId=<pid>"`) — never by image name — specifically so cleanup could never reach any
other `ember.exe` process on the host, including the real cockpit. A known input-race
(documented in the #242 board: a single write of `text + \r` can be silently dropped) was
worked around by writing the text and the Enter keystroke as two separate writes.

## Battery results

### (a) Boot, help surface, clean exit — PASS

- `ember.exe --help` (non-interactive flag, no TTY needed): prints full usage (`-h/--help`,
  `-v/--version`, `--diag-startup`, `--mcp`, subcommands, `EMBER_MODEL_URL`/`EMBER_API_KEY`
  env docs). Exit 0.
- Interactive boot: startup line `[ember] model endpoint: <url> -- resolved from
  EMBER_MODEL_URL (skips the managed spawn)` appears, followed by the welcome panel
  ("ember v0.0.0", tips, recent-activity pane) and a ready prompt.
- There is no dedicated `/help` slash command registered in source today (matches the #242
  board's own inventory). The live equivalent is typing `/`, which renders the command
  dropdown — confirmed live: it lists all 6 currently-wired commands (`/observatory`,
  `/watch`, `/finetune`, `/model`, `/goal`, `/cockpit`).
- Clean exit: `Ctrl+C` while idle terminates the process (repl.ts's documented
  non-busy-path `_onExit?.()`). Verified by exact-PID OS check after the keystroke — PID no
  longer present.

### (b) Goal organ — scenario A only: PASS. Scenarios B/C: out of scope for this lane (see below)

- `/goal <objective>` on a freshly booted binary: response `goal set: <objective>\nstatus:
  Active` rendered live.
- The goal record was persisted to disk by the real file-backed store
  (`services/goal-persistence.ts`) at `<repoRoot>/.ember/goals/<goalId-keyed-session>.json`
  (repo-root resolved via the documented exe-location walk-up in `utils/repo-root.ts`, not a
  harness artifact). Read back after the session exited:
  ```json
  {
    "objective": "Verify the #250 deploy-gap acceptance battery end to end",
    "status": "Active",
    "usage": { "tokensUsed": 0, "elapsedMs": 0 },
    "consecutiveBlockedTurns": 0
  }
  ```
  This is scenario A ("create -> continuation-eligible idle") demonstrated live and
  independently confirmed via the on-disk store, not just transcript text.
- `/goal` (bare, view) round-tripped the objective text in the transcript, but this pass's
  harness captures a cumulative log rather than a reconstructed terminal screen, so the
  precise on-screen placement of the view response is not independently confirmed to the
  same rigor as the create step — flagged here rather than silently counted as a full pass.
- **Scenarios B (>=3 autonomous continuations against a live model) and C (user
  preemption) require an actual reachable model endpoint to run real inference turns.**
  This lane's rails explicitly forbid touching the reserved live-cockpit ports or spawning
  any model process, so every test here used a deliberately dead `EMBER_MODEL_URL` — by
  design, incapable of completing a real turn. Re-running B/C against a real endpoint
  remains task-tracked separately (the decomposed live-acceptance lane for #211, which also
  carries the prior wedge history this pass was careful not to repeat). Note found in situ
  (not run by this pass, cited for context only): an earlier session's own goal-store
  directory already contains one record that reached `status: Complete` after a real
  multi-turn autonomous run, which is corroborating history that the mechanism has worked
  live before — it is not evidence produced by this acceptance pass and is not claimed as
  such.

### (c) Circuit breaker + startup disclosure — PASS

- Startup disclosure line names the dead `EMBER_MODEL_URL` exactly (`[ember] model
  endpoint: http://127.0.0.1:1 -- resolved from EMBER_MODEL_URL (skips the managed spawn)`).
- Submitting an ordinary prompt against the dead endpoint: bounded backoff, circuit opened
  in 34.7s (worst-case budget ~61s per `CIRCUIT_MAX_ATTEMPTS=6`/`CIRCUIT_BACKOFF_CAP_MS=30s`)
  — no unbounded hang. Visible degraded banner: `Model endpoint degraded: circuit open for
  http://127.0.0.1:1 (last failure: connection error)`.
- Second submit immediately after: resolved in 3.16s (local fast-reject, no repeat backoff
  cycle) — confirms the circuit stayed OPEN and rejected locally instead of re-dialing.
  Status-bar banner text matched the documented format exactly: `⚠ degraded:
  http://127.0.0.1:1 · connection error · attempts 6 · next probe in 60s`.
- Clean exit verified by exact-PID check, as in (a).

### (d) #119 ported modules present — PASS (static + registration check)

Spot-checked the modules #119/#238 restored: `core/monitor-render.ts`,
`core/ember-world-state.ts`, `commands/world-state.ts`, `core/encounter-membrane.ts`,
`components/design-system.ts`, `components/prompt-input.ts` — all present in the built
source tree. `command-registry.ts` imports and registers both `createGoalCommand()` and
`createWorldStateCommand()`; live-confirmed reachable via the `/` dropdown in test (a), which
lists `/goal` and `/cockpit` (world-state) alongside the other 4 builtins. This is the
concrete fix for the #242 board's BROKEN #1 finding (`/goal` unreachable on the
then-deployed `ember-cockpit-195.exe`) — on this binary it is registered and renders.

### (e) Build identity — recorded above (sha256, size, UTC timestamp, bun version, source commit).

## Verdict: READY for swap

All in-scope acceptance items pass on a freshly built `public/master` binary. The swap
itself (kill-then-launch of the live operator cockpit, with kill receipts and an
announce-first line) is out of scope for this lane per #250's own contract and was not
performed here — no running process was touched at any point in this pass.

## Scope note for #211 closure

This report satisfies #250's own acceptance bar (a receipted build + binary-level battery
before a swap), not the full #211 leg-(b) live acceptance (autonomous multi-turn
continuation + user preemption against a real model). That remains open as its own
decomposed, separately tracked lane.
