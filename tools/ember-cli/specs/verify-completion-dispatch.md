<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# `/verify` — EMBER-01 completion verification dispatch, non-blocking

Status: CURRENT

Issue: #1344

Consumer: `tools/ember-cli/src/services/verify-watch.ts`

## Operator mandate this node implements

"No process regarding anything ember should even be able to bypass ember-cli" and
"embercli needs to be able to stay up during verification ... or it's useless"
(2026-08-03). Before this node, `scripts/verify_ember01_completion.py` was invocable
only from a bare shell (see the canonical run20.sh-style invocation this replaces),
and the cockpit had no live-dispatched way to run it. This node makes verification a
first-class, non-blocking ember-cli command.

## Contract: `services/verify-watch.ts`

A module-level singleton job-state store, the exact shape `services/telemetry-watch.ts`
uses for `/watch` (`_state` + `getVerifyState()` snapshot read, one job at a time,
starting a new job replaces the singleton). The load-bearing property: `startVerifyRun()`
returns IMMEDIATELY after seeding state and kicking off the pipeline — it never awaits
the pipeline's completion, and the pipeline itself never uses `spawnSync` (that would
block the whole single-threaded cockpit UI for the pipeline's multi-minute duration).
Every subprocess leg goes through the injectable `VerifyProcessRunner` (real
implementation: `node:child_process.spawn`, buffered async, timeout-bounded at
`DEFAULT_VERIFY_TIMEOUT_MS`).

### Pipeline (three legs, run in order, each gated on the previous leg's exit)

1. `gh issue list --repo wordingone/ember --state open --limit 1000 --json ...` — stdout
   written to `<jobDir>/issues.json`. Non-zero exit fails the job at phase
   `fetching-issues`; later legs never run.
2. `python -B scripts/ember_01_custody/issue_census.py --repo-root <repoRoot>
   --public-ref refs/remotes/origin/master --issues-json <jobDir>/issues.json --output
   <jobDir>/issue-census.json`. Non-zero exit fails the job at phase `issue-census`.
3. `python -B scripts/verify_ember01_completion.py --root <repoRoot> --receipt
   <jobDir>/receipt.json --run-custody --issue-census <jobDir>/issue-census.json
   --preserve-custody-output <jobDir>/custody-census-output.json --run-seat
   --selection <EMBER_VERIFY_SELECTION> [--binding root_id=path ...] [--identity-manifest
   ...] [--checkpoint-manifest ...] [--model-config ...]`. Exit 0 or 1 are both a
   COMPLETED run (ok / not-ok) and land the job at `status: "done"`; any other exit
   (crash, missing interpreter, bad args) is an infra failure and lands the job at
   `status: "failed"`.

`<jobDir>` is `emberStatePath(repoRoot, "verify-receipts", jobId)` — outside the
checkout by construction (issue #1330's external-state fix), so the receipt directory
is never itself part of what the verifier censuses.

### Custody root bindings — no second config surface

The `--binding NAME=PATH` operator-machine roots the custody legs need come from the
EXISTING `/custody set` store (`services/custody-bindings.ts`,
`readRootBindingsStore`) — `commands/verify.ts` reads it and forwards every entry as
`root_id=machine_path`. This node never introduces a second place to bind an
operator-machine path.

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

### Custody-census output preservation (both green and red)

`verify_ember01_completion.py`'s `custody_legs()` writes `census.py`'s raw per-file
custody output to an in-checkout scratch path and unconditionally unlinks it afterward
("keep the checkout clean") — on every run, red or green. `--preserve-custody-output`
copies that file to `<jobDir>/custody-census-output.json` BEFORE the unlink, so a red
run's contradiction detail (the case that most needs inspection) is not the case that
gets thrown away. Best-effort: a copy failure never changes a leg verdict.

### Coarse progress (slice 1 of #1344)

`getVerifyState()` exposes `phase` (`fetching-issues` | `issue-census` | `verifying` |
`done` | `failed`) and a bounded stdout tail per leg — not a live per-leg checklist,
since `verify_ember01_completion.py` does not emit JSONL progress the way
`launch_packet.py` does for `/train`. A `--progress-jsonl` leg-by-leg stream is a named
follow-up, not built here.

### Not in this node

Dispatch-token / machine-refusal enforcement that blocks
`scripts/verify_ember01_completion.py` from being invoked directly outside ember-cli
(issue #1344's requirement 2) is separate follow-on work. This node makes `/verify` a
working, non-blocking cli entry point; it does not yet make direct invocation refuse.

## Tests (test=spec)

`services/verify-watch.test.ts` — pipeline leg ordering and exact argv per leg,
identity args omitted (never defaulted) when unset, gh-leg failure short-circuits
before later legs, verifier crash (exit outside `{0,1}`) vs. a completed red run (exit
1) are distinguished. `commands/verify.ts` covers the command-layer contract
(env-binding block rendering, custody-bindings-store forwarding, mandatory-selection
refusal, already-running guard, status rendering) but is not itself the bound
consumer of this node — `commands/*.ts` is outside `ADDED_COMPONENT_RE`'s
`components|screens|services` scope, so only `services/verify-watch.ts` is the
spec-floor-bound component here.
