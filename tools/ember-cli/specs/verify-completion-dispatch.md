<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
<!--
-->

# `/verify` — EMBER-01 completion verification dispatch, non-blocking, pinned-worktree isolated

Status: CURRENT

Issues: #1344, #1371 (slice 1)

Consumer: `tools/ember-cli/src/services/verify-watch.ts`

## Operator mandate this node implements

"No process regarding anything ember should even be able to bypass ember-cli" and
"embercli needs to be able to stay up during verification ... or it's useless"
(2026-08-03). Before #1344, `scripts/verify_ember01_completion.py` was invocable only
from a bare shell, and the cockpit had no live-dispatched way to run it. #1344 made
verification a first-class, non-blocking ember-cli command.

**#1371 operator ruling (2026-08-03, binding, P0): "/verify must never freeze
repository-wide development. The only write-protected surface is the dedicated
verification worktree."** Run20 and the 2026-08-03/04 runs each held development lanes
against a census running directly on the live checkout: every repository-scoped leg ran
with `--root <repoRoot>`, the SAME checkout every other worktree, commit, branch, and
build touches, so a concurrent write could flip the checkout dirty, retarget HEAD, or
change bytes mid-hash — and operators learned to hold writes until a run finished. That
informal hold is the freeze this node kills.

## Contract: `services/verify-watch.ts`

A module-level singleton job-state store, the exact shape `services/telemetry-watch.ts`
uses for `/watch` (`_state` + `getVerifyState()` snapshot read, one job at a time,
starting a new job replaces the singleton). The load-bearing property: `startVerifyRun()`
returns IMMEDIATELY after seeding state and kicking off the pipeline — it never awaits
the pipeline's completion, and the pipeline itself never uses `spawnSync` (that would
block the whole single-threaded cockpit UI for the pipeline's multi-minute duration).
Every subprocess leg goes through the injectable `VerifyProcessRunner` (real
implementation: `node:child_process.spawn`, buffered async, timeout-bounded at
`resolveVerifyTimeoutMs()` — see the timeout/tree-reap/receipt section below).

### Pipeline (#1371: pinned-worktree dispatch, then the original three legs, then retire)

