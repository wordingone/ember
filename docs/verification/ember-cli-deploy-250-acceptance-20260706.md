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

### (b) Goal organ — scenario A: PASS. Scenarios B: FAIL (binary-side defect, #276). C: SKIPPED

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
  This pass originally used a deliberately dead `EMBER_MODEL_URL` (rails at the time forbade
  touching any live/reserved port). A follow-up leg was later granted a scoped, requests-only
  exception (`EMBER_MODEL_URL=http://127.0.0.1:8082`, the resident model server child of the
  live cockpit — never any lifecycle op against it, exact-PID teardown throughout) to actually
  run B/C. Results below.

#### B/C live run (scoped :8082 exception) — 2026-07-06

**Discriminating design** (pre-registered before running, to separate "model is just slow"
from "the organ doesn't fire"): a control arm first proves the plain request path completes
at all, then scenario B runs `/goal` against the same binary + same server, with the
server's own `/slots` endpoint polled read-only throughout as a ground-truth
did-a-request-ever-arrive signal.

- **Control arm — PASS.** A plain one-word prompt (`"Reply with exactly one word: PONG"`)
  completed a full round trip (submit -> busy -> rendered reply) in the transcript, latency
  ~10-20s. (An earlier automated FAIL of this same arm was retracted after manually
  re-reading the raw transcript: 5s `/slots` poll granularity had straddled the fast busy
  window entirely and missed it. Re-verified true PASS at 2s granularity.) This proves the
  binary -> server -> reply path itself works and is fast on this box — ruling out "dead
  endpoint" or "binary can't talk to the server" as an explanation for what follows.
- **Scenario B — FAIL.** `/goal <3-step progress.txt-writing objective>` created and
  persisted correctly (`goal set: ... status: Active` rendered; store record confirmed on
  disk). Then: nothing, for the full 30.03-minute pre-registered wall cap. Zero `/slots`
  busy observations at 2-second polling across the entire window, zero transcript growth
  after the goal-set confirmation, zero tool calls, the objective's target file never
  created, `continuationTurnsObserved: 0`. Goal store read back after exit: `createdAt` and
  `updatedAt` byte-identical (`2026-07-06T18:31:49.390Z`), `tokensUsed: 0`, `status: Active`
  — the record was never touched again after creation.
- **Verdict per the pre-registered table**: control-PASS + slots-idle-during-B =
  **BINARY-SIDE CONTINUATION DEFECT**. Filed as
  [ember#276](https://github.com/wordingone/ember/issues/276), with a root-cause trace
  posted from the run's own `continuation_skipped` receipt log (two skips — `turn_active`
  then `queued_user_input` — then total silence for the rest of the window, because the
  self-chaining poke in `core/goal-continuation-wiring.ts` only re-invokes itself on a
  *fired* continuation, never on a skip; there is no idle-timer or retry-until-eligible
  safety net anywhere in the wiring). Task-tracked as issue #276 / task #60 for the fix
  lane; this doc records the acceptance-leg result, not the fix.
- **Scenario C — SKIPPED.** Meaningless while B never produces a continuation to preempt,
  per the same pre-registered design. Deferred to the fix-verification pass.
- Process safety: cockpit pid 7568 (`ember-cockpit-250.exe`) and the resident llama-server
  (pid 39720, `:8082`) both confirmed alive and untouched before, during, and after this run
  via exact-PID checks. Zero leftover test `ember.exe` processes.

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

## Verdict: READY for swap (deploy-gap acceptance) — #211 leg-(b) live acceptance: FAIL, tracked as #276

All of #250's own in-scope acceptance items ((a), (c), (d), (e), and goal-organ scenario A)
pass on a freshly built `public/master` binary — the deploy-gap swap itself remains READY,
unchanged from the original pass. The swap (kill-then-launch of the live operator cockpit,
with kill receipts and an announce-first line) is still out of scope for this lane per
#250's own contract and was not performed here — no running process was touched at any
point across either pass.

Separately, the #211 leg-(b) live acceptance (autonomous multi-turn continuation + user
preemption against a real model) now has a real result, not just a scope note: scenario A
passes, scenario B fails per the pre-registered discrimination design (control-PASS +
slots-idle-during-B), and scenario C was correctly skipped as meaningless without B. This is
a genuine binary-side defect in the goal-continuation organ, filed and root-caused at
[ember#276](https://github.com/wordingone/ember/issues/276) — it does not block or reverse
the #250 deploy-gap verdict above (goal mode existing and creating/persisting a goal is
part of #250's bar; autonomous continuation firing is #211's bar), but it is a real,
receipted gap that should be fixed before #211's own closure and re-verified with the same
harness discipline (control arm + `/slots` discriminator) before this doc's B/C section is
updated to PASS.

## Scope note for #211 closure

This report satisfies #250's own acceptance bar (a receipted build + binary-level battery
before a swap). It also now carries the full #211 leg-(b) live-acceptance *attempt* (not a
scope gap anymore) — result: A passes, B fails (see #276), C skipped. #211 itself remains
open, blocked on the #276 fix landing and a clean B/C re-run.
