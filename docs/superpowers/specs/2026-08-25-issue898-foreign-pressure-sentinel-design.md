# Issue #898 L7 Foreign-Pressure Sentinel Design

**Date:** 2026-08-25  
**Issue:** #898  
**Packet:** L7 — daemon-lifetime foreign commit/GPU census, admission fence, and receipt-first owned-orphan reclamation  
**Base:** `b4084ac442a3f70c38f1bec0a0bd480512b7e145`

## Outcome and authority

Ember Lab continuously detects foreign GPU-compute processes and foreign
processes with at least 4 GiB of private commit. It records identity-bound
observations, measures total foreign private commit including processes below
that attribution cutoff, and fences new admissions when measured host commit
headroom crosses the existing 10 GiB survival floor. A complete healthy census
clears only the foreign-pressure fence; the existing sticky survival guard and
its evidence-bound manual rearm remain independent.

The sentinel never terminates, suspends, checkpoints, or otherwise controls a
foreign process. Termination authority remains limited to a process tree proven
to be in an Ember Lab-owned Windows Job Object. The startup-orphan reconciliation
path gains the same receipt-before-action and immediate identity-reverification
ordering already used by normal protective owned stops.

This design implements the strict termination-scope ruling in
[#898 comment 5404065502](https://github.com/wordingone/ember/issues/898#issuecomment-5404065502)
and the counter/threshold clarification in
[#898 comment 5404125636](https://github.com/wordingone/ember/issues/898#issuecomment-5404125636).
It does not grant image-, path-, or name-based process-control authority.

## Considered approaches

1. **Separate foreign-pressure state inside the existing daemon monitor
   (selected).** This preserves the survival guard's sticky/manual-rearm
   semantics while allowing the pressure sentinel to return to clear after a
   complete healthy census. Both states are checked by the one admission path.
2. Overload `resource_guard_state`. Rejected because an automatically clearing
   foreign-pressure state would weaken the existing sticky survival guard, while
   retaining the sticky rule would make the promised pressure-clear transition
   false.
3. Census only at admission. Rejected because it cannot observe a foreign
   process that appears between admissions and cannot prove daemon-lifetime
   detection or clearing.

No new daemon, detached helper, or process-control service is created. The
existing `ember-lab-resource-guard` monitor owns the census on its existing
2,000 ms interval.

## Three quantities with separate roles

The design deliberately does not use one threshold for three different jobs.

### Fence trigger: host commit headroom

The trigger is the existing closed host survival counter and floor:

```text
host_commit_remaining_bytes =
    GetPerformanceInfo.CommitLimit * PageSize
    - GetPerformanceInfo.CommitTotal * PageSize

minimum_host_commit_remaining_bytes = 10 GiB
```

`GetPerformanceInfo` supplies both operands in pages from the same point-in-time
sample. A fence transition occurs when the checked byte subtraction is below the
existing `RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES`. The transition is not
caused by any individual process crossing 4 GiB. This catches many medium-sized
foreign processes while avoiding a false fence for one large process on a host
with ample headroom.

The existing survival guard continues to freeze independently on the same host
floor and remains sticky until its current evidence-bound rearm succeeds. The
new pressure state therefore never opens admission by itself: effective
admission is open only when both states are open. Clearing pressure can leave an
effective admission frozen by the survival guard, and status/receipts must name
both reasons rather than imply that the host is safe.

### Attribution cutoff: per-process private commit

The inclusive attribution cutoff is 4 GiB:

```text
foreign_process_attribution_cutoff_bytes = 4 * 1024^3
```

The value derives from the smallest closed hard per-process budget already
established by #898. It controls which private-commit PIDs are named, not whether
admission is fenced.

Windows process private commit is read from
`K32GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX).PrivateUsage`. This is
private committed memory, not working set. The process handle requests only
`PROCESS_QUERY_LIMITED_INFORMATION` (plus `SYNCHRONIZE` for the probe-end life
check); it never requests VM-read, terminate, suspend, debug, duplicate, or
write rights.

### Total foreign private commit

Every complete observation records
`total_foreign_private_commit_bytes`, the checked sum of `PrivateUsage` for all
enumerated user processes that are not members of an active Ember Lab-owned Job
Object. This includes values below 4 GiB. PID 0 and PID 4 are explicitly recorded
as excluded kernel pseudo-processes; any other enumerated PID whose identity or
private-commit counter cannot be read makes the census incomplete and fail
closed rather than silently lowering the aggregate.

The host fence and process aggregate are the same *kind* of quantity—commit—but
they are not expected to be numerically equal. `CommitTotal` includes kernel and
other non-private charges, while the aggregate is process-private attribution.
Receipts state that difference and never claim that subtracting the aggregate
from the host counter proves causation.

## Process enumeration, identity, and ownership

One census tick performs these steps:

1. Read the host commit sample with `GetPerformanceInfo`.
2. Enumerate process IDs with `K32EnumProcesses`, resizing until the returned
   buffer is demonstrably complete.
3. Read NVIDIA compute-app PIDs and used GPU bytes through the existing
   `nvidia-smi --query-compute-apps=pid,used_gpu_memory` provider path. Provider
   failure makes the census incomplete; an empty successful result is valid.
4. Open each non-kernel process with `PROCESS_QUERY_LIMITED_INFORMATION |
   SYNCHRONIZE`. Read its creation time with `GetProcessTimes` and private commit with
   `K32GetProcessMemoryInfo(...).PrivateUsage`.
5. Snapshot the active Ember Lab owned Job Objects from persisted jobs and
   retained handles. Classify a process as owned only when `IsProcessInJob`
   returns true for one of those exact Job Object handles. A matching executable
   name, image path, argv, parent PID, or environment is never ownership.
6. Sum all non-owned private commit and name every non-owned PID that either has
   an NVIDIA compute context or has private commit greater than or equal to
   4 GiB.
7. Immediately re-open every named PID by PID and require the same creation-time
   token at the end of the probe. A missing or changed identity makes the probe
   fail. A successful probe positively asserts that every named foreign identity
   remained alive through probe completion.

Named rows are ordered by PID then creation-time token so receipt hashes and
tests are deterministic. A PID without a stable creation token is never
silently admitted as an identity.

## State, observations, and admission

Migration adds:

- `foreign_process_pressure_state`, one singleton row with state
  `clear`, `observed`, `fenced`, or `probe_failed`, the latest observation,
  and observation timestamp; and
- `foreign_process_pressure_observations`, an append-only bounded ledger with
  outcome and exact JSON payload.

Each payload uses schema `ember-lab-foreign-process-pressure-observation-v1`
and carries:

- host `CommitTotal`, `CommitLimit`, `PageSize`, derived remaining bytes, and
  the existing 10 GiB floor;
- the 4 GiB attribution cutoff and its issue-ruling source;
- total enumerated foreign private commit, included-process count, and explicit
  kernel exclusions;
- ordered named foreign identities with PID, creation token, private commit,
  GPU bytes when present, provider, and candidate classes;
- owned Job Object identities considered during classification;
- probe completeness, end-of-probe survival result, and any unreadable or
  identity-conflict rows; and
- `foreign_process_control: false` and the counter claim boundary.

State transitions are atomic with the observation insert:

- complete sample, headroom at or above the floor, no named rows: `clear`;
- complete sample, headroom at or above the floor, named rows: `observed`
  (detection evidence without a fence);
- complete sample, headroom below the floor: `fenced`, regardless of whether
  the 4 GiB named set is empty; and
- incomplete enumeration, provider, counter, identity, membership, or survival
  check: `probe_failed` and fail-closed admission.

The first complete sample at or above the floor transitions `fenced` or
`probe_failed` to `clear`/`observed`. This is the pressure-clear rule. It does
not rearm or mutate sticky `resource_guard_state`.

Dispatch reads both singleton states in its existing pre-spawn transaction.
`fenced` or `probe_failed` refuses before argv construction or process birth.
The refusal contains both state observations and their hashes. A race cannot
convert an older clear row into authority because the admission transaction
binds the current singleton rows.

The monitor does not add pressure-fenced jobs to the protective-stop list.
Running owned jobs are never stopped merely because foreign pressure exists.

## Owned-orphan termination ordering

The current `reclaim_starting_job` calls `TerminateJobObject` before it writes
its event. L7 replaces that ordering for a provably owned orphan:

1. In an immediate transaction, verify the persisted `starting` state, lease
   owner/epoch, named Job Object, recorded PID, creation token, and executable
   identity. Transition to a fenced reconciliation state without releasing the
   lease.
2. Open the named Job Object with query rights and the recorded process with
   query/synchronize rights. Require `IsProcessInJob`, the exact creation token,
   and the persisted executable identity.
3. Construct and exclusive-create a content-addressed
   `ember-lab-owned-orphan-termination-v1` decision receipt. It binds job ID,
   state, lease epoch, Job Object name, PID, creation token, executable identity
   hash, membership result, reason, and intended exact Job Object action.
4. Immediately re-open the process and Job Object and repeat membership and
   identity verification after receipt persistence. No unrelated work occurs
   between this check and `TerminateJobObject`.
5. Terminate only that verified Job Object, wait for the exact process identity
   and active-process count to reach terminal, then atomically mark the job
   failed, release its exact lease epoch, and record completion with the decision
   receipt path and hash.

Any failed or changed check refuses termination, retains the lease fence, and
records an identity-conflict/uncertain event. The code never falls back to PID,
image, path, or name matching. The foreign census never calls this path.

## TDD and probe evidence

Production enumeration is behind a narrow census-provider interface. The
deterministic test provider is compiled only for tests and cannot be selected by
RPC, manifest, run ID, or environment variable.

RED tests are written before implementation for:

- one healthy 5 GiB foreign process: named, not fenced;
- twelve 3.5 GiB foreign processes with host headroom below the floor: named set
  empty, aggregate 42 GiB, fenced;
- foreign GPU-compute PID below 4 GiB: named by GPU class;
- complete healthy sample after pressure: pressure state clears/observes while
  sticky survival state is unchanged;
- any non-kernel unreadable PID, provider failure, aggregate overflow, PID reuse,
  or named-process death: `probe_failed` and admission refused;
- an owned Job Object member excluded from the foreign aggregate and named set;
- foreign process handles never requesting terminate/control rights and a
  positive probe-end survival assertion;
- dispatch refusal before argv construction/spawn for current `fenced` and
  `probe_failed` rows; and
- owned-orphan receipt persistence before termination, second immediate identity
  verification, exact Job Object termination, and refusal under PID reuse or
  lost membership.

Focused unit tests run on every host. Windows integration tests exercise real
process creation times, private-commit counters, Job Object membership, foreign
survival, and receipt-before-termination ordering. The live probe must use a
dedicated harmless foreign sentinel created for the test; it must not control
any pre-existing desktop process. A foreign process held by another operator was
live on the host at design time and is a concrete falsifier of permissive control,
but no live PID is hard-coded as test input or authority.

## Claim boundary

This packet proves daemon-lifetime detection, admission fencing from the closed
host commit floor, foreign survival through the probe, and receipt-first control
of a separately verified owned orphan. It does not prove that foreign processes
caused a host-floor breach, does not make process-private commit equal to system
commit, and does not grant control over foreign processes. Pressure-clear at the
10 GiB survival floor is not a certified-launch-readiness claim; the certified
launch path retains its larger measured pre-launch floor. This packet does not by
itself close issue #898.
