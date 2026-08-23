# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed host commit-capacity contract for ember mechanisms that pin
large host-resident state (for example ``FullStateAdamWCPUOffload``'s
CPU-offloaded optimizer moments in ``a1_optimizer.py``).

An ember mechanism that needs more host commit headroom than the reference
host currently provides must not be admitted by silent ad-hoc OS tuning
mid-run. This module gives each such mechanism a declared, testable
capacity requirement, checked by a fail-closed pre-execution probe. A host
that does not meet the requirement is refused with a precise statement of
the shortfall -- never a suggestion to tune the OS by hand while a run is
in flight.

Receipted defect this formalizes (#898, 2026-08-21 amendment): the E8 dense
A1 launch needed a manual, undocumented, unreceipted pagefile increase
(32 GiB -> 64 GiB) to proceed. The operator ruled that ember must either fit
the host envelope, provision prerequisites through a deliberate documented
automated auditable setup contract, redesign the workload, or fail closed
with a precise statement -- manual mid-run OS tuning is never an accepted
path.

Scoping ruling (operator, 2026-08-21, binds this module): the 2026-08-21
pagefile change was a TEMPORARY operator intervention and technical debt,
acceptable only to finish that dense control run -- never a formalized,
repeatable Ember setup requirement. A mechanism's elevated commit need is a
property of that mechanism's own declared control-experiment profile (see
``HostMechanismProfile`` / ``dense_a1_full_state_cpu_offload_profile``), never
a redefinition of Ember's normal host floor. The certified launch path now
validates this profile against live headroom and the daemon-authenticated Job
Object ceiling before the load-bearing trainer runner is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

BYTES_PER_GIB = 1024**3
_U64_MAX = 2**64 - 1

# #898 L2 measured the largest hard Job Object limit overshoot at 6.17%
# on the same CUDA/WDDM allocation class used by dense A1. This is a compiled
# evidence binding, not a caller-selected margin.
DENSE_A1_JOB_MEMORY_OVERSHOOT_BASIS_POINTS = 617
DENSE_A1_JOB_MEMORY_OVERSHOOT_BASIS = "windows_job_object_cuda_wddm_measured"

# fp32 master_copy + exp_avg + exp_avg_sq: three 4-byte tensors per parameter,
# each touched in full on every optimizer.step() call (a1_optimizer.py
# FullStateAdamWCPUOffload.step). All three are commit-charged CPU tensors.
_FULL_STATE_ADAMW_CPU_OFFLOAD_BYTES_PER_PARAM = 12

# Declared transient working-set the checkpoint publication path allocates
# above the resident optimizer state for this mechanism's shard sizes
# (matches the #898 2026-08-21 amendment's receipted math: 8 GiB transient).
DENSE_A1_TRANSIENT_CHECKPOINT_BYTES = 8 * BYTES_PER_GIB

# Frozen safety reserve held back from the headroom computation, matching the
# reserve already receipted for this run in the same amendment.
DENSE_A1_RESERVE_BYTES = 6 * BYTES_PER_GIB

# Canonical dense structural parameter count used by the certified A1 config.
# The #898 amendment described it as 3.84B; the envelope binds the exact count.
DENSE_A1_REFERENCE_ACTIVE_PARAMETERS = 3_839_161_856

