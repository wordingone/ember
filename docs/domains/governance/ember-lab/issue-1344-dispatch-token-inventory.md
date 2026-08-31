# Issue #1344 dispatch-token inventory

Operator mandate (2026-08-03, verbatim): "no process regarding anything ember
should even be able to bypass ember-cli[ember-lab]" -- ember-cli (Ember Lab)
is the sole entry point for every ember process: verification, training,
certification, census, eval, export. Direct invocation must be
machine-refused, not policy-refused.

This is the receipted inventory acceptance criterion #1 asks for: every
entry point that can start an Ember process, whether it is gated today, and
what closing the loop still requires.

## Entry points that START a process (spawn/exec/GPU/training-consuming)

| Entry point | Starts | Gated today | Mechanism |
| --- | --- | --- | --- |
| `runtime/ember-lab/src/main.rs` (`ember-lab.exe`, all subcommands) | itself IS the daemon/CLI authority | N/A -- this is the authority, not a consumer | -- |
| `tools/ember-restart-3b/certified_train_launch.py` | the certified 3B training run (`execute_validated_launch`) | **YES** (#1686 + this issue) | `consume_ember_lab_dispatch()` calls `scripts/ember_dispatch_token.py::consume_dispatch()` before touching any certificate/receipt. Fail-closed: refuses on missing env (`EMBER_LAB_DISPATCH_REQUIRED`), malformed token/pipe (`EMBER_LAB_DISPATCH_TOKEN_INVALID`), unauthenticated daemon (`EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED`), or any RPC/consumption failure (`EMBER_LAB_DISPATCH_REFUSED`). |
| `runtime/ember-lab` `verify-training` subcommand | a synchronous training-closure check (no spawn, but the daemon treats it as a dispatch-gated capability) | YES (pre-existing, #1400/#1401) | `consume_verifier_dispatch_token()` in `main.rs`, same four env vars, same named-pipe RPC. This is the Rust half `ember_dispatch_token.py` mirrors. |
| `runtime/ember-lab` governed-vertical dispatch (`tools/ember-cli/src/services/governed-dispatch.ts` -> `dispatch_manifest` RPC) | an external llmq build, spawned **by the daemon itself** | YES (by construction) | The daemon is the spawner: it creates the job row, mints the token, and stamps the child's env before `Command::spawn`. No separate consumer needed because the daemon never releases control of the process to an ungated path. |

## Entry points that only READ/AUDIT (no process start, no GPU, no mutation)

These are evidence-gathering tools, not process launchers. Gating them is
listed in the issue body's broad phrasing ("verification... census...")
but every one below is explicitly documented in its own file as read-only /
non-mutating / CPU-only, and every one is invoked today by an ember-cli
command that spawns it directly with **no dispatch context available**
(see "What remains" below). Hard-gating a read-only tool without also
wiring its issuer side does not close a bypass -- it just breaks the one
legitimate caller, for zero security benefit, until the issuer side lands.

| Entry point | What it does | Current CLI caller |
| --- | --- | --- |
| `src/ember/governance/scripts/verify_ember01_completion.py` | assembles the EMBER-01 nine-condition completion receipt (reads/hashes, never launches) | `services/verify-watch.ts` (`child_process.spawn`, polled) |
| `scripts/ember_01_custody/census.py` | "Deterministic, read-only custody and benchmark census primitives" (its own docstring) | census-facing commands, spawned directly |
| `src/ember/governance/scripts/ember_01_identity/validate_identity.py` | "Validate Ember model/experiment identity manifests **without loading a model**" (its own docstring) | identity-validation callers, spawned directly |
| `tools/ember-restart-3b/launch_packet.py` | "EMBER-01 cond7 launch-packet readiness runner (**CPU-only, no GPU allocation**)" (its own docstring) | `commands/train.ts` preflight (`runLaunchPacket`), spawned directly, **before** any certified-launch offer exists |
| `src/ember/governance/scripts/training_closure.py` | audits/hashes the training dependency closure declaration; `--print-hash` or pass/fail report, never spawns | imported by `certified_train_launch.py`; CLI-invoked standalone for audits |

## What remains (not done in this PR -- see PR body)

The half that exists after this PR: any process the daemon spawns *itself*
(governed-vertical dispatch, `verify-training`) is already gated end to end,
and the certified-launch consumer (#1686) now actually works (previously
`scripts/ember_dispatch_token.py` did not exist, so `certified_train_launch.py`
refused *every* invocation, including correctly-dispatched ones).

The half that does not exist yet: **ember-cli never asks the daemon for a
token before it spawns a child itself.** `commands/train.ts`'s
`_runPythonProcessInBackground` calls `child_process.spawn` directly, with no
`env` override -- the child inherits ember-cli's own environment, which has
none of the four `EMBER_LAB_DISPATCH_*` variables. `/train confirm` today
spawns `certified_train_launch.py` with no dispatch context, so post-#1686 it
refuses with `EMBER_LAB_DISPATCH_REQUIRED` unconditionally. This is a
pre-existing gap from #1686 (confirmed: no `EMBER_LAB_DISPATCH_TOKEN` is
assigned anywhere under `tools/ember-cli/src`), not a regression introduced
by this PR -- but it is real and it currently blocks every CLI-initiated
training launch.

Closing it needs new daemon surface, not a consumer: the existing token
mechanism (`Daemon::consume_dispatch_token`) requires a job row whose `pid`
column is populated *when the daemon itself calls `Command::spawn`*
(`dispatch_manifest` is the only writer of that column today). ember-cli
spawning the child itself and asking the daemon to retroactively bind a
token to an already-running, externally-spawned pid is a different, new RPC
contract -- verifying the claimed pid is honest (not a forged/reused one)
without the daemon having spawned it needs its own design and its own
tests, which is why it is scoped out of this PR rather than rushed against
the training path this repo treats as the crown jewel (see
`.claude/rules/discipline.md`'s "no class EVER repeats" law -- a wrong
identity check here is exactly a training-failure class). Recommended
follow-up: a `bind_dispatch_token` (or equivalent) RPC that takes
`{job_id, pid, program, argv_sha256}` from the CLI immediately after
`spawn()` returns, verifies the pid's live identity the same way
`consume_dispatch_token` does today, and only then mints the token the CLI
stamps into a second, gated phase of the child's lifecycle -- or,
alternatively, extend the `dispatch_manifest` governed-vertical pattern
(daemon spawns, CLI never does) to the certified-launch and verify/census/
identity entry points, which would let `governed-dispatch.ts` be
generalized rather than adding a second issuance mechanism.