0. **Pin + create the dedicated managed worktree, DETACHED.** `git rev-parse HEAD` against
   `repoRoot` (read-only; the ONLY write this pipeline makes to `repoRoot`'s own git state
   is registering a new worktree row via step 0's `worktree add` — it never touches
   `repoRoot`'s working tree, index, or HEAD). Then `python -B
   src/ember/governance/scripts/worktree_lifecycle.py --repo <repoRoot> create --path
   <worktreeRoot>/<jobId> --detach --owner ember-cli-verify --purpose
   "verify dispatch <jobId>" --expires <today+1d> --start-point <pinnedCommit>` — the
   ONLY worktree-creation path (composes with #1366: no ad-hoc `git worktree add`).
   Failure here (including `WORKTREE_CEILING`) fails the job at phase
   `preparing-worktree` BEFORE any repository-scoped leg or `gh` call runs.
   `worktreeRoot` defaults to `<homedir>/ember-verify-worktrees`, always outside
   `.claude/` (repo-guard #1009) and outside `repoRoot` itself.

   **`--detach` is load-bearing, not a style choice.**
   `verify_ember01_completion.py` runs its executable legs — and computes `ok` — only when
   the checkout is clean AND detached (`inspect_checkout` reads `git symbolic-ref HEAD`;
   a branch-attached checkout stamps all nine legs `UNRESOLVED` with "checkout not
   clean+detached" and forces `checkout_integrity` false). A `--branch`-created worktree
   therefore yields a pipeline that runs to completion around a verdict that could never
   have been green. `parseWorktreeCreateResult` requires `detached: true` in the create
   response and fails the job at `preparing-worktree` otherwise, so a lifecycle script
   that ever reverts to `-b` is refused rather than silently certifying nothing.
   Detaching also stops a `refs/heads/verify/<jobId>` accruing per run on a shared
   repository surface: retire's archive-ref path applies to detached rows, preserving the
   head under `refs/archive/worktree-retirement/...` without a permanent branch.
1. `gh issue list --repo wordingone/ember --state open --limit 1000 --json ...` — stdout
   written to `<jobDir>/issues.json`. Non-zero exit fails the job at phase
   `fetching-issues`; later legs never run.
2. `python -B src/ember/governance/scripts/ember_01_custody/issue_census.py --repo-root <PINNED WORKTREE PATH>
   --public-ref refs/remotes/origin/master --issues-json <jobDir>/issues.json --output
   <jobDir>/issue-census.json`. Non-zero exit fails the job at phase `issue-census`.
   `--repo-root` targets the pinned worktree, never `repoRoot` — #1371's whole point.
3. `python -B scripts/verify_ember01_completion.py --root <PINNED WORKTREE PATH> --receipt
   <jobDir>/verifier-receipt.json --run-custody --issue-census <jobDir>/issue-census.json
   --preserve-custody-output <jobDir>/custody-census-output.json --run-seat
   --selection <EMBER_VERIFY_SELECTION> [--binding root_id=path ...] [--identity-manifest
   ...] [--checkpoint-manifest ...] [--model-config ...]`. `--root` targets the pinned
   worktree — checkout-integrity inspection, launch-packet readiness, authority
   conservation, identity legs, and the custody census's own repo-relative reads all run
   against the isolated copy. Exit 0 or 1 are both a COMPLETED run (ok / not-ok) and land
   the job at `status: "done"`; any other exit (crash, missing interpreter, bad args) is
   an infra failure and lands the job at `status: "failed"`.
4. **Release the managed worktree.** Run on EVERY exit path once step 0 has been
   ATTEMPTED — not merely once it succeeded — escalating only as far as it must:

   1. Delete the scratch this pipeline's own verifier writes inside the worktree
      (`.ember01-verify-custody.tmp.json`, `receipts/ember-01-launch-packet/`).
      `verify_ember01_completion.py` deletes these itself on the normal path precisely to
      keep the tree clean; when a leg is killed by the deadline that cleanup never runs,
      so the worktree is dirty with files only this pipeline wrote.
   2. `python -B src/ember/governance/scripts/worktree_lifecycle.py --repo <repoRoot> retire --path <PATH>`.
   3. If that refuses (`DIRTY_WORKTREE` on residue step 1 did not know about), retry with
      `--force-owner ember-cli-verify`. The lifecycle script overrides its dirty check
      ONLY for managed rows whose recorded owner matches that value, so the escalation can
      never reach a worktree somebody else created; a forced release is disclosed as
      `worktreeForciblyRetired` in status and in the receipt, never silent. Without this,
      a timed-out run strands its worktree together with the temp file that reached 1.4GB
      in the live incident — the single most probable leak in this design.
   4. If the worktree was never REGISTERED — create was killed mid-`git worktree add`, so
      git knows about a worktree that has no managed row — `retire` would refuse it as
      `UNMANAGED_WORKTREE` forever and `audit` would report it as a violation for
      everyone. That case is cleaned up with `git worktree remove --force` against the
      path this run intended to create, which is recorded in state BEFORE the create leg
      spawns for exactly this reason. When the path does not exist (create refused before
      touching the filesystem, e.g. `WORKTREE_CEILING`) nothing is attempted. No
      `git worktree prune` is run: it is repository-wide, so it would reap every
      missing-directory worktree record on the machine as a side effect of one `/verify`
      create failing, and `remove --force` already clears this worktree's own record.

   Release is best-effort throughout: a failure at any step is disclosed as
   `worktreeRetireError` on the job state, never escalated into a run failure (the run's
   verdict is about the pinned commit, not about whether its scratch worktree was tidied
   away afterward). The REAL guarantee here is step 4 running on every exit path, not the
   lease — the 1-day expiry is a backstop only, for the case where the whole node process
   dies before step 4 can even attempt to run (so nothing is left to retire it). Even then
   a worktree that fails to retire still expires within its 1-day lease, so
   `worktree_lifecycle.py audit` catches it — never a silent permanent leak. The lease
   stays at 1 day (lifecycle expiry is date-granular, so anything shorter than "tomorrow"
   reads the same as "today" to `audit`) rather than being tightened, since the backstop
   is not the mechanism doing the real work.

`<jobDir>` is `emberStatePath(repoRoot, "verify-receipts", jobId)` — outside the
checkout by construction (issue #1330's external-state fix), so the receipt directory
is never itself part of what the verifier censuses.

### Timeout, tree-reap, and the always-written run receipt

These three come from one live failure: run `verify-msdz1l2eum570b` (2026-08-04). The
20-minute pipeline cap killed the verifier mid-census; the direct child died but the
`census.py` GRANDCHILD survived as an orphan for 84 more minutes, writing a 1.4GB temp
file nobody ever consumed; and because the job was terminal only in this module's
in-memory singleton, NOTHING was written to disk — after a cockpit restart there was no
way to say what had run, how far it got, or what was still alive.

- **Timeout (`EMBER_VERIFY_TIMEOUT_MINUTES`, default 180): a RUN-WIDE deadline.** One
  budget, resolved once by `resolveVerifyTimeoutMs()` and shared by every leg — each leg
  gets what is left of it, and a leg reached after it is spent reports as timed out
  without being spawned. Per-leg it would have meant a ~18-hour worst case at the default
  before any terminal state, against an env var that reads as "this run gets N minutes".
  The default is measured, not guessed: the custody census leg alone took ~95 minutes on
  the operator machine, so 20 minutes was amputating healthy runs. A malformed or
  non-positive value falls back to the default — never to "no timeout". Worktree release
  runs on its own separate 5-minute grace, because on the timeout path the run budget is
  spent by definition and a release that cannot run is exactly how a worktree leaks.
  `/verify status` shows the remaining budget while a run is live.
- **Tree-reap on timeout.** `proc.kill()` signals only the direct child, which is how the
  grandchild outlived it. On Windows the runner reaps the whole descendant tree with
  `taskkill /PID <pid> /T /F`. On POSIX legs are spawned `detached`, making each child its
  own process-group leader, so `process.kill(-pid, SIGKILL)` reaches the child and every
  descendant in one signal — `pkill -KILL -P <pid>` would have been wrong in both
  directions, killing the direct children while leaving the spawned root alive and never
  reaching the grandchild that was the actual orphan. The receipt records only PIDs the
  kill CONFIRMS it took (`taskkill` SUCCESS lines; nothing is seeded), because a receipt
  naming a PID that is still running is the same class of lie the reap exists to end.
- **Terminal receipt, always.** `<jobDir>/receipt.json` is the RUN receipt this service
  owns, written on EVERY terminal state — green, red, infra failure, timeout, and a
  worktree-create failure that happens before any leg runs — with `ok`, `failure_kind`,
  `phase`, `pinned_commit`, `worktree_path`, `started_at`/`finished_at`/`duration_ms`,
  `leg_timings_ms`, `reaped_pids`, `timeout_ms`, and the verifier's leg vector when there
  is one (schema `ember-cli/verify-run-receipt@1`). The verifier's own receipt moved to
  `<jobDir>/verifier-receipt.json` so the two can never race for one path and the absence
  of a verifier receipt can never look like a missing run receipt. Terminal state is
  reachable ONLY through `finish()`, which writes the receipt first; the old module-level
  `_fail()` that set terminal state without touching disk is deleted, not merely unused.
  A receipt-write failure is disclosed as `runReceiptWriteError` rather than swallowed.

`failure_kind` is one of `pin-head`, `worktree-create`, `gh`, `issue-census`, `verifier-infra`,
`verifier-not-ok`, `timeout`, `crash`, or `null` on a green run. `verifier-not-ok` is the
one value that pairs with `status: "done"`: the pipeline succeeded and the repository did
not verify, and a consumer reading only the receipt cannot mistake red for green.

### Development never waits (#1371 acceptance #1)

Because every repository-scoped leg targets the pinned managed worktree and NOTHING
else does, a concurrent commit, branch, PR, build, or review in any other worktree —
including the live checkout the cockpit itself runs from — is never read by, and never
has to wait on, a running `/verify` job. The only "held" thing is the pinned worktree
itself, and nothing but this pipeline ever writes there. `commands/verify.ts` still
deduplicates a SECOND `/verify` dispatch while one is running (one job at a time), but
that guard is about `/verify` itself, never about unrelated repository writes.

### Custody root bindings — no second config surface

The `--binding NAME=PATH` operator-machine roots the custody legs need come from the
EXISTING `/custody set` store (`services/custody-bindings.ts`,
`readRootBindingsStore`) — `commands/verify.ts` reads it and forwards every entry as
`root_id=machine_path`. This node never introduces a second place to bind an
operator-machine path.

**Disclosed residual scope (#1371 slice 2b, not fixed in this node):** the custody
census's operator-machine roots (`registered-worktree-registry` /
`registered-worktree-material-registry` in `manifests/ember-01-custody/root-spec.json`,
scan modes `git_worktree_registry` / `git_worktree_material_registry`) are deliberately
bound to LIVE machine paths outside the pinned worktree — they attest custody of
operator-machine state the pinned worktree cannot represent, so pinning does not (and
should not) touch them. `census.py` already snapshot-or-fails at the file level (final
byte/membership re-verification; #1365's `runtime_state_exclusions` mechanism), but
ordinary concurrent development in an UNRELATED worktree can still, in principle, read
as a `directory_snapshot_changed_during_scan` / `artifact_mutated_during_hash`
contradiction on those two specific roots during a long custody run. Re-scoping those
roots so ordinary concurrent development can never contradict a run (#1371 requirement
5's "census roots that fingerprint live development surfaces ... re-scoped or
snapshot-isolated") is tracked as follow-on work, named here rather than silently
left for a future reader to rediscover.

### The 4 remaining operator-machine paths — no silent degradation

`--selection`, `--identity-manifest`, `--checkpoint-manifest`, `--model-config` are not
repo-root-scoped, so they are not custody bindings; they come from
`EMBER_VERIFY_SELECTION` / `EMBER_VERIFY_IDENTITY_MANIFEST` /
`EMBER_VERIFY_CHECKPOINT_MANIFEST` / `EMBER_VERIFY_MODEL_CONFIG`.
`EMBER_VERIFY_SELECTION` is MANDATORY — the verifier's `--selection` has no fallback
(`argparse required=True`), so an unset selection refuses the job outright before any
subprocess runs, never a job that starts and fails deep in the pipeline for a knowable
cause. The other three are individually optional: omitting any one omits the
corresponding verifier flag rather than substituting a default, which the verifier's
own "honesty over green" design already turns into an UNRESOLVED (never a fake pass)
on identity legs 3 and 4.

Operator ruling (non-negotiable, 2026-08-03): a cli-dispatched run must never produce a
weaker completion vector than a manual script run without saying so. `commands/verify.ts`
therefore renders an env-binding block — every one of the 4 vars as SET/UNSET plus the
exact legs an unset one costs — at BOTH `/verify` start and every `/verify status`
response, directly above any leg vector. Silently omitting a flag without reporting the
omission in the same view is a defect in this node, not an acceptable degradation.
`/verify status` also discloses `pinnedCommit` and `worktreePath` directly above the
env-binding block — the "development never waits" guarantee made legible, not an
implementation detail worth hiding.

### Custody-census output preservation (both green and red)

`verify_ember01_completion.py`'s `custody_legs()` writes `census.py`'s raw per-file
custody output to an in-checkout scratch path and unconditionally unlinks it afterward
("keep the checkout clean") — on every run, red or green. `--preserve-custody-output`
copies that file to `<jobDir>/custody-census-output.json` BEFORE the unlink, so a red
run's contradiction detail (the case that most needs inspection) is not the case that
gets thrown away. Best-effort: a copy failure never changes a leg verdict.

### Coarse progress (slice 1 of #1344; #1371 adds `preparing-worktree` / `retiring-worktree`)

`getVerifyState()` exposes `phase` (`preparing-worktree` | `fetching-issues` |
`issue-census` | `verifying` | `retiring-worktree` | `done` | `failed`) and a bounded
stdout tail per leg — not a live per-leg checklist, since `verify_ember01_completion.py`
does not emit JSONL progress the way `launch_packet.py` does for `/train`. A
`--progress-jsonl` leg-by-leg stream is a named follow-up, not built here. A per-leg
fingerprint cache (unchanged fingerprint → reuse the prior leg receipt, disclosed
cached-vs-executed) is #1371 requirement 3 / slice 2, not built here — see this issue's
staging notes for the design sketch.

### Not in this node

- Dispatch-token / machine-refusal enforcement that blocks
  `scripts/verify_ember01_completion.py` from being invoked directly outside ember-cli
  (issue #1344's requirement 2) is separate follow-on work.
- The per-leg fingerprint cache (#1371 requirement 3) and the worktree-registry
  re-scoping (#1371 requirement 5's residual scope, above) are slice 2 — #1371 stays
  open across slices, disclosed in this node's PR body.

## Tests (test=spec)

`services/verify-watch.test.ts` — pipeline leg ordering including the #1371
create-worktree/retire-worktree steps and exact argv per leg (repo-scoped legs' `--root`
/ `--repo-root` target the pinned worktree, never `repoRoot`), identity args omitted
(never defaulted) when unset, gh-leg failure short-circuits before later legs while
still retiring the worktree, a worktree-create failure (e.g. `WORKTREE_CEILING`) fails
the job at `preparing-worktree` before any repo-scoped leg or `gh` call runs, a
worktree-retire failure is disclosed as `worktreeRetireError` without failing the run,
and verifier crash (exit outside `{0,1}`) vs. a completed red run (exit 1) are
distinguished. It also covers the three run-`verify-msdz1l2eum570b` cures: the default
timeout is at least 180 minutes and `EMBER_VERIFY_TIMEOUT_MINUTES` overrides it (a
malformed value falls back rather than disabling the cap) and reaches every leg's runner;
the Windows tree-kill argv keeps its `/T` flag and the reaped-PID parse always includes
the root; and `receipt.json` is on disk with the right `ok`/`failure_kind`/`phase`/
`reaped_pids`/`leg_timings_ms` after a timeout, after a pre-leg worktree-create failure,
after a gh infra failure, and on both green and red completed runs. It further covers the
send-back cures: create passes `--detach` and never `--branch`, a create response without
`detached: true` fails the job before `gh` runs, a create killed mid-flight is cleaned up
by path even though no managed row exists, and a dirty worktree at release escalates from
plain retire to the owner-scoped forced retire.

`services/verify-watch.integration.test.ts` is the one NON-mocked test in this node, and
exists because the all-mocked suite structurally could not see B1: it creates a real
worktree with the real `src/ember/governance/scripts/worktree_lifecycle.py` in a throwaway git repository, then
asks the REAL `verify_ember01_completion.inspect_checkout` what it sees, asserting
`detached` and `clean` are both true (the gate the executable legs hang on), that no
`refs/heads/*` beyond `master` accrues, that retire archives the detached head, and that a
worktree dirtied the way a killed leg dirties it can still be released — but only by its
own owner.

`tests/test_worktree_lifecycle.py` covers the lifecycle-script half: `--detach` leaves HEAD
detached and mints no branch ref, `--detach` with `--branch` and neither-of-them are both
refused, a detached row's retire archives its head, and `--force-owner` retires a dirty
worktree for its own owner while still refusing another owner and while never weakening a
clean retire. `commands/verify.ts` covers the command-layer contract (env-binding block
rendering, pinned-commit/worktree-path status disclosure, custody-bindings-store
forwarding, mandatory-selection refusal, already-running guard, status rendering) but is
not itself the bound consumer of this node — `commands/*.ts` is outside
`ADDED_COMPONENT_RE`'s `components|screens|services` scope, so only
`services/verify-watch.ts` is the spec-floor-bound component here.