@dataclass(frozen=True)
class HostMechanismProfile:
    """One ember mechanism's declared host commit-capacity requirement."""

    name: str
    active_parameters: int
    bytes_per_param: int
    transient_bytes: int
    reserve_bytes: int
    overshoot_allowance_basis_points: int = 0
    overshoot_allowance_basis: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("host mechanism profile name must be a nonempty string")
        for field_name, value in (
            ("active_parameters", self.active_parameters),
            ("bytes_per_param", self.bytes_per_param),
            ("transient_bytes", self.transient_bytes),
            ("reserve_bytes", self.reserve_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"host mechanism profile {field_name} must be a positive integer")
        if (
            type(self.overshoot_allowance_basis_points) is not int
            or not 0 <= self.overshoot_allowance_basis_points <= 10_000
        ):
            raise ValueError(
                "host mechanism profile overshoot allowance basis points must be "
                "an integer between 0 and 10000"
            )
        if self.overshoot_allowance_basis_points:
            if (
                not isinstance(self.overshoot_allowance_basis, str)
                or not self.overshoot_allowance_basis
            ):
                raise ValueError(
                    "host mechanism profile with an overshoot allowance requires "
                    "a nonempty evidence basis"
                )
        elif self.overshoot_allowance_basis is not None:
            raise ValueError(
                "host mechanism profile without an overshoot allowance cannot "
                "declare an evidence basis"
            )
        # Ember Lab's manifest and Windows Job Object boundary are u64-sized.
        # Refuse at profile construction instead of relying on Python's
        # unbounded integers and truncating later.
        for field_name, value in (
            ("optimizer_state_bytes", self.optimizer_state_bytes),
            ("simulated_peak_commit_bytes", self.simulated_peak_commit_bytes),
            ("overshoot_margin_bytes", self.overshoot_margin_bytes),
            ("maximum_job_memory_bytes", self.maximum_job_memory_bytes),
            ("required_headroom_bytes", self.required_headroom_bytes),
        ):
            if value > _U64_MAX:
                raise ValueError(f"host mechanism profile {field_name} exceeds u64")

    @property
    def optimizer_state_bytes(self) -> int:
        return self.active_parameters * self.bytes_per_param

    @property
    def simulated_peak_commit_bytes(self) -> int:
        return self.optimizer_state_bytes + self.transient_bytes

    @property
    def overshoot_margin_bytes(self) -> int:
        numerator = (
            self.simulated_peak_commit_bytes * self.overshoot_allowance_basis_points
        )
        return (numerator + 9_999) // 10_000

    @property
    def maximum_job_memory_bytes(self) -> int:
        return self.simulated_peak_commit_bytes + self.overshoot_margin_bytes

    @property
    def required_headroom_bytes(self) -> int:
        return self.maximum_job_memory_bytes + self.reserve_bytes

    def job_memory_envelope_disclosure(self) -> dict[str, Any]:
        return {
            "schema_version": "ember-host-job-memory-envelope-v1",
            "mechanism": self.name,
            "active_parameters": self.active_parameters,
            "bytes_per_param": self.bytes_per_param,
            "optimizer_state_bytes": self.optimizer_state_bytes,
            "transient_bytes": self.transient_bytes,
            "simulated_peak_commit_bytes": self.simulated_peak_commit_bytes,
            "overshoot_allowance_basis": {
                "kind": self.overshoot_allowance_basis or "none",
                "issue_comment": 5289202818
                if self.overshoot_allowance_basis_points
                else None,
                "basis_points": self.overshoot_allowance_basis_points,
            },
            "overshoot_margin_bytes": self.overshoot_margin_bytes,
            "maximum_job_memory_bytes": self.maximum_job_memory_bytes,
            "host_reserve_bytes": self.reserve_bytes,
            "required_headroom_bytes": self.required_headroom_bytes,
        }


def dense_a1_full_state_cpu_offload_profile(
    active_parameters: int = DENSE_A1_REFERENCE_ACTIVE_PARAMETERS,
) -> HostMechanismProfile:
    """The declared host commit-capacity profile for dense-arm A1 training.

    Defaults to the #898 2026-08-21 amendment's reference parameter count
    (3.839161856B), which yields ~60.05 GiB required headroom after the
    evidence-bound overshoot margin -- matching the
    amendment's receipted math (42.9 GiB optimizer state + 8 GiB transient +
    6 GiB reserve).
    """

    if type(active_parameters) is not int or active_parameters <= 0:
        raise ValueError("active parameters must be a positive integer")
    return HostMechanismProfile(
        name="dense-a1-full-state-cpu-offload",
        active_parameters=active_parameters,
        bytes_per_param=_FULL_STATE_ADAMW_CPU_OFFLOAD_BYTES_PER_PARAM,
        transient_bytes=DENSE_A1_TRANSIENT_CHECKPOINT_BYTES,
        reserve_bytes=DENSE_A1_RESERVE_BYTES,
        overshoot_allowance_basis_points=(
            DENSE_A1_JOB_MEMORY_OVERSHOOT_BASIS_POINTS
        ),
        overshoot_allowance_basis=DENSE_A1_JOB_MEMORY_OVERSHOOT_BASIS,
    )


class HostJobMemoryEnvelopeRefusal(RuntimeError):
    """The cap armed by the daemon differs from the mechanism-derived cap."""

    def __init__(
        self,
        *,
        profile: HostMechanismProfile,
        expected_maximum_job_memory_bytes: int,
    ) -> None:
        if (
            type(expected_maximum_job_memory_bytes) is not int
            or expected_maximum_job_memory_bytes <= 0
        ):
            raise ValueError("expected maximum job memory bytes must be a positive integer")
        self.profile = profile
        self.expected_maximum_job_memory_bytes = expected_maximum_job_memory_bytes
        self.derived_maximum_job_memory_bytes = profile.maximum_job_memory_bytes
        super().__init__(
            f"host job-memory envelope refused mechanism '{profile.name}': "
            f"daemon armed {expected_maximum_job_memory_bytes} bytes but the "
            f"mechanism derives {profile.maximum_job_memory_bytes} bytes"
        )


class HostSetupContractRefusal(RuntimeError):
    """The live host cannot host a mechanism's declared commit-capacity profile.

    Distinct from an in-run resource-preflight refusal (``CheckpointDeferredLowCommit``
    in ``checkpoint_artifacts.py``): this fires BEFORE a run is dispatched, at
    host-setup time, and its message always names the exact shortfall in GiB
    and the lawful outcomes. It never encodes the temporary 2026-08-21 OS
    intervention as a repeatable provisioning contract.
    """

    def __init__(self, *, profile: HostMechanismProfile, available_commit_bytes: int) -> None:
        if type(available_commit_bytes) is not int or available_commit_bytes < 0:
            raise ValueError("available commit bytes must be a nonnegative integer")
        self.profile = profile
        self.available_commit_bytes = available_commit_bytes
        self.required_headroom_bytes = profile.required_headroom_bytes
        self.shortfall_bytes = max(0, profile.required_headroom_bytes - available_commit_bytes)
        required_gib = profile.required_headroom_bytes / BYTES_PER_GIB
        available_gib = available_commit_bytes / BYTES_PER_GIB
        shortfall_gib = self.shortfall_bytes / BYTES_PER_GIB
        super().__init__(
            f"host setup contract refused mechanism '{profile.name}': requires "
            f"{required_gib:.2f} GiB host commit headroom (optimizer state "
            f"{profile.optimizer_state_bytes / BYTES_PER_GIB:.2f} GiB + transient "
            f"{profile.transient_bytes / BYTES_PER_GIB:.2f} GiB + evidence-bound "
            f"job-limit overshoot margin "
            f"{profile.overshoot_margin_bytes / BYTES_PER_GIB:.2f} GiB + reserve "
            f"{profile.reserve_bytes / BYTES_PER_GIB:.2f} GiB), but only "
            f"{available_gib:.2f} GiB is available -- shortfall {shortfall_gib:.2f} GiB. "
            f"This headroom is a property of the '{profile.name}' control-experiment "
            f"profile itself, not Ember's normal host floor. No OS provisioning "
            f"exception is encoded by this contract: the mechanism must fit the "
            f"existing envelope, redesign to need less, or fail closed pending a "
            f"separately reviewed mechanism/host contract."
        )


def validate_host_setup_contract(
    profile: HostMechanismProfile,
    *,
    available_commit_bytes_probe: Callable[[], int],
    expected_maximum_job_memory_bytes: int | None = None,
) -> dict[str, Any]:
    """Refuse admission when the live host cannot host ``profile``.

    ``available_commit_bytes_probe`` is injected so this validates against
    any headroom source -- the real Windows probe
    (``checkpoint_artifacts.available_host_commit_bytes``) in production, a
    fixed value in tests -- without this module importing platform-specific
    machinery itself.
    """

    if expected_maximum_job_memory_bytes is not None:
        if (
            type(expected_maximum_job_memory_bytes) is not int
            or expected_maximum_job_memory_bytes <= 0
        ):
            raise ValueError("expected maximum job memory bytes must be a positive integer")
        if expected_maximum_job_memory_bytes != profile.maximum_job_memory_bytes:
            raise HostJobMemoryEnvelopeRefusal(
                profile=profile,
                expected_maximum_job_memory_bytes=expected_maximum_job_memory_bytes,
            )
    if not callable(available_commit_bytes_probe):
        raise ValueError("available commit bytes probe must be callable")
    available_commit_bytes = available_commit_bytes_probe()
    if type(available_commit_bytes) is not int or available_commit_bytes < 0:
        raise ValueError("available commit bytes probe must return a nonnegative integer")
    if available_commit_bytes < profile.required_headroom_bytes:
        raise HostSetupContractRefusal(profile=profile, available_commit_bytes=available_commit_bytes)
    return {
        "status": "PASS",
        "mechanism": profile.name,
        "required_headroom_bytes": profile.required_headroom_bytes,
        "available_commit_bytes": available_commit_bytes,
        "job_memory_envelope": profile.job_memory_envelope_disclosure(),
    }
