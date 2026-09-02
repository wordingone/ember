# Host setup contract — commit-capacity provisioning (#898)

## Status

Declares and validates one dimension of host readiness: commit-capacity
headroom for mechanisms that pin large host-resident state. Implemented in
`tools/ember-restart-3b/host_setup_contract.py`. Not yet wired into any live
launch/dispatch path — that integration is a follow-up reviewed separately.

## Why this exists

The E8 dense A1 launch (2026-08-21) was refused by the checkpoint host-commit
preflight, correctly, because the host did not have enough commit headroom
for `FullStateAdamWCPUOffload`'s CPU-resident optimizer state. The refusal
was correct; the host's provisioned capacity was the defect. Recovering
required a manual, one-time pagefile increase (32 GiB fixed → 64 GiB fixed)
made by hand through the registry, invisible to any receipt, and not
reproducible on a fresh host without a person remembering to repeat it.

The operator ruled: ember must either (a) fit inside the host's existing
envelope, (b) provision what it needs through a deliberate, documented,
automated, auditable setup contract, (c) redesign the workload to need less,
or (d) fail closed with a precise statement of what is missing. Silent,
undocumented, mid-run OS tuning is never an accepted path under any of those
four. This document and its companion module are (b) and (d) for the
host-commit-capacity dimension specifically. Redesigning the mechanism itself
(c) is addressed separately in
`docs/domains/governance/spec/optimizer-state-mmap-arena-spec.md`, which this contract is
compared against.

## Operator scoping ruling (2026-08-21) — binds everything below

The 2026-08-21 pagefile change is recorded as a **temporary operator
intervention and technical debt**, acceptable only to finish the current
dense control run — it is **not** formalized here as a repeatable Ember
setup requirement, and declining the mmap-arena redesign (which would dirty
~42.9 GiB of optimizer state per step, see
`docs/domains/governance/spec/optimizer-state-mmap-arena-spec.md`) does not by itself establish
a privileged pagefile configuration as the durable answer; those are
independent claims. The dense A1 control's elevated commit footprint is a
property of *that control experiment's own declared profile*
(`dense_a1_full_state_cpu_offload_profile`), never a redefinition of Ember's
normal host floor. A future mechanism that needs more headroom does **not**
inherit "widen the pagefile" as its accepted remediation from this contract
— it must fit the existing envelope, provision through its own declared,
fail-closed, experiment-scoped contract, or redesign; a further privileged
OS change requires its own fresh operator review, never an automatic reuse
of this one.

## The recorded exception

The pagefile change made on 2026-08-21 is recorded here as a one-time,
receipted, operator-authorized exception scoped to the dense A1 control
run — not as a general provisioning step other mechanisms inherit:

- **Registry path:** `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management`
- **Value:** `PagingFiles` (REG_MULTI_SZ)
- **Applied value (2026-08-21, operator-authorized, one time):** fixed pagefile
  raised from a 32,768 MiB (32 GiB) maximum to a 65,536 MiB (64 GiB) maximum.
- **Effective only after reboot.** Between the registry write and the next
  reboot, the live Windows commit limit does not reflect the new maximum —
  see the companion probe-correctness fix in `checkpoint_artifacts.py`
  (`host_commit_headroom_diagnostic` / `configured_maximum_available_commit_bytes`),
  which now bounds computed headroom by the live commit limit as well as the
  configured maximum, precisely to avoid over-reporting headroom in that
  window.
- **Must be a FIXED size, not system-managed.** A system-managed
  ("automatic") pagefile is refused by the existing probe
  (`configured_maximum_available_commit_bytes` requires every `PagingFiles`
  entry to end in a positive fixed maximum) because its true ceiling is not a
  value ember can read and reason about ahead of a launch.

This is recorded as the current exception, not a baseline: it is not
asserted to be sufficient forever, and it is not the prescribed remediation
for a mechanism other than the one that was granted it. A different or
larger future need is a fresh operator decision, evaluated against fit,
redesign, and a genuinely scoped, fail-closed contract of its own — not an
extension of this one.

## The contract mechanics

`tools/ember-restart-3b/host_setup_contract.py` declares, per mechanism, a
`HostMechanismProfile`:

```
required_headroom_bytes = active_parameters * bytes_per_param
                         + transient_bytes
                         + reserve_bytes
```

For `dense_a1_full_state_cpu_offload_profile()` (the profile the 2026-08-21
amendment measured):

| Component | Value | Basis |
|---|---|---|
| `bytes_per_param` | 12 | fp32 `master_copy` + `exp_avg` + `exp_avg_sq`, 4 bytes each (`a1_optimizer.py` `FullStateAdamWCPUOffload.initialize_state`) |
| `active_parameters` | 3,840,000,000 | dense-arm A1 reference parameter count |
| optimizer state (derived) | ≈42.9 GiB | `active_parameters * bytes_per_param` |
| `transient_bytes` | 8 GiB | declared checkpoint-publication transient working set |
| `reserve_bytes` | 6 GiB | frozen safety reserve |
| **total required headroom** | **≈56.9 GiB** | matches the 2026-08-21 amendment's receipted math |

`validate_host_setup_contract(profile, available_commit_bytes_probe=...)`
compares the profile's requirement against a live headroom source (in
production, `checkpoint_artifacts.available_host_commit_bytes`) and either:

- returns a `PASS` receipt naming the mechanism, required bytes, and
  available bytes, or
- raises `HostSetupContractRefusal`, whose message states the exact
  shortfall in GiB, the exact registry value and minimum size to set, and
  that manual mid-training OS tuning is not a supported substitute.

The probe is dependency-injected so the contract module stays free of
platform-specific code and is fully unit-testable without a real Windows
host (see `tests/ember_restart_model/domain-governance/test_host_setup_contract.py`).

## Boundary honesty

This module validates and refuses; it does not yet run at any real launch
decision point. Wiring `validate_host_setup_contract` into the dense-arm A1
dispatch path is named, reviewed-separately follow-up work, not claimed here.
Until that wiring lands, the host-commit preflight inside
`checkpoint_artifacts.py` (`checkpoint_commit_preflight`,
`CheckpointDeferredLowCommit`) remains the sole enforcement point for host
commit headroom during a run; this contract adds pre-launch, mechanism-level
declaration and refusal on top of it, once wired.

This distinction matters against the operator's scoping ruling: the ruling
requires that a genuine minimum host commit configuration be "declared in
the host envelope contract and validated before execution — a preflight
that fails closed with the measured number." Declaring the requirement
(this module) is not the same as validating it before execution (a real
pre-launch call site). Until `validate_host_setup_contract` is actually
called at a real launch decision point — scoped to the declaring
mechanism's own control-experiment declaration, not applied as a general
host-floor check — this issue does not yet satisfy that requirement, and no
packet on #898 should claim otherwise.

## Relationship to the mmap arena alternative

`docs/domains/governance/spec/optimizer-state-mmap-arena-spec.md` designs a different cure for
the same root problem: backing the optimizer's three fp32 state tensors with
ember-custody memory-mapped files instead of anonymous CPU memory, which
would drop the host commit charge from ~57 GiB to working-set scale and make
this pagefile contract largely unnecessary for that mechanism. That spec's
own honest cost analysis (page-cache pressure, dirty-page writeback, SSD
wear) determines whether it should supersede this contract or coexist with
it as a second admitted path; this document does not presume that outcome.
